const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function createPage() {
  const nodes = new Map();
  const node = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: '', textContent: '', innerHTML: '', disabled: false, hidden: false,
      style: {}, dataset: {}, classList: { toggle() {} },
      addEventListener() {}, setAttribute() {}, focus() {},
    });
    return nodes.get(selector);
  };
  const context = vm.createContext({
    URL,
    document: { querySelector: node },
    localStorage: { getItem() { throw new Error('Storage unavailable'); } },
    fetch() { throw new Error('Opening results must not make network requests'); },
  });
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
