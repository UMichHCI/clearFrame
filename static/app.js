// ClearFrame front end â€” POSTs to the backend's /run endpoint and renders the
// three views: live Console output, user-facing Results, and structured LLM
// analysis. Each visitor supplies their own OpenAI key; it rides in the
// POST body (not the URL) so it never lands in server logs or history.

const $ = s => document.querySelector(s);
const consoleEl = $("#console"), resultsEl = $("#results"), analysisEl = $("#analysis");
const dot = $("#dot"), statusText = $("#statusText"), goBtn = $("#go");
const keyEl = $("#apiKey"), rememberEl = $("#remember");
const copyResultsBtn = $("#copyResults");
const printResultsBtn = $("#printResults");
const resultsFileInput = $("#resultsFile");
const importStatus = $("#importStatus");
const saveResultsBtn = $("#saveResults");
const sectionModes = new Map(), renderedMemes = new Map();
let memeState = 'idle', memeError = '', memeController = null, memeRenderVersion = 0;
let perspectiveState = 'idle', perspectiveError = '', perspectiveController = null, perspectiveVersion = 0;
let running = false, rawLog = "", latestResults = null;
let runGeneration = 0;

const CATEGORY_TITLES = {
  worthy_unworthy_victims: "Whose suffering gets attention",
  agency_attribution: "Who gets blamed",
  presuppositions_doctrine: "What goes unquestioned",
  selective_criteria: "How actions are judged",
  suppressed_alternative: "What other explanations are missing",
  smoke_and_discrepancies: "Distractions and conflicting facts",
};

function categoryTitle(category){
  return (Object.hasOwn(CATEGORY_TITLES, category.key) ? CATEGORY_TITLES[category.key] : '') ||
    category.label || labelCategory(category.key) || "Difference";
}

const CATEGORY_DESCRIPTIONS = {
  worthy_unworthy_victims: "Whose harm gets explained, and whose gets less attention.",
  agency_attribution: "Who the article blames, excuses, or leaves unnamed.",
  presuppositions_doctrine: "Ideas the article accepts without examining them.",
  selective_criteria: "What counts as success or failure, and whether the same rules apply to everyone.",
  suppressed_alternative: "Possible causes or ways forward that the article does not explore.",
  smoke_and_discrepancies: "Side issues that draw attention away from important questions, or facts the articles disagree on.",
};

// Restore a remembered key from this browser (opt-in only).
const KEY_STORE = "clearframe.openai_key";
let savedKey = null;
try { savedKey = localStorage.getItem(KEY_STORE); } catch (_err) { /* Storage may be blocked. */ }
if (savedKey){ keyEl.value = savedKey; rememberEl.checked = true; }

// Tabs
function showTab(which){
  const con = which === "console";
  const res = which === "results";
  const ana = which === "analysis";
  [["#tabConsole", con], ["#tabResults", res], ["#tabAnalysis", ana]].forEach(([id, selected]) => {
    $(id).classList.toggle("active", selected);
    $(id).setAttribute("aria-selected", String(selected));
    $(id).tabIndex = selected ? 0 : -1;
  });
  $("#consoleView").style.display = con ? "" : "none";
  $("#resultsTools").style.display = res ? "" : "none";
  $("#resultsImport").style.display = res ? "" : "none";
  resultsEl.style.display = res ? "" : "none";
  analysisEl.style.display = ana ? "" : "none";
}
$("#tabConsole").onclick = () => showTab("console");
$("#tabResults").onclick = () => showTab("results");
$("#tabAnalysis").onclick = () => showTab("analysis");
const viewTabs = [["#tabResults", "results"], ["#tabConsole", "console"], ["#tabAnalysis", "analysis"]];
viewTabs.forEach(([id], index) => {
  $(id).addEventListener("keydown", event => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % viewTabs.length;
    else if (event.key === "ArrowLeft") next = (index + viewTabs.length - 1) % viewTabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = viewTabs.length - 1;
    else return;
    event.preventDefault();
    showTab(viewTabs[next][1]);
    $(viewTabs[next][0]).focus();
  });
});

function setStatus(cls, text){ dot.className = "dot " + cls; statusText.textContent = text; }
$("#clearLog").onclick = () => { consoleEl.innerHTML = ""; rawLog = ""; };
$("#copyLog").onclick = () => navigator.clipboard.writeText(rawLog);

function referenceText(article){
  const title = article.title || "Untitled";
  const source = article.source_country || article.outlet || "";
  const url = article.url || "";
  const number = article.citation_id ? "[" + article.citation_id + "] " : "";
  return "- " + number + title + (source ? " (" + source + ")" : "") + (url ? ": " + url : "");
}

