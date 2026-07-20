// ClearFrame front end — POSTs to the backend's /run endpoint and renders the
// two views: a live terminal Console (debugging) and structured result cards
// (validation). Each visitor supplies their own OpenAI key; it rides in the
// POST body (not the URL) so it never lands in server logs or history.

const $ = s => document.querySelector(s);
const consoleEl = $("#console"), resultsEl = $("#results");
const dot = $("#dot"), statusText = $("#statusText"), goBtn = $("#go");
const keyEl = $("#apiKey"), rememberEl = $("#remember");
let running = false, rawLog = "";

// Restore a remembered key from this browser (opt-in only).
const KEY_STORE = "clearframe.openai_key";
const savedKey = localStorage.getItem(KEY_STORE);
if (savedKey){ keyEl.value = savedKey; rememberEl.checked = true; }

// Tabs
function showTab(which){
  const con = which === "console";
  $("#tabConsole").classList.toggle("active", con);
  $("#tabResults").classList.toggle("active", !con);
  consoleEl.style.display = con ? "" : "none";
  $("#consoleTools").style.display = con ? "" : "none";
  resultsEl.style.display = con ? "none" : "";
}
$("#tabConsole").onclick = () => showTab("console");
$("#tabResults").onclick = () => showTab("results");

function setStatus(cls, text){ dot.className = "dot " + cls; statusText.textContent = text; }
$("#clearLog").onclick = () => { consoleEl.innerHTML = ""; rawLog = ""; };
$("#copyLog").onclick = () => navigator.clipboard.writeText(rawLog);

// Colorize a terminal line by its recognizable prefixes/markers.
function classify(line){
  if (/^\s*\[\d\/9\]/.test(line)) return "stage";
  if (/\[WARNING\]/.test(line)) return "warn";
  if (/ERROR|Traceback|Exception|Error:/.test(line)) return "err";
  if (/\[DEV\]|BACKEND ONLY/.test(line)) return "dev";
  if (/\[DEBUG\]/.test(line)) return "debug";
  if (/\[PASS\]/.test(line)) return "pass";
  if (/\[drop\]/.test(line)) return "drop";
  if (/^[\s─=]+$/.test(line)) return "rule";
  return "";
}

function appendLine(text){
  rawLog += text + "\n";
  const span = document.createElement("span");
  const cls = classify(text);
  if (cls) span.className = cls;
  span.textContent = text + "\n";
  const atBottom = consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 40;
  consoleEl.appendChild(span);
  if (atBottom) consoleEl.scrollTop = consoleEl.scrollHeight;
}

function renderResults(data){
  const arts = data.articles || [];
  $("#resCount").textContent = arts.length ? "(" + arts.length + ")" : "";
  let html = "";
  if (data.overall_synthesis){
    html += '<div class="synth"><h3>What these articles together let you see</h3>' +
            escapeHtml(data.overall_synthesis) + '</div>';
  }
  if (data.structural_note){
    html += '<div class="note">' + escapeHtml(data.structural_note) + '</div>';
  }
  if (!arts.length){
    html += '<div class="empty">No comparison articles surfaced for this story.</div>';
  } else {
    arts.forEach((a, i) => {
      html += '<div class="card"><div class="top">' +
        '<div><div class="title">#' + (i+1) + '  ' + escapeHtml(a.title || "Untitled") + '</div>' +
        '<div class="meta">' + escapeHtml(a.domain) + ' · ' + escapeHtml(a.sourcecountry) + '</div></div>' +
        (a.score != null ? '<div class="score">score ' + a.score + '</div>' : '') +
        '</div>' +
        (a.lens ? '<span class="lens">' + escapeHtml(a.lens) + '</span>' : '') +
        '<div class="why">' + escapeHtml(a.why) + '</div>' +
        (a.url ? '<div style="margin-top:8px"><a href="' + encodeURI(a.url) + '" target="_blank" rel="noopener">' + escapeHtml(a.url) + '</a></div>' : '') +
        '</div>';
    });
  }
  resultsEl.innerHTML = html;
}

function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// Dispatch a single decoded SSE event to the right renderer.
function handleMsg(msg){
  if (msg.type === "line") appendLine(msg.text);
  else if (msg.type === "result"){ renderResults(msg.data); setStatus("ok", "Done. See the Results tab for the validated output."); }
  else if (msg.type === "error"){ appendLine("ERROR: " + msg.text); setStatus("err", "Failed: " + msg.text); }
  else if (msg.type === "done"){
    if (dot.className.indexOf("err") === -1 && dot.className.indexOf("ok") === -1) setStatus("ok", "Finished.");
  }
}

// Read the streaming SSE response body, parsing "data: …\n\n" frames as they
// arrive. We use fetch (not EventSource) so the key can go in the POST body.
async function streamRun(url, apiKey){
  const resp = await fetch("/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, api_key: apiKey }),
  });
  if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true){
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1){
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const data = frame.split("\n")
        .filter(l => l.startsWith("data:"))
        .map(l => l.slice(5).trim())
        .join("");
      if (data) handleMsg(JSON.parse(data));
    }
  }
}

$("#form").addEventListener("submit", async e => {
  e.preventDefault();
  if (running) return;
  const url = $("#url").value.trim();
  const apiKey = keyEl.value.trim();
  if (!url) return;
  if (!apiKey){ setStatus("err", "Enter your OpenAI API key to run."); keyEl.focus(); return; }

  // Persist (or clear) the key per the checkbox.
  if (rememberEl.checked) localStorage.setItem(KEY_STORE, apiKey);
  else localStorage.removeItem(KEY_STORE);

  consoleEl.innerHTML = ""; resultsEl.innerHTML = ""; rawLog = "";
  $("#resCount").textContent = "";
  showTab("console");
  running = true; goBtn.disabled = true;
  setStatus("run", "Running… (this takes ~30–90s; watch it stream below)");

  try {
    await streamRun(url, apiKey);
  } catch (err) {
    setStatus("err", "Connection lost. Is the server still running?");
  } finally {
    running = false; goBtn.disabled = false;
  }
});
