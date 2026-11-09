const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function createPage(overrides = {}) {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: '', textContent: '', innerHTML: '', className: '', disabled: false, hidden: false,
      style: {}, dataset: {}, classList: { toggle() {} },
      addEventListener() {}, setAttribute() {}, focus() {},
    });
    return nodes.get(selector);
  };
  const context = vm.createContext({
    URL, AbortController, TextDecoder,
    document: { querySelector: node },
    localStorage: { getItem() { throw new Error('Storage unavailable'); } },
    fetch() { throw new Error('Opening results must not make network requests'); },
    ...overrides,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/memes.js'), 'utf8'), context);
  vm.runInContext(source, context);
  return { context, node, evaluate: code => vm.runInContext(code, context) };
}

const snapshot = {
  summary: 'A comparison summary.',
  categories: [{
    key: 'agency_attribution', paragraph: 'First sentence. More detail.',
    supporting_articles: [{ title: 'Supporting article', url: 'https://example.org/story' }],
  }],
  analysis_articles: [{ role: 'source', title: 'Source article', url: 'https://source.example/story' }],
};

const file = (data, name = 'results.json') => ({
  name, size: 100, text: async () => typeof data === 'string' ? data : JSON.stringify(data),
});

test('imports a results snapshot without storage or network access, changing only Results', async () => {
  const { context, node } = createPage();
  node('#console').textContent = 'Existing progress';
  node('#analysis').innerHTML = 'Existing details';
  node('#analysisCount').textContent = '3';
  node('#url').value = 'https://unchanged.example';
  node('#apiKey').value = 'unchanged-key';
  const withDetails = { ...snapshot, llm_analysis: { source_extraction: { secret: 'Not imported' } } };
  await context.importResultsFile(file(withDetails));
  assert.match(node('#results').innerHTML, /A comparison summary/);
  assert.equal(node('#copyResults').disabled, false);
  assert.equal(node('#printResults').disabled, false);
  assert.equal(node('#console').textContent, 'Existing progress');
  assert.equal(node('#analysis').innerHTML, 'Existing details');
  assert.equal(node('#analysisCount').textContent, '3');
  assert.equal(node('#url').value, 'https://unchanged.example');
  assert.equal(node('#apiKey').value, 'unchanged-key');
  assert.equal(node('#importStatus').dataset.state, '');
  assert.match(node('#importStatus').textContent, /Opened results.json/);
});

test('adapts full saved runs and deduplicates comparison articles', () => {
  const { context } = createPage();
  const reference = { title: 'Comparison', url: 'https://example.org/story', source_country: 'Oman' };
  const run = {
    source_url: 'https://source.example/story', source_title: 'Original headline',
    plan: { original_source_country: 'United States' },
    synthesis: {
      summary: 'Run summary', structural_note: 'A note.',
      categories: { agency_attribution: snapshot.categories[0] },
    },
    pair_analyses: [{ article_reference: reference }, { article_reference: reference }],
  };
  const result = context.parseResultsFile(JSON.stringify(run));
  assert.equal(result.summary, 'Run summary');
  assert.equal(result.categories[0].key, 'agency_attribution');
  assert.equal(result.analysis_articles.length, 2);
  assert.equal(result.analysis_articles[0].role, 'source');
  assert.equal(result.analysis_articles[0].source_country, 'United States');
  assert.equal(result.analysis_articles[1].role, 'comparison');
});

test('reads UTF-8 files with a byte-order mark', () => {
  const { context } = createPage();
  const multilingual = { ...snapshot, summary: 'News: \u0623\u062e\u0628\u0627\u0631, \u65b0\u95fb' };
  assert.equal(context.parseResultsFile('\uFEFF' + JSON.stringify(multilingual)).summary, multilingual.summary);
});

test('invalid and unrelated files show an error and preserve existing results', async () => {
  const { context, node } = createPage();
  await context.importResultsFile(file(snapshot));
  const previous = node('#results').innerHTML;
  const badFiles = [
    file('{'), file(null), file([]), file({ unrelated: true }),
    file({ summary: [] }), file({ categories: 'wrong' }),
    file({ categories: [null] }), file({ categories: [{}] }),
    file({ analysis_articles: [null] }),
    file({ summary_supporting_articles: 'wrong', summary: 'Test' }),
    file({ categories: [{ paragraph: 'Test', supporting_articles: [false] }] }),
    file({ synthesis: null }), file(snapshot, 'report.html'),
    { ...file(snapshot), size: 21 * 1024 * 1024 },
  ];
  for (const badFile of badFiles) {
    await context.importResultsFile(badFile);
    assert.equal(node('#importStatus').dataset.state, 'error');
    assert.equal(node('#results').innerHTML, previous);
  }
});

test('uploaded markup is escaped and unsafe links stay inactive', async () => {
  const { context, node } = createPage();
  await context.importResultsFile(file({
    summary: '<script>alert(1)</script>',
    categories: [{ paragraph: '<img src=x onerror=alert(1)>', supporting_articles: [
      { title: '<svg onload=alert(1)>', url: 'javascript:alert(1)' },
    ] }],
  }, '<img>.json'));
  assert.doesNotMatch(node('#results').innerHTML, /<script|<img|<svg|href="javascript:/);
  assert.match(node('#results').innerHTML, /&lt;script&gt;/);
  assert.match(node('#importStatus').textContent, /<img>\.json/);
});

test('the most recently selected file wins if reads finish out of order', async () => {
  const { context, node } = createPage();
  let finishReading;
  const slowFile = { name: 'old.json', size: 100, text: () => new Promise(resolve => { finishReading = resolve; }) };
  const first = context.importResultsFile(slowFile);
  await context.importResultsFile(file({ ...snapshot, summary: 'New results' }, 'new.json'));
  finishReading(JSON.stringify(snapshot));
  await first;
  assert.match(node('#results').innerHTML, /New results/);
  assert.match(node('#importStatus').textContent, /Opened new.json/);
});

test('a file cannot overwrite an active or newly started comparison', async () => {
  const { context, node, evaluate } = createPage();
  evaluate('running = true');
  await context.importResultsFile(file(snapshot));
  assert.equal(node('#results').innerHTML, '');
  assert.match(node('#importStatus').textContent, /Wait for the current comparison/);
  evaluate('running = false');
  let finishReading;
  const pending = context.importResultsFile({ name: 'old.json', size: 100, text: () => new Promise(resolve => { finishReading = resolve; }) });
  evaluate('runGeneration += 1; running = true');
  node('#results').innerHTML = 'New comparison in progress';
  finishReading(JSON.stringify(snapshot));
  await pending;
  assert.equal(node('#results').innerHTML, 'New comparison in progress');
});

const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '../static/meme-templates/catalog.json'), 'utf8'));
const memeView = () => ({ version: 1, items: ['overview', 'finding-1'].map(id => ({
  id, template_id: 'drake', captions: { rejected: 'The missing context', preferred: 'The familiar explanation' },
  sentence: 'The article gives one explanation more attention.', alt_text: 'Drake prefers the familiar explanation.',
})) });

