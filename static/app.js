// ClearFrame front end — talks to the backend's /run SSE endpoint and renders
// the two views: a live terminal Console (debugging) and structured result
// cards (validation).

const EXAMPLES = [
  ["AP · Ukraine", "https://apnews.com/article/ukraine-russia-war-kyiv-strikes-july-2026-83bcba8bb972ce248a805bc576a7322c"],
  ["Al Jazeera · Nigeria", "https://www.aljazeera.com/news/2026/3/17/many-killed-wounded-after-blasts-hit-nigerias-maiduguri-witnesses-say"],
  ["NBC · North Korea", "https://www.nbcnews.com/world/north-korea/north-korea-fires-missiles-sea-show-force-seoul-rcna263450"],
];

const $ = s => document.querySelector(s);
const consoleEl = $("#console"), resultsEl = $("#results");
const dot = $("#dot"), statusText = $("#statusText"), goBtn = $("#go");
let evtSource = null, rawLog = "";

// Example chips
const exWrap = $("#examples");
EXAMPLES.forEach(([label, url]) => {
  const b = document.createElement("button");
  b.type = "button"; b.textContent = label;
  b.onclick = () => { $("#url").value = url; };
  exWrap.appendChild(b);
});

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

$("#form").addEventListener("submit", e => {
  e.preventDefault();
  const url = $("#url").value.trim();
  if (!url) return;
  if (evtSource) evtSource.close();
  consoleEl.innerHTML = ""; resultsEl.innerHTML = ""; rawLog = "";
  $("#resCount").textContent = "";
  showTab("console");
  goBtn.disabled = true;
  setStatus("run", "Running… (this takes ~30–90s; watch it stream below)");

  evtSource = new EventSource("/run?url=" + encodeURIComponent(url));
  evtSource.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "line") appendLine(msg.text);
    else if (msg.type === "result"){ renderResults(msg.data); setStatus("ok", "Done. See the Results tab for the validated output."); }
    else if (msg.type === "error"){ appendLine("ERROR: " + msg.text); setStatus("err", "Failed: " + msg.text); }
    else if (msg.type === "done"){ evtSource.close(); evtSource = null; goBtn.disabled = false;
      if (dot.className.indexOf("err") === -1 && dot.className.indexOf("ok") === -1) setStatus("ok", "Finished."); }
  };
  evtSource.onerror = () => {
    setStatus("err", "Connection lost. Is app.py still running?");
    goBtn.disabled = false;
    if (evtSource){ evtSource.close(); evtSource = null; }
  };
});
