// ClearFrame front end â€” POSTs to the backend's /run endpoint and renders the
// three views: live Console output, user-facing Results, and structured LLM
// analysis. Each visitor supplies their own OpenAI key; it rides in the
// POST body (not the URL) so it never lands in server logs or history.

const $ = s => document.querySelector(s);
const consoleEl = $("#console"), resultsEl = $("#results"), analysisEl = $("#analysis");
const dot = $("#dot"), statusText = $("#statusText"), goBtn = $("#go");
const keyEl = $("#apiKey"), rememberEl = $("#remember");
const copyResultsBtn = $("#copyResults");
let running = false, rawLog = "", latestResults = null;

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
  $("#resultsTools").style.display = res ? "" : "none";
  resultsEl.style.display = res ? "" : "none";
  analysisEl.style.display = ana ? "" : "none";
}
$("#tabConsole").onclick = () => showTab("console");
$("#tabResults").onclick = () => showTab("results");
$("#tabAnalysis").onclick = () => showTab("analysis");

function setStatus(cls, text){ dot.className = "dot " + cls; statusText.textContent = text; }
$("#clearLog").onclick = () => { consoleEl.innerHTML = ""; rawLog = ""; };
$("#copyLog").onclick = () => navigator.clipboard.writeText(rawLog);

function referenceText(article){
  const title = article.title || "Untitled";
  const source = article.source_country || article.outlet || "";
  const url = article.url || "";
  return "- " + title + (source ? " (" + source + ")" : "") + (url ? ": " + url : "");
}

function groupArticlesByCountry(articles){
  const groups = new Map();
  articles.forEach(article => {
    const country = article.source_country || "Unknown country";
    if (!groups.has(country)) groups.set(country, []);
    groups.get(country).push(article);
  });
  return groups;
}

function addGroupedArticlesHtml(parts, articles){
  groupArticlesByCountry(articles).forEach((countryArticles, country) => {
    parts.push("<h3>" + escapeHtml(country) + "</h3><ul>");
    countryArticles.forEach(article => {
      const title = escapeHtml(article.title || "Untitled");
      const outlet = escapeHtml(article.outlet || "");
      const role = article.role === "source" ? "Source" : "Comparison";
      const url = safeHttpUrl(article.url || "");
      const linkedTitle = url
        ? '<a href="' + escapeAttribute(url) + '">' + title + "</a>"
        : title;
      parts.push("<li>[" + escapeHtml(role) + "] " + linkedTitle +
        (outlet ? " (" + outlet + ")" : "") + "</li>");
    });
    parts.push("</ul>");
  });
}

function resultsAsPlainText(data){
  const lines = ["ClearFrame Results"];
  if (data.stop_reason) lines.push("", "Analysis stopped", data.stop_reason);
  if (data.summary){
    lines.push("", "Summary", data.summary);
    const refs = data.summary_supporting_articles || [];
    if (refs.length) lines.push("", "References", ...refs.map(referenceText));
  }
  if (data.structural_note) lines.push("", "Structural note", data.structural_note);
  const categories = data.categories || [];
  if (categories.length) lines.push("", "Category Details");
  else lines.push("", "No meaningful category-level differences surfaced for this story.");
  categories.forEach(category => {
    lines.push("", category.label || category.key || "Category", category.paragraph || "");
    const refs = category.supporting_articles || [];
    if (refs.length) lines.push("", "References", ...refs.map(referenceText));
  });
  const analysisArticles = data.analysis_articles || [];
  if (analysisArticles.length){
    lines.push("", "Articles Used in This Analysis");
    groupArticlesByCountry(analysisArticles).forEach((countryArticles, country) => {
      lines.push("", country, ...countryArticles.map(referenceText));
    });
  }
  return lines.join("\n").trim() + "\n";
}

function addReferencesHtml(parts, references){
  if (!references.length) return;
  parts.push("<h3>References</h3><ul>");
  references.forEach(article => {
    const title = escapeHtml(article.title || "Untitled");
    const source = escapeHtml(article.source_country || article.outlet || "");
    const url = safeHttpUrl(article.url || "");
    const linkedTitle = url
      ? '<a href="' + escapeAttribute(url) + '">' + title + "</a>"
      : title;
    parts.push("<li>" + linkedTitle + (source ? " (" + source + ")" : "") + "</li>");
  });
  parts.push("</ul>");
}

