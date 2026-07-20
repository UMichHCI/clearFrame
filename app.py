"""
ClearFrame — local web back end
===============================
A tiny, zero-dependency HTTP + SSE backend over run.py's pipeline. It does two
things and nothing more:

  1. Serves the static front end from ./static (index.html, style.css, app.js).
  2. Runs the pipeline on /run and STREAMS its terminal output to the browser,
     line by line, then a structured summary of the selected articles.

The front end lives entirely in ./static — no markup, CSS, or JS in this file.

Run:
    ./venv/bin/python app.py
    # then open http://localhost:8000

Only the Python standard library is used here, so there is nothing to install
beyond what run.py already needs. One run streams at a time (this is a local
debugging tool, not a multi-user server), guarded by a lock.
"""

import base64
import hmac
import json
import mimetypes
import os
import queue
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pandas as pd

from run import run_clearframe_pipeline, CATEGORY_PLAIN_LABELS

# Bind config. Locally these default to localhost:8000. When hosted (e.g. on
# Render), set HOST=0.0.0.0 and the platform injects PORT, so the container
# accepts outside traffic.
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# Optional shared-password gate. If CLEARFRAME_PASSWORD is set, every request
# must carry HTTP Basic Auth credentials whose password matches. This keeps a
# public URL from being an open door to your OpenAI spend. Unset = no auth
# (fine for purely local use). The username is not checked — any value works.
AUTH_PASSWORD = os.environ.get("CLEARFRAME_PASSWORD", "")

# Directory holding the front end (index.html, style.css, app.js).
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Only one pipeline run streams at a time. Redirecting sys.stdout is process
# global, so serialising runs keeps two concurrent runs from interleaving lines.
_run_lock = threading.Lock()


# ─────────────────────────────────────────────
# STDOUT CAPTURE
# ─────────────────────────────────────────────

class QueueWriter:
    """A stdout stand-in that pushes each completed line onto a queue."""

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.q.put(line)
        return len(s)

    def flush(self) -> None:
        if self._buf:
            self.q.put(self._buf)
            self._buf = ""


def _summarize_result(result: dict) -> dict:
    """Pull the user-facing, structured bits out of the pipeline result dict.

    Everything here is safe to show for validation: no outlet ownership context,
    no raw category keys — just what print_user_results would show, as data.
    """
    synthesis = result.get("synthesis") or {}
    out = {
        "overall_synthesis": (synthesis.get("overall_synthesis") or "").strip(),
        "structural_note": (synthesis.get("structural_note") or "").strip(),
        "articles": [],
    }

    selected = result.get("selected_df")
    if isinstance(selected, pd.DataFrame) and not selected.empty:
        for _, row in selected.iterrows():
            strongest = row.get("strongest_category", "")
            out["articles"].append({
                "title": str(row.get("title", "") or ""),
                "domain": str(row.get("domain", "") or ""),
                "sourcecountry": str(row.get("sourcecountry", "") or ""),
                "url": str(row.get("url", "") or ""),
                "why": str(row.get("why_this_article", "") or ""),
                "lens": CATEGORY_PLAIN_LABELS.get(strongest, ""),
                "score": row.get("illumination_score", None),
            })
    return out