function summaryAsHtml(summary, references){
  const byId = new Map(references.map(article => [String(article.citation_id), article]));
  const linkedText = textAsHtml(summary).replace(/\[(\d+)\]/g, (marker, number) => {
    const article = byId.get(number);
    const url = article ? safeHttpUrl(article.url || "") : "";
    return url
      ? '<a href="' + escapeAttribute(url) + '" target="_blank" rel="noopener">' + marker + '</a>'
      : marker;
  });
  return '<p>' + linkedText.replace(/(?:<br>\s*){2,}/g, '</p><p>') + '</p>';
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
      const sourceTag = article.role === "source" ? "[Your article] " : "";
      const url = safeHttpUrl(article.url || "");
      const linkedTitle = url
        ? '<a href="' + escapeAttribute(url) + '">' + title + "</a>"
        : title;
      parts.push("<li>" + sourceTag + linkedTitle +
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
  if (data.structural_note) lines.push("", "About this comparison", data.structural_note);
  const categories = data.categories || [];
  if (categories.length) lines.push("", "Findings explained");
  else lines.push("", "The comparison did not find clear evidence of an important difference in how these articles explain the story.");
  categories.forEach(category => {
    lines.push("", categoryTitle(category));
    const description = CATEGORY_DESCRIPTIONS[category.key];
    if (description) lines.push(description);
    lines.push(category.paragraph || "");
    const refs = category.supporting_articles || [];
    if (refs.length) lines.push("", "References", ...refs.map(referenceText));
  });
  const analysisArticles = data.analysis_articles || [];
  if (analysisArticles.length){
    lines.push("", "Articles compared");
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
    const number = article.citation_id ? "[" + escapeHtml(String(article.citation_id)) + "] " : "";
    parts.push("<li>" + number + linkedTitle + (source ? " (" + source + ")" : "") + "</li>");
  });
  parts.push("</ul>");
}

