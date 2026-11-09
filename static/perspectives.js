// Display model-written answers and comparisons using the supplied article registry.
globalThis.ClearFramePerspectives = (() => {
  let dispose = () => {};
  function element(tag, className, text){
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }
  function render(container, map){
    dispose(); container.replaceChildren();
    const perspectives = map.perspectives || [], connections = map.connections || [];
    const references = new Map((map.article_references || []).map(article => [article.id, article]));
    const sourcesFor = ids => (ids || []).map(id => references.get(id)).filter(Boolean);
    const labelFor = article => {
      if (article.outlet) return article.outlet;
      try { return new URL(article.url).hostname.replace(/^www\./, ''); }
      catch (_error) { return article.title || 'Article'; }
    };
    function appendSources(target, ids){
      const sources = sourcesFor(ids);
      if (!sources.length) return;
      target.append(element('h4', '', 'Supporting articles'));
      const list = element('ul', 'article-list');
      sources.forEach(article => {
        const item = element('li'), url = safeHttpUrl(article.url);
        const title = element(url ? 'a' : 'span', '', article.title || labelFor(article));
        if (url) { title.href = url; title.target = '_blank'; title.rel = 'noopener noreferrer'; }
        item.append(title);
        const metadata = [article.outlet, article.source_country].filter(Boolean).join(' / ');
        if (metadata) item.append(element('span', 'article-meta', metadata));
        list.append(item);
      });
      target.append(list);
    }
    const wrapper = element('div', 'perspective-map');
    const world = element('section');
    wrapper.append(world); container.append(wrapper);
    const worldView = globalThis.ClearFrameWorldMap?.mount(world, { perspectives, connections, question: map.question, appendSources });
    dispose = () => { worldView?.destroy(); container.replaceChildren(); };
  }
  return { render, clear: () => dispose() };
})();