def stream_pipeline(url: str, api_key: str, sink: "queue.Queue[dict]") -> None:
    """Run the pipeline, forwarding every printed line to `sink` as an event.

    `api_key` is the caller's own OpenAI key — each visitor brings their own, so
    runs bill the visitor, not the host. It is passed straight to the pipeline
    and never stored or logged.

    Events pushed to the sink are dicts with a `type`:
      {"type": "line",   "text": str}     one line of terminal output
      {"type": "result", "data": dict}    structured summary for the Results tab
      {"type": "error",  "text": str}     the run raised
      {"type": "done"}                     stream complete
    """
    line_q: "queue.Queue[str]" = queue.Queue()
    holder: dict = {}

    def worker():
        writer = QueueWriter(line_q)
        old_stdout = sys.stdout
        sys.stdout = writer
        try:
            holder["result"] = run_clearframe_pipeline(source_url=url, api_key=api_key)
        except Exception as e:  # surfaced to the browser, not swallowed
            holder["error"] = f"{e.__class__.__name__}: {e}"
            holder["traceback"] = traceback.format_exc()
        finally:
            writer.flush()
            sys.stdout = old_stdout
            line_q.put(None)  # sentinel: worker finished

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    while True:
        line = line_q.get()
        if line is None:
            break
        sink.put({"type": "line", "text": line})

    if "error" in holder:
        sink.put({"type": "line", "text": ""})
        sink.put({"type": "line", "text": "──────────── PIPELINE ERROR ────────────"})
        for tb_line in (holder.get("traceback", "")).splitlines():
            sink.put({"type": "line", "text": tb_line})
        sink.put({"type": "error", "text": holder["error"]})
    else:
        sink.put({"type": "result", "data": _summarize_result(holder.get("result", {}))})

    sink.put({"type": "done"})


# ─────────────────────────────────────────────
# HTTP HANDLER
# ─────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    # Quieter logging — the pipeline's own output is what matters.
    def log_message(self, fmt, *args):
        pass

    def _authorized(self) -> bool:
        """True if auth is disabled or the request's Basic-Auth password matches."""
        if not AUTH_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[len("Basic "):]).decode("utf-8")
        except Exception:
            return False
        _, _, password = decoded.partition(":")
        return hmac.compare_digest(password, AUTH_PASSWORD)

    def _require_auth(self):
        """Send a 401 that makes the browser prompt for the shared password."""
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="ClearFrame"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._authorized():
            self._require_auth()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_static("index.html")
        elif parsed.path.startswith("/static/"):
            self._send_static(parsed.path[len("/static/"):])
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if not self._authorized():
            self._require_auth()
            return
        parsed = urlparse(self.path)
        if parsed.path == "/run":
            self._handle_run(self._read_json_body())
        else:
            self.send_error(404, "Not found")

    def _read_json_body(self) -> dict:
        """Parse the request body as JSON, returning {} on any problem.

        The body carries the visitor's URL and their own OpenAI key. It goes in
        a POST body (not the URL query) precisely so the key never lands in
        access logs or browser history.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _send_static(self, rel_path: str):
        """Serve a file from ./static, guarding against path traversal."""
        safe = os.path.normpath(rel_path).lstrip("/\\")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, event: dict):
        payload = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()

    def _handle_run(self, body: dict):
        url = str(body.get("url", "")).strip()
        api_key = str(body.get("api_key", "")).strip()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        if not url:
            self._sse({"type": "error", "text": "No URL provided."})
            self._sse({"type": "done"})
            return

        if not api_key:
            self._sse({"type": "error",
                       "text": "No OpenAI API key provided. Enter your own key above to run."})
            self._sse({"type": "done"})
            return

        if not _run_lock.acquire(blocking=False):
            self._sse({"type": "error",
                       "text": "Another run is in progress. Wait for it to finish."})
            self._sse({"type": "done"})
            return

        sink: "queue.Queue[dict]" = queue.Queue()
        producer = threading.Thread(target=stream_pipeline, args=(url, api_key, sink), daemon=True)
        producer.start()
        try:
            while True:
                event = sink.get()
                try:
                    self._sse(event)
                except (BrokenPipeError, ConnectionResetError):
                    break  # browser navigated away / closed the tab
                if event.get("type") == "done":
                    break
        finally:
            _run_lock.release()


def main():
    ThreadingHTTPServer.allow_reuse_address = True  # avoid stale-socket errors on restart
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        if e.errno == 48:  # EADDRINUSE
            print(f"Port {PORT} is already in use — ClearFrame is probably already running.")
            print(f"  • Just open http://{HOST}:{PORT} in your browser, or")
            print(f"  • Free the port with:  lsof -ti :{PORT} | xargs kill -9")
            return
        raise
    print(f"ClearFrame UI running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