function resultsAsHtml(data){
  const parts = ['<div><h1>ClearFrame Results</h1>'];
  if (data.stop_reason){
    parts.push("<h2>Analysis stopped</h2><p>" + textAsHtml(data.stop_reason) + "</p>");
  }
  if (data.summary){
    parts.push("<h2>Summary</h2>" + summaryAsHtml(data.summary, data.summary_supporting_articles || []));
    addReferencesHtml(parts, data.summary_supporting_articles || []);
  }
  if (data.structural_note){
    parts.push("<h2>About this comparison</h2><p><em>" + textAsHtml(data.structural_note) + "</em></p>");
  }
  const categories = data.categories || [];
  if (categories.length) parts.push("<h2>Findings explained</h2>");
  else parts.push("<p>The comparison did not find clear evidence of an important difference in how these articles explain the story.</p>");
  categories.forEach(category => {
    parts.push("<h3>" + escapeHtml(categoryTitle(category)) + "</h3>");
    const description = CATEGORY_DESCRIPTIONS[category.key];
    if (description) parts.push("<p><em>" + escapeHtml(description) + "</em></p>");
    parts.push("<p>" + textAsHtml(category.paragraph || "") + "</p>");
    addReferencesHtml(parts, category.supporting_articles || []);
  });
  const analysisArticles = data.analysis_articles || [];
  if (analysisArticles.length){
    parts.push("<h2>Articles compared</h2>");
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
printResultsBtn.onclick = async () => {
  if (!latestResults) return;
  if (sectionModes.get('overview') === 'comic') await globalThis.ClearFrameComic?.ready($('#overview-comic'));
  window.print();
};

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

function articleLink(article){
  const title = escapeHtml(article.title || "Untitled article");
  const url = safeHttpUrl(article.url || "");
  return url ? '<a href="' + escapeAttribute(url) + '" target="_blank" rel="noopener noreferrer">' + title + '</a>' : title;
}

function reportArticles(articles){
  return '<ul class="article-list">' + articles.map(article => {
    const metadata = [article.source_country, article.outlet].filter(Boolean).join(" / ");
    const number = article.citation_id ? '[' + escapeHtml(String(article.citation_id)) + '] ' : '';
    return '<li>' + number + articleLink(article) +
      (metadata ? '<span class="article-meta">' + escapeHtml(metadata) + '</span>' : '') + '</li>';
  }).join('') + '</ul>';
}

function reportReferences(articles){
  if (!articles.length) return '';
  return '<div class="references"><h4>Supporting articles</h4>' + reportArticles(articles) + '</div>';
}

function findingAsHtml(paragraph){
  const text = String(paragraph || '');
  const split = text.search(/(?<=[.!?])\s+(?=[A-Z])/);
  if (split === -1) return '<strong>' + textAsHtml(text) + '</strong>';
  return '<strong>' + textAsHtml(text.slice(0, split)) + '</strong>' + textAsHtml(text.slice(split));
}

function sectionViewModes(id){
  return id === 'overview' ? ['high', 'middle', 'comic', 'low'] : ['high', 'low'];
}

function sectionViews(id, label, highContent){
  sectionModes.set(id, 'high');
  const middleTab = id === 'overview' ? '<button id="overview-tab-middle" type="button" role="tab" aria-selected="false" aria-controls="overview-middle" tabindex="-1" data-section="overview" data-section-mode="middle">Middle fidelity</button>' : '';
  const comicTab = id === 'overview' ? '<button id="overview-tab-comic" type="button" role="tab" aria-selected="false" aria-controls="overview-comic" tabindex="-1" data-section="overview" data-section-mode="comic">Comic</button>' : '';
  const comicPanel = id === 'overview' ? '<div id="overview-comic" class="section-comic" role="tabpanel" aria-labelledby="overview-tab-comic" tabindex="0" hidden>' +
    (globalThis.ClearFrameComic?.render() || '<p class="empty">The comic could not be loaded. Reload this page to try again.</p>') + '</div>' : '';
  const middlePanel = id === 'overview' ? '<div id="overview-middle" class="section-middle" role="tabpanel" aria-labelledby="overview-tab-middle" tabindex="0" hidden>' +
    '<div id="overview-map"></div><div id="perspectiveControls" class="meme-controls">' +
    '<p id="perspectiveStatus" class="meme-status" role="status" aria-live="polite"></p>' +
    '<p id="perspectivePrivacy" class="meme-privacy">Making a map sends the analysis and article references to OpenAI and uses your account. This is a separate request from making memes.</p>' +
    '<button type="button" id="generatePerspectives" class="generate-memes" data-generate-perspectives>Generate map</button></div></div>' : '';
  return '<div class="section-modes" role="tablist" aria-label="View for ' + escapeAttribute(label) + '">' +
    '<button id="' + id + '-tab-high" type="button" role="tab" aria-selected="true" aria-controls="' + id + '-high" data-section="' + id + '" data-section-mode="high">High fidelity</button>' +
    middleTab + comicTab +
    '<button id="' + id + '-tab-low" type="button" role="tab" aria-selected="false" aria-controls="' + id + '-low" tabindex="-1" data-section="' + id + '" data-section-mode="low">Low fidelity</button></div>' +
    '<div id="' + id + '-high" class="section-high" role="tabpanel" aria-labelledby="' + id + '-tab-high" tabindex="0">' + highContent + '</div>' +
    middlePanel + comicPanel +
    '<div id="' + id + '-low" class="section-low" role="tabpanel" aria-labelledby="' + id + '-tab-low" tabindex="0" hidden>' +
    '<div id="' + id + '-meme" class="section-meme"></div>' +
    '<div id="' + id + '-meme-controls" class="meme-controls">' +
    '<p id="' + id + '-meme-status" class="meme-status" role="status" aria-live="polite"></p>' +
    '<p id="' + id + '-meme-privacy" class="meme-privacy">Making memes sends the summary text to OpenAI and uses your account. One request makes the short versions for all sections.</p>' +
    '<button id="' + id + '-generate-memes" type="button" class="generate-memes" data-generate-memes>Generate memes</button></div></div>';
}

function renderResults(data){
  if (perspectiveController) perspectiveController.abort();
  perspectiveController = null; perspectiveVersion += 1;
  perspectiveState = 'idle'; perspectiveError = '';
  globalThis.ClearFramePerspectives?.clear();
  if (memeController) memeController.abort();
  memeController = null;
  memeRenderVersion += 1;
  memeState = 'idle'; memeError = '';
  sectionModes.clear(); renderedMemes.clear();
  latestResults = data;
  saveResultsBtn.disabled = false;
  copyResultsBtn.disabled = false;
  printResultsBtn.disabled = false;
  const cats = data.categories || [];
  const articles = data.analysis_articles || [];
  const source = articles.find(article => article.role === 'source');
  const comparisons = articles.filter(article => article.role !== 'source');
  const countries = new Set(articles.map(article => article.source_country).filter(Boolean));
  $("#resCount").textContent = cats.length ? String(cats.length) : '';
  let html = '<article class="report"><header class="report-heading"><p class="eyebrow">Your article</p>' +
    '<h1>' + (source ? articleLink(source) : 'Your article comparison') + '</h1>';
  if (source){
    const metadata = [source.source_country, source.outlet].filter(Boolean).join(' / ');
    html += '<p class="source-meta">' + escapeHtml(metadata) + '</p>';
  }
  html += '</header><div class="report-scope" aria-label="Comparison scope">' +
    '<div><strong>' + comparisons.length + '</strong><span>other articles</span></div>' +
    '<div><strong>' + countries.size + '</strong><span>countries</span></div>' +
    '<div><strong>' + cats.length + '</strong><span>differences</span></div></div>';
  if (data.stop_reason){
    html += '<section class="stop-reason"><h2>Comparison stopped</h2><p>' + textAsHtml(data.stop_reason) + '</p></section>';
  }
  if (data.summary){
    const refs = data.summary_supporting_articles || [];
    html += '<section class="overview" id="overview" aria-labelledby="overviewHeading"><h2 id="overviewHeading">What we found</h2>' +
      sectionViews('overview', 'What we found', summaryAsHtml(data.summary, refs) + reportReferences(refs)) + '</section>';
  }
  if (cats.length){
    html += '<nav class="report-contents" aria-label="Findings in this comparison"><h2>In this comparison</h2><ol>';
    cats.forEach((category, index) => {
      html += '<li><a href="#finding-' + (index + 1) + '"><span class="index">' + String(index + 1).padStart(2, '0') +
        '</span>' + escapeHtml(categoryTitle(category)) + '</a></li>';
    });
    html += '</ol></nav>';
  }
  html += '<section class="findings" aria-labelledby="findingsHeading"><h2 id="findingsHeading">How the articles differ</h2>';
  if (!cats.length){
    html += '<p class="empty">' + (data.stop_reason ? 'There are no results for this comparison.' :
      'We did not find any clear, important differences in how these articles explain the story.') + '</p>';
  }
  cats.forEach((category, index) => {
    const number = index + 1;
    const description = CATEGORY_DESCRIPTIONS[category.key];
    html += '<section class="finding" id="finding-' + number + '" aria-labelledby="findingHeading-' + number + '">' +
      '<div class="finding-heading"><span class="finding-number">' + String(number).padStart(2, '0') + '</span>' +
      '<h3 id="findingHeading-' + number + '">' + escapeHtml(categoryTitle(category)) + '</h3></div>' +
      sectionViews('finding-' + number, categoryTitle(category),
      (description ? '<p class="finding-description">' + escapeHtml(description) + '</p>' : '') +
      '<p class="finding-body">' + findingAsHtml(category.paragraph) + '</p>' +
      reportReferences(category.supporting_articles || [])) + '</section>';
  });
  html += '</section>';
  if (comparisons.length){
    html += '<section class="article-library"><h2>Articles compared</h2>' +
      '<p class="section-note">Other articles about this story, grouped by country. Some helped explain a difference; others did not.</p>';
    const groups = [...groupArticlesByCountry(comparisons)].sort(([a], [b]) => a.localeCompare(b));
    groups.forEach(([country, countryArticles]) => {
      html += '<details class="country"><summary>' + escapeHtml(country) + ' <span>(' + countryArticles.length + ')</span></summary>' +
        reportArticles(countryArticles) + '</details>';
    });
    html += '</section>';
  }
  if (data.structural_note){
    html += '<footer class="report-note">' + textAsHtml(data.structural_note) + '</footer>';
  }
  resultsEl.innerHTML = html + '</article>';
  updateMemeControls();
  updatePerspectiveControls();
  if (data.perspective_map && data.summary) renderPerspectiveMap(data);
  if (data.meme_view && ClearFrameMemes.itemIds(data).length) void renderMemeCards(data);
}

function showSectionMode(id, mode){
  const modes = sectionViewModes(id);
  if (!sectionModes.has(id) || !modes.includes(mode)) return;
  sectionModes.set(id, mode);
  for (const option of modes){
    const selected = option === mode;
    const button = $('#' + id + '-tab-' + option);
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    $('#' + id + '-' + option).hidden = !selected;
  }
  if (mode === 'comic') globalThis.ClearFrameComic?.load($('#' + id + '-comic'));
  updateMemeControls();
  updatePerspectiveControls();
}

function updatePrintAvailability(){
  const eligible = new Set(latestResults ? ClearFrameMemes.itemIds(latestResults) : []);
  const pendingMeme = [...sectionModes].some(([id, mode]) => mode === 'low' && eligible.has(id) && !renderedMemes.has(id));
  const pendingMap = sectionModes.get('overview') === 'middle' && perspectiveState !== 'ready';
  printResultsBtn.disabled = !latestResults || pendingMeme || pendingMap;
}

function updateMemeControls(){
  const available = latestResults && ClearFrameMemes.itemIds(latestResults).length > 0;
  const busy = memeState === 'generating' || memeState === 'loading';
  const hasLowSelection = [...sectionModes.values()].includes('low');
  $("#regenerateMemes").hidden = !hasLowSelection || !latestResults?.meme_view;
  $("#regenerateMemes").disabled = busy;
  const eligible = new Set(latestResults ? ClearFrameMemes.itemIds(latestResults) : []);
  sectionModes.forEach((mode, id) => {
    const ready = renderedMemes.has(id);
    const canGenerate = available && eligible.has(id);
    $('#' + id + '-meme-controls').hidden = ready && !busy && memeState !== 'error';
    $('#' + id + '-generate-memes').hidden = !canGenerate;
    $('#' + id + '-generate-memes').disabled = !canGenerate || busy;
    $('#' + id + '-generate-memes').textContent = memeState === 'error' ? 'Try again' : 'Generate memes';
    $('#' + id + '-meme-privacy').hidden = !canGenerate || busy;
    let message = 'Turn this summary into a meme and one short sentence.';
    if (!canGenerate) message = 'There is no short version available for this section.';
    else if (memeState === 'generating') message = 'Writing and reviewing your memes... You can read the high fidelity version now.';
    else if (memeState === 'loading') message = 'Putting the captions on your memes...';
    else if (memeState === 'error') message = memeError;
    $('#' + id + '-meme-status').textContent = message;
    $('#' + id + '-meme-status').dataset.state = memeState;
  });
  updatePrintAvailability();
}

function updatePerspectiveControls(){
  const busy = perspectiveState === 'generating';
  $('#regeneratePerspectives').hidden = sectionModes.get('overview') !== 'middle' || !latestResults?.perspective_map;
  $('#regeneratePerspectives').disabled = busy;
  if (sectionModes.has('overview')){
    $('#perspectiveControls').hidden = perspectiveState === 'ready';
    $('#generatePerspectives').disabled = busy;
    $('#generatePerspectives').textContent = perspectiveState === 'error' ? 'Try again' : 'Generate map';
    $('#perspectivePrivacy').hidden = busy;
    $('#perspectiveStatus').textContent = busy ? 'Mapping the perspectives... You can read the other versions while this finishes.' :
      perspectiveState === 'error' ? perspectiveError : 'Explore how the articles explain the same story.';
    $('#perspectiveStatus').dataset.state = perspectiveState;
  }
  updatePrintAvailability();
}

function renderPerspectiveMap(data){
  try {
    ClearFramePerspectives.render($('#overview-map'), data.perspective_map);
    perspectiveState = 'ready'; perspectiveError = '';
  } catch (_error){
    perspectiveState = 'error'; perspectiveError = 'This map could not be displayed. Try generating it again. Your other results are still available.';
  }
  updatePerspectiveControls();
}

async function generatePerspectiveMap({ apiKey = keyEl.value.trim(), regenerate = false } = {}){
  const data = latestResults;
  if (!data?.summary || perspectiveState === 'generating') return;
  if (data.perspective_map && !regenerate){ renderPerspectiveMap(data); return; }
  if (!apiKey){
    perspectiveState = 'error'; perspectiveError = 'Enter your OpenAI key on the left, then choose Try again to make a map.';
    updatePerspectiveControls(); keyEl.focus(); return;
  }
  const controller = new AbortController();
  perspectiveController = controller;
  const version = ++perspectiveVersion;
  perspectiveState = 'generating'; perspectiveError = ''; updatePerspectiveControls();
  const results = { summary: data.summary, categories: data.categories, summary_supporting_articles: data.summary_supporting_articles,
    analysis_articles: data.analysis_articles, structural_note: data.structural_note };
  try {
    const response = await fetch('/perspectives', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results, api_key: apiKey }), signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (latestResults !== data || version !== perspectiveVersion) return;
    if (!response.ok){
      perspectiveState = 'error';
      perspectiveError = response.status === 404 ?
        'The app server does not have the map feature loaded. Restart app.py, reload this page, then try again.' :
        payload.error || 'Could not make the map. Try again. Your other results are still available.';
      updatePerspectiveControls(); return;
    }
    data.perspective_map = payload.perspective_map;
    renderPerspectiveMap(data);
  } catch (_error){
    if (controller.signal.aborted || latestResults !== data || version !== perspectiveVersion) return;
    perspectiveState = 'error'; perspectiveError = 'Could not make the map. Check your connection and OpenAI key, then try again. Your other results are still available.';
    updatePerspectiveControls();
  } finally {
    if (perspectiveController === controller) perspectiveController = null;
  }
}

async function renderMemeCards(data){
  const version = ++memeRenderVersion;
  memeState = 'loading'; updateMemeControls();
  try {
    const catalog = await ClearFrameMemes.catalog();
    if (latestResults !== data || version !== memeRenderVersion) return;
    let view;
    try { view = ClearFrameMemes.validate(data.meme_view, data, catalog.templates); }
    catch (error) { delete data.meme_view; throw error; }
    const byId = new Map(catalog.templates.map(template => [template.id, template]));
    const cards = await Promise.all(view.items.map(async item => {
      const image = await ClearFrameMemes.render(item, byId.get(item.template_id));
      return { id: item.id, html: '<figure class="meme-card"><a href="#' + escapeAttribute(item.id) + '" data-high-section="' + escapeAttribute(item.id) +
        '" title="Read the full explanation"><img src="' + image + '" alt="' + escapeAttribute(item.alt_text) +
        '"></a><figcaption>' + escapeHtml(item.sentence) + '</figcaption></figure>' };
    }));
    if (latestResults !== data || version !== memeRenderVersion) return;
    data.meme_view = view;
    cards.forEach(card => {
      renderedMemes.set(card.id, card.html);
      $('#' + card.id + '-meme').innerHTML = card.html;
    });
    memeState = 'ready'; updateMemeControls();
  } catch (error) {
    if (latestResults !== data || version !== memeRenderVersion) return;
    memeState = 'error'; memeError = error.message || 'The memes could not be displayed. Try again.';
    updateMemeControls();
  }
}

async function generateMemes({ apiKey = keyEl.value.trim(), regenerate = false } = {}){
  const data = latestResults;
  if (!data || !ClearFrameMemes.itemIds(data).length || memeState === 'generating' || memeState === 'loading') return;
  if (data.meme_view && !regenerate){ await renderMemeCards(data); return; }
  if (!apiKey){
    memeState = 'error'; memeError = 'Enter your OpenAI key on the left, then choose Try again to make memes.';
    updateMemeControls(); keyEl.focus(); return;
  }
  const controller = new AbortController();
  memeController = controller;
  const version = ++memeRenderVersion;
  memeState = 'generating'; memeError = ''; updateMemeControls();
  // Only the finished summary and supporting references leave the browser.
  const results = { summary: data.summary, categories: data.categories, structural_note: data.structural_note };
  try {
    const response = await fetch('/memes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results, api_key: apiKey }), signal: controller.signal,
    });
    const payload = await response.json();
    if (latestResults !== data || version !== memeRenderVersion) return;
    if (!response.ok) throw new Error(payload.error || 'Could not make memes. Try again.');
    data.meme_view = payload.meme_view;
    await renderMemeCards(data);
  } catch (error) {
    if (controller.signal.aborted || latestResults !== data || version !== memeRenderVersion) return;
    memeState = 'error'; memeError = 'Could not make memes. Check your connection and OpenAI key, then try again. Your full results are still available.';
    updateMemeControls();
  } finally {
    if (memeController === controller) memeController = null;
  }
}