function resultsAsHtml(data){
  const parts = ['<div><h1>ClearFrame Results</h1>'];
  if (data.stop_reason){
    parts.push("<h2>Analysis stopped</h2><p>" + textAsHtml(data.stop_reason) + "</p>");
  }
  if (data.summary){
    parts.push("<h2>Summary</h2><p>" + textAsHtml(data.summary) + "</p>");
    addReferencesHtml(parts, data.summary_supporting_articles || []);
  }
  if (data.structural_note){
    parts.push("<h2>Structural note</h2><p><em>" + textAsHtml(data.structural_note) + "</em></p>");
  }
  const categories = data.categories || [];
  if (categories.length) parts.push("<h2>Category Details</h2>");
  else parts.push("<p>No meaningful category-level differences surfaced for this story.</p>");
  categories.forEach(category => {
    parts.push("<h3>" + escapeHtml(category.label || category.key || "Category") + "</h3>");
    parts.push("<p>" + textAsHtml(category.paragraph || "") + "</p>");
    addReferencesHtml(parts, category.supporting_articles || []);
  });
  const analysisArticles = data.analysis_articles || [];
  if (analysisArticles.length){
    parts.push("<h2>Articles Used in This Analysis</h2>");
    addGroupedArticlesHtml(parts, analysisArticles);
  }
  parts.push("</div>");
  return parts.join("");
}

async function copyResults(){
  if (!latestResults) return;
  const plainText = resultsAsPlainText(latestResults);
  const richHtml = resultsAsHtml(latestResults);
  const originalLabel = copyResultsBtn.textContent;
  try {
    if (navigator.clipboard.write && window.ClipboardItem){
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([richHtml], { type: "text/html" }),
        "text/plain": new Blob([plainText], { type: "text/plain" }),
      })]);
    } else {
      await navigator.clipboard.writeText(plainText);
    }
    copyResultsBtn.textContent = "Copied!";
  } catch (err) {
    copyResultsBtn.textContent = "Copy failed";
  }
  window.setTimeout(() => { copyResultsBtn.textContent = originalLabel; }, 1800);
}

copyResultsBtn.onclick = copyResults;

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
  latestResults = data;
  copyResultsBtn.disabled = false;
  const cats = data.categories || [];
  $("#resCount").textContent = cats.length ? "(" + cats.length + ")" : "";
  let html = "";
  if (data.stop_reason){
    html += '<div class="stop-reason"><h3>Analysis stopped</h3>' +
      escapeHtml(data.stop_reason) + '</div>';
  }
  if (data.summary){
    html += '<div class="synth"><h3>Summary</h3>' + escapeHtml(data.summary);
    const summaryRefs = data.summary_supporting_articles || [];
    if (summaryRefs.length){
      html += '<div class="meta" style="margin-top:10px">References</div>';
      summaryRefs.forEach(a => {
        const title = a.title || "Untitled";
        const country = a.source_country || a.outlet || "";
        const url = safeHttpUrl(a.url || "");
        html += '<div style="margin-top:6px">' +
          (url ? '<a href="' + escapeAttribute(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' : escapeHtml(title)) +
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
          const url = safeHttpUrl(a.url || "");
          html += '<div style="margin-top:6px">' +
            (url ? '<a href="' + escapeAttribute(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' : escapeHtml(title)) +
            (outlet ? ' <span class="meta">(' + escapeHtml(outlet) + ')</span>' : '') +
            '</div>';
        });
      }
      html += '</div>';
    });
    html += '</div></details>';
  }
  const analysisArticles = data.analysis_articles || [];
  if (analysisArticles.length){
    html += '<section class="used-articles"><h3>Articles Used in This Analysis</h3>' +
      '<div class="meta">The source article and every comparison article sent to pair analysis.</div>';
    groupArticlesByCountry(analysisArticles).forEach((countryArticles, country) => {
      html += '<div class="country-group"><h4>' + escapeHtml(country) + '</h4><ul>';
      countryArticles.forEach(article => {
        const title = article.title || "Untitled";
        const outlet = article.outlet || "";
        const url = safeHttpUrl(article.url || "");
        const role = article.role === "source" ? "Source" : "Comparison";
        html += '<li><span class="article-role">' + escapeHtml(role) + '</span>' +
          (url ? '<a href="' + escapeAttribute(url) + '" target="_blank" rel="noopener">' + escapeHtml(title) + '</a>' : escapeHtml(title)) +
          (outlet ? ' <span class="meta">(' + escapeHtml(outlet) + ')</span>' : '') + '</li>';
      });
      html += '</ul></div>';
    });
    html += '</section>';
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

function escapeAttribute(s){
  return escapeHtml(s).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function safeHttpUrl(value){
  try {
    const parsed = new URL(String(value || ""));
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : "";
  } catch (_err) {
    return "";
  }
}

function textAsHtml(s){
  return escapeHtml(s).replace(/\r?\n/g, "<br>");
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
  latestResults = null;
  copyResultsBtn.disabled = true;
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