function mockRenderer(context) {
  context.ClearFrameMemes.catalog = async () => catalog;
  context.ClearFrameMemes.render = async () => 'data:image/png;base64,test';
}

test('template validation rejects arbitrary images, mismatched cards, and overflowing captions', () => {
  const { context } = createPage();
  assert.equal(context.ClearFrameMemes.validate(memeView(), snapshot, catalog.templates).items.length, 2);
  const invalid = [
    { ...memeView(), version: 3 }, { ...memeView(), items: [] },
    { ...memeView(), items: [memeView().items[0], memeView().items[0]] },
  ];
  const unknown = memeView(); unknown.items[0].template_id = 'https://untrusted.example/image.png'; invalid.push(unknown);
  const long = memeView(); long.items[0].captions.rejected = 'a '.repeat(20); invalid.push(long);
  const wrong = memeView(); wrong.items[0].captions = { wrong: 'slot' }; invalid.push(wrong);
  for (const view of invalid) assert.throws(() => context.ClearFrameMemes.validate(view, snapshot, catalog.templates));
});

test('saved meme cards reopen without an LLM call and leave the full explanation available', async () => {
  const { context, node, evaluate } = createPage();
  mockRenderer(context);
  await context.importResultsFile(file({ ...snapshot, meme_view: memeView() }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(evaluate('memeState'), 'ready');
  assert.match(node('#overview-meme').innerHTML, /data:image\/png/);
  assert.match(node('#finding-1-meme').innerHTML, /The article gives one explanation/);
  assert.equal(evaluate('sectionModes.get("overview")'), 'high');
  context.showSectionMode('overview', 'low');
  assert.equal(node('#overview-high').hidden, true);
  assert.equal(node('#overview-low').hidden, false);
  assert.equal(evaluate('sectionModes.get("finding-1")'), 'high');
  assert.equal(node('#printResults').disabled, false);
  context.showSectionMode('overview', 'high');
  assert.match(node('#results').innerHTML, /A comparison summary/);
  assert.equal(evaluate('JSON.stringify(latestResults.meme_view.items).includes("data:image")'), false);
});

test('new cards have short sentences and expanded dialogue while older saved captions still open', () => {
  const { context } = createPage();
  const validate = view => context.ClearFrameMemes.validate(view, snapshot, catalog.templates);
  const legacy = memeView();
  legacy.items[0].template_id = 'spiderman';
  legacy.items[0].captions = { left: 'Your server did it.', right: 'Your update did it.' };
  legacy.items[0].sentence = 'word '.repeat(30).trim();
  assert.equal(validate(legacy).version, 1);
  const modern = JSON.parse(JSON.stringify(legacy)); modern.version = 2;
  modern.items[0].captions.left_actor = 'App company'; modern.items[0].captions.right_actor = 'City hall';
  modern.items[0].sentence = 'The two sides blame each other.';
  assert.equal(validate(modern).version, 2);
  modern.items[0].sentence = 'word '.repeat(21).trim();
  assert.throws(() => validate(modern));
});

test('regeneration requests fresh captions instead of redisplaying the saved set', async () => {
  let calls = 0;
  const { context, evaluate } = createPage({ fetch: async () => {
    calls++; return { ok: true, json: async () => ({ meme_view: { ...memeView(), version: 2 } }) };
  } });
  mockRenderer(context);
  await context.importResultsFile(file({ ...snapshot, meme_view: memeView() }));
  await new Promise(resolve => setImmediate(resolve));
  await context.generateMemes({ apiKey: 'key', regenerate: true });
  assert.equal(calls, 1);
  assert.equal(evaluate('latestResults.meme_view.version'), 2);
});

test('invalid saved memes preserve the full results and allow a fresh generation', async () => {
  const { context, node, evaluate } = createPage();
  mockRenderer(context);
  await context.importResultsFile(file({ ...snapshot, meme_view: { version: 1, items: [] } }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(evaluate('memeState'), 'error');
  assert.match(node('#results').innerHTML, /A comparison summary/);
  assert.equal(evaluate('latestResults.meme_view'), undefined);
  assert.equal(node('#overview-generate-memes').disabled, false);
});

test('generation sends analysis text only and independent section tabs make no extra calls', async () => {
  const calls = [];
  const { context, node } = createPage({ fetch: async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return { ok: true, json: async () => ({ meme_view: memeView() }) };
  } });
  mockRenderer(context);
  await context.importResultsFile(file({ ...snapshot, llm_analysis: { private: 'raw details' } }));
  await context.generateMemes({ apiKey: 'visitor-key' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/memes');
  assert.equal(calls[0].body.api_key, 'visitor-key');
  assert.equal(calls[0].body.results.summary, snapshot.summary);
  assert.equal(calls[0].body.results.llm_analysis, undefined);
  assert.equal(calls[0].body.results.analysis_articles, undefined);
  assert.doesNotMatch(JSON.stringify(calls[0].body), /data:image|\.jpg|raw details/);
  context.showSectionMode('overview', 'low'); context.showSectionMode('finding-1', 'low'); context.showSectionMode('overview', 'high');
  assert.equal(node('#overview-high').hidden, false);
  assert.equal(node('#finding-1-low').hidden, false);
  await context.generateMemes({ apiKey: 'visitor-key' });
  assert.equal(calls.length, 1);
  assert.equal(node('#overview-generate-memes').disabled, false);
});

test('generation failures and missing keys keep full results readable', async () => {
  let calls = 0;
  const { context, node, evaluate } = createPage({ fetch: async () => {
    calls++; return { ok: false, json: async () => ({ error: 'Unavailable' }) };
  } });
  await context.importResultsFile(file(snapshot));
  await context.generateMemes();
  assert.equal(calls, 0);
  assert.match(node('#overview-meme-status').textContent, /Enter your OpenAI key/);
  await context.generateMemes({ apiKey: 'key' });
  assert.equal(calls, 1);
  assert.equal(evaluate('memeState'), 'error');
  assert.match(node('#results').innerHTML, /A comparison summary/);
});

test('a late generation cannot overwrite a newly uploaded comparison', async () => {
  let finish;
  const { context, node, evaluate } = createPage({ fetch: () => new Promise(resolve => { finish = resolve; }) });
  mockRenderer(context);
  await context.importResultsFile(file(snapshot));
  const pending = context.generateMemes({ apiKey: 'key' });
  await context.importResultsFile(file({ ...snapshot, summary: 'New comparison' }, 'new.json'));
  finish({ ok: true, json: async () => ({ meme_view: memeView() }) });
  await pending;
  assert.match(node('#results').innerHTML, /New comparison/);
  assert.equal(evaluate('latestResults.meme_view'), undefined);
  assert.equal(evaluate('renderedMemes.size'), 0);
});

test('section choices survive asynchronous meme loading and navigation between main views', async () => {
  let finish;
  const { context, node, evaluate } = createPage({ fetch: () => new Promise(resolve => { finish = resolve; }) });
  mockRenderer(context);
  await context.importResultsFile(file(snapshot));
  context.showSectionMode('overview', 'low');
  const pending = context.generateMemes({ apiKey: 'key' });
  context.showSectionMode('finding-1', 'low');
  context.showSectionMode('overview', 'high');
  context.showTab('console');
  finish({ ok: true, json: async () => ({ meme_view: memeView() }) });
  await pending;
  context.showTab('results');
  assert.equal(evaluate('sectionModes.get("overview")'), 'high');
  assert.equal(evaluate('sectionModes.get("finding-1")'), 'low');
  assert.equal(node('#overview-high').hidden, false);
  assert.equal(node('#finding-1-low').hidden, false);
  assert.equal(node('#finding-1-meme-controls').hidden, true);
  assert.equal(node('#printResults').disabled, false);
});

test('a completed SSE run releases its reader without waiting for the connection to close', async () => {
  let cancelled = false, released = false, readCount = 0;
  const chunk = new TextEncoder().encode('data: {"type":"done"}\n\n');
  const { context } = createPage({ fetch: async () => ({ ok: true, body: { getReader: () => ({
    read: async () => {
      readCount++;
      if (readCount > 1) throw new Error('The stream should finish at its done event');
      return { value: chunk, done: false };
    },
    cancel: async () => { cancelled = true; }, releaseLock: () => { released = true; },
  }) } }) });
  await context.streamRun('https://source.example/story', 'key');
  assert.equal(readCount, 1);
  assert.equal(cancelled, true);
  assert.equal(released, true);
});
