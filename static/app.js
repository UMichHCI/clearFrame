// ClearFrame front end â€” POSTs to the backend's /run endpoint and renders the
// three views: live Console output, user-facing Results, and structured LLM
// analysis. Each visitor supplies their own OpenAI key; it rides in the
// POST body (not the URL) so it never lands in server logs or history.

const $ = s => document.querySelector(s);
const consoleEl = $("#console"), resultsEl = $("#results"), analysisEl = $("#analysis");
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
  const res = which === "results";
  const ana = which === "analysis";
  $("#tabConsole").classList.toggle("active", con);
  $("#tabResults").classList.toggle("active", res);
  $("#tabAnalysis").classList.toggle("active", ana);
  consoleEl.style.display = con ? "" : "none";
  $("#consoleTools").style.display = con ? "" : "none";
  resultsEl.style.display = res ? "" : "none";
  analysisEl.style.display = ana ? "" : "none";
}
$("#tabConsole").onclick = () => showTab("console");
$("#tabResults").onclick = () => showTab("results");
$("#tabAnalysis").onclick = () => showTab("analysis");

function setStatus(cls, text){ dot.className = "dot " + cls; statusText.textContent = text; }
$("#clearLog").onclick = () => { consoleEl.innerHTML = ""; rawLog = ""; };
$("#copyLog").onclick = () => navigator.clipboard.writeText(rawLog);

// Colorize a terminal line by its recognizable prefixes/markers.
function classify(line){
  if (/^\s*\[\d\/9\]/.test(line)) return "stage";
  if (/\[WARNING\]/.test(line)) return "warn";
  if (/ERROR|Traceback|Exception|Error:/.test(line)) return "err";
  if (/\[DEV\]/.test(line)) return "dev";
  if (/\[DEBUG\]/.test(line)) return "debug";
  if (/\[PASS\]/.test(line)) return "pass";
  if (/\[drop\]/.test(line)) return "drop";
  if (/^[\sâ”€=]+$/.test(line)) return "rule";
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
  const cats = data.categories || [];
  $("#resCount").textContent = cats.length ? "(" + cats.length + ")" : "";
  let html = "";
  if (data.summary){
    html += '<div class="synth"><h3>Summary</h3>' + escapeHtml(data.summary);
    const summaryRefs = data.summary_supporting_articles || [];
    if (summaryRefs.length){
      html += '<div class="meta" style="margin-top:10px">References</div>';
      summaryRefs.forEach(a => {
        const title = a.title || "Untitled";
        const country = a.source_country || a.outlet || "";
        const url = a.url || "";
        html += '<div style="margin-top:6px">' +
          (url ? '<a href="' + encodeURI(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' : escapeHtml(title)) +
          (country ? ' <span class="meta">(' + escapeHtml(country) + ')</span>' : '') +
          '</div>';
      });
    }
    html += '</div>';
  }
  if (data.structural_note){
    html += '<div class="note">' + escapeHtml(data.structural_note) + '</div>';
  }
  if (!cats.length){
    html += '<div class="empty">No meaningful category-level differences surfaced for this story.</div>';
  } else {
    html += '<details class="category-details"><summary>Category Details</summary><div class="details-body">';
    cats.forEach(c => {
      const refs = c.supporting_articles || [];
      html += '<div class="card"><div class="top">' +
        '<div><div class="title">' + escapeHtml(c.label || c.key || "Category") + '</div></div>' +
        '</div>' +
        '<div class="why">' + escapeHtml(c.paragraph) + '</div>';
      if (refs.length){
        html += '<div class="meta" style="margin-top:10px">References</div>';
        refs.forEach(a => {
          const title = a.title || "Untitled";
          const outlet = a.outlet || "";
          const url = a.url || "";
          html += '<div style="margin-top:6px">' +
            (url ? '<a href="' + encodeURI(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' : escapeHtml(title)) +
            (outlet ? ' <span class="meta">(' + escapeHtml(outlet) + ')</span>' : '') +
            '</div>';
        });
      }
      html += '</div>';
    });
    html += '</div></details>';
  }
  resultsEl.innerHTML = html;
}

function renderAnalysis(data){
  const analysis = data.llm_analysis || {};
  const pairs = analysis.pair_extractions || [];
  $("#analysisCount").textContent = pairs.length ? "(" + pairs.length + ")" : "";

  let html = "";
  html += analysisSection("Source Article Extraction", renderJsonBlock(analysis.source_extraction || {}));
  html += analysisSection("Pair Extractions", renderPairs(pairs));
  html += analysisSection("Final Synthesis", renderJsonBlock(analysis.category_synthesis || {}));
  analysisEl.innerHTML = html;
}

function analysisSection(title, body){
  return '<section class="analysis-section"><h3>' + escapeHtml(title) + '</h3>' + body + '</section>';
}

function renderPairs(pairs){
  if (!pairs.length) return '<div class="empty compact">No pair extraction output.</div>';
  return pairs.map(pair => {
    const ref = pair.article_reference || {};
    const title = ref.title || "Untitled";
    const country = ref.source_country || "";
    const outlet = ref.outlet || "";
    const answers = pair.category_answers || {};
    let body = '<div class="meta">' + escapeHtml([country, outlet].filter(Boolean).join(" · ")) + '</div>';
    Object.keys(answers).forEach(key => {
      body += '<details class="analysis-detail"><summary>' + escapeHtml(labelCategory(key)) + '</summary>' +
        renderJsonBlock(answers[key]) + '</details>';
    });
    return '<details class="analysis-card"><summary>' +
      '<span>' + escapeHtml(title) + '</span><span class="meta">row ' + escapeHtml(pair.row_index) + '</span>' +
      '</summary><div class="analysis-body">' + body + '</div></details>';
  }).join("");
}

function renderJsonBlock(value){
  return '<pre class="json-block">' + escapeHtml(JSON.stringify(value || {}, null, 2)) + '</pre>';
}

function labelCategory(key){
  return String(key || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// Dispatch a single decoded SSE event to the right renderer.
function handleMsg(msg){
  if (msg.type === "line") appendLine(msg.text);
  else if (msg.type === "result"){ renderResults(msg.data); renderAnalysis(msg.data); setStatus("ok", "Done. See Results and LLM Analysis."); }
  else if (msg.type === "error"){ appendLine("ERROR: " + msg.text); setStatus("err", "Failed: " + msg.text); }
  else if (msg.type === "done"){
    if (dot.className.indexOf("err") === -1 && dot.className.indexOf("ok") === -1) setStatus("ok", "Finished.");
  }
}

// Read the streaming SSE response body, parsing "data: â€¦\n\n" frames as they
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

  consoleEl.innerHTML = ""; resultsEl.innerHTML = ""; analysisEl.innerHTML = ""; rawLog = "";
  $("#resCount").textContent = "";
  $("#analysisCount").textContent = "";
  showTab("console");
  running = true; goBtn.disabled = true;
  setStatus("run", "Runningâ€¦ (this takes ~30â€“90s; watch it stream below)");

  try {
    await streamRun(url, apiKey);
  } catch (err) {
    setStatus("err", "Connection lost. Is the server still running?");
  } finally {
    running = false; goBtn.disabled = false;
  }
});