$("#regenerateMemes").onclick = () => { void generateMemes({ regenerate: true }); };
$('#regeneratePerspectives').onclick = () => { void generatePerspectiveMap({ regenerate: true }); };
resultsEl.addEventListener('click', event => {
  const tab = event.target.closest('[data-section-mode]');
  if (tab){ showSectionMode(tab.dataset.section, tab.dataset.sectionMode); return; }
  const link = event.target.closest('[data-high-section]');
  if (link){ event.preventDefault(); showSectionMode(link.dataset.highSection, 'high'); return; }
  if (event.target.closest('[data-generate-memes]')) void generateMemes({ regenerate: true });
  if (event.target.closest('[data-generate-perspectives]')) void generatePerspectiveMap({ regenerate: true });
});
resultsEl.addEventListener('keydown', event => {
  const tab = event.target.closest('[data-section-mode]');
  if (!tab) return;
  let mode;
  const modes = sectionViewModes(tab.dataset.section);
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft'){
    const step = event.key === 'ArrowRight' ? 1 : -1;
    mode = modes[(modes.indexOf(tab.dataset.sectionMode) + step + modes.length) % modes.length];
  }
  else if (event.key === 'Home') mode = 'high';
  else if (event.key === 'End') mode = 'low';
  else return;
  event.preventDefault(); showSectionMode(tab.dataset.section, mode);
  $('#' + tab.dataset.section + '-tab-' + mode).focus();
});
saveResultsBtn.onclick = () => {
  if (!latestResults) return;
  const { llm_analysis, ...results } = latestResults;
  const url = URL.createObjectURL(new Blob([JSON.stringify(results, null, 2) + '\n'], {type:'application/json'}));
  const link = document.createElement('a');
  link.href = url; link.download = 'results.json'; document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

function parseResultsFile(text){
  const invalid = () => { throw new Error('This file does not contain readable ClearFrame results. Choose results.json or a saved ClearFrame run.'); };
  const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  const readText = value => {
    if (value == null) return '';
    if (typeof value !== 'string') invalid();
    return value;
  };
  const readList = value => {
    if (value == null) return [];
    if (!Array.isArray(value)) invalid();
    return value;
  };
  const readArticle = article => {
    if (!isObject(article)) invalid();
    const citation = article.citation_id;
    if (citation != null && typeof citation !== 'string' && typeof citation !== 'number') invalid();
    return {
      title: readText(article.title), url: readText(article.url),
      outlet: readText(article.outlet), source_country: readText(article.source_country),
      role: readText(article.role), citation_id: citation ?? '',
    };
  };
  let data;
  try { data = JSON.parse(text.replace(/^\uFEFF/, '')); }
  catch (_err) { throw new Error('This file could not be read. Choose a valid .json results file.'); }
  if (!isObject(data)) invalid();
  const rawRun = Object.hasOwn(data, 'synthesis');
  const content = rawRun ? data.synthesis : data;
  if (!isObject(content) || !['summary', 'categories', 'stop_reason', 'analysis_articles'].some(key => Object.hasOwn(content, key))) invalid();
  const categoryData = content.categories ?? [];
  let entries;
  if (Array.isArray(categoryData)) entries = categoryData.map(category => ['', category]);
  else if (isObject(categoryData)) entries = Object.entries(categoryData);
  else invalid();
  const categories = entries.map(([key, category]) => {
    if (!isObject(category) || typeof category.paragraph !== 'string') invalid();
    return {
      key: readText(category.key ?? key), label: readText(category.label),
      paragraph: category.paragraph,
      supporting_articles: readList(category.supporting_articles).map(readArticle),
    };
  });
  let articles = readList(content.analysis_articles).map(readArticle);
  if (rawRun){
    const plan = data.plan ?? {};
    if (!isObject(plan)) invalid();
    articles = [];
    const sourceUrl = readText(data.source_url);
    if (sourceUrl){
      articles.push(readArticle({
        title: readText(data.source_title) || 'Your article', url: sourceUrl,
        source_country: readText(plan.original_source_country), role: 'source',
      }));
    }
    const seen = new Set(articles.map(article => article.url));
    readList(data.pair_analyses).forEach(pair => {
      if (!isObject(pair)) invalid();
      if (pair.article_reference == null) return;
      const article = readArticle(pair.article_reference);
      const identity = article.url || [article.title, article.outlet].filter(Boolean).join('|');
      if (!identity || seen.has(identity)) return;
      seen.add(identity);
      articles.push({ ...article, role: 'comparison' });
    });
  }
  const normalized = {
    summary: readText(content.summary), structural_note: readText(content.structural_note),
    stop_reason: readText(rawRun ? data.stop_reason : content.stop_reason), categories,
    summary_supporting_articles: readList(content.summary_supporting_articles).map(readArticle),
    analysis_articles: articles,
  };
  // Preserve optional meme data; the catalog validator checks it before rendering.
  if (Object.hasOwn(data, 'meme_view')) normalized.meme_view = data.meme_view;
  if (Object.hasOwn(data, 'perspective_map')) normalized.perspective_map = data.perspective_map;
  return normalized;
}

async function importResultsFile(file){
  if (!file) return;
  importStatus.hidden = false;
  importStatus.dataset.state = '';
  if (running){
    importStatus.textContent = 'Wait for the current comparison to finish before opening a file.';
    resultsFileInput.value = '';
    return;
  }
  const generation = ++runGeneration;
  importStatus.textContent = 'Opening ' + file.name + '...';
  try {
    if (!/\.json$/i.test(file.name)) throw new Error('Choose a .json file, such as results.json or a saved ClearFrame run.');
    if (file.size > 20 * 1024 * 1024) throw new Error('Choose a results file smaller than 20 MB.');
    const text = await file.text();
    if (generation !== runGeneration || running) return;
    const data = parseResultsFile(text);
    renderResults(data);
    showTab('results');
    importStatus.textContent = 'Opened ' + file.name + '. These results are only loaded in this page.';
  } catch (err) {
    if (generation !== runGeneration || running) return;
    importStatus.dataset.state = 'error';
    importStatus.textContent = err.message || 'This file could not be opened. Try another saved results file.';
  } finally {
    if (generation === runGeneration) resultsFileInput.value = '';
  }
}

resultsFileInput.addEventListener('change', () => importResultsFile(resultsFileInput.files[0]));

function renderAnalysis(data){
  const analysis = data.llm_analysis || {};
  const pairs = analysis.pair_extractions || [];
  $("#analysisCount").textContent = pairs.length ? "(" + pairs.length + ")" : "";

  let html = '<div class="view-heading"><p class="eyebrow">Behind the comparison</p><h1>A closer look</h1>' +
    '<p>The notes behind your results.</p></div>';
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
function showRunError(message){
  setStatus("err", "Comparison failed. See Progress for details.");
  resultsEl.innerHTML = '<div class="view-heading"><p class="eyebrow">Comparison interrupted</p>' +
    '<h1>We could not complete this comparison.</h1><p>' + escapeHtml(message) + '</p>' +
    '<p>Check Progress for details, or try another article.</p></div>';
  analysisEl.innerHTML = '<p class="empty">There are no notes for this comparison.</p>';
}

function handleMsg(msg, apiKey){
  if (msg.type === "line") appendLine(msg.text);
  else if (msg.type === "result"){
    renderResults(msg.data); renderAnalysis(msg.data); showTab("results");
    setStatus("ok", "Done. Your results are ready.");
    if (apiKey) void generateMemes({ apiKey });
    if (apiKey) void generatePerspectiveMap({ apiKey });
  }
  else if (msg.type === "error"){ appendLine("ERROR: " + msg.text); showRunError(msg.text); }
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
      if (data){
        const message = JSON.parse(data);
        handleMsg(message, apiKey);
        // The server may keep the HTTP connection alive after its final event.
        if (message.type === 'done'){
          await reader.cancel();
          reader.releaseLock();
          return;
        }
      }
    }
  }
}

$("#form").addEventListener("submit", async e => {
  e.preventDefault();
  if (running) return;
  const url = $("#url").value.trim();
  const apiKey = keyEl.value.trim();
  if (!url) return;
  if (!apiKey){ setStatus("err", "Enter your OpenAI key to compare articles."); keyEl.focus(); return; }

  // A new run takes precedence over a file still being read.
  runGeneration += 1;
  if (perspectiveController) perspectiveController.abort();
  perspectiveController = null; perspectiveVersion += 1;
  perspectiveState = 'idle'; perspectiveError = '';
  globalThis.ClearFramePerspectives?.clear();
  if (memeController) memeController.abort();
  memeRenderVersion += 1;
  memeState = 'idle'; memeError = '';
  sectionModes.clear(); renderedMemes.clear();
  importStatus.hidden = true;
  resultsFileInput.value = '';
  try {
    if (rememberEl.checked) localStorage.setItem(KEY_STORE, apiKey);
    else localStorage.removeItem(KEY_STORE);
  } catch (_err) { /* The comparison can run even when browser storage is blocked. */ }

  consoleEl.innerHTML = ""; resultsEl.innerHTML = ""; analysisEl.innerHTML = ""; rawLog = "";
  latestResults = null;
  saveResultsBtn.disabled = true;
  $("#regenerateMemes").hidden = true;
  $('#regeneratePerspectives').hidden = true;
  copyResultsBtn.disabled = true;
  printResultsBtn.disabled = true;
  resultsEl.innerHTML = '<div class="view-heading"><p class="eyebrow">Comparison in progress</p><h1>Looking at other articles.</h1>' +
    '<p>Your results will appear here when the comparison is complete. Follow along in Progress.</p></div>';
  analysisEl.innerHTML = '<p class="empty">Notes will appear when this comparison is complete.</p>';
  $("#resCount").textContent = "";
  $("#analysisCount").textContent = "";
  showTab("console");
  running = true; goBtn.disabled = true;
  resultsFileInput.disabled = true;
  setStatus("run", "Comparing articles. Follow along in Progress.");

  try {
    await streamRun(url, apiKey);
  } catch (err) {
    showRunError("The connection was interrupted. Check that the server is still running and try again.");
  } finally {
    running = false; goBtn.disabled = false;
    resultsFileInput.disabled = false;
  }
});

