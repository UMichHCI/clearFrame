// Local geography and existing perspective answers; no map service or model requests.
globalThis.ClearFrameWorldMap = (() => {
  let atlasPromise;
  const svgNS = 'http://www.w3.org/2000/svg';
  const normalize = name => String(name || '').normalize('NFKD').replace(/\p{Diacritic}/gu, '')
    .toLowerCase().replace(/\bthe\b/g, '').replace(/&/g, 'and').replace(/[^a-z0-9]/g, '');
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  function node(tag, className, text){
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text != null) result.textContent = text;
    return result;
  }
  function svgNode(tag, attributes = {}){
    const result = document.createElementNS(svgNS, tag);
    Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
    return result;
  }
  function loadAtlas(){
    if (!atlasPromise) atlasPromise = fetch('/static/geography/world-map.json').then(response => {
      if (!response.ok) throw new Error('Geography unavailable');
      return response.json();
    }).catch(error => { atlasPromise = null; throw error; });
    return atlasPromise;
  }

  function mount(container, { perspectives, connections = [], question, appendSources }){
    let active = true, selected = null, hovered = null, atlas = null, frame = 0, drag = null;
    let selectedConnection = null, hoveredConnection = null, hoverPoint = null;
    const edges = [], comparisonChoices = [], edgePoints = new Map();
    let view = { x: 0, y: 0, width: 1000, height: 430 }, zoom = 1;
    const markers = [], choices = [], locations = [], paths = new Map(), screenPoints = new Map();
    const events = new AbortController();
    const listen = (target, type, handler) => target.addEventListener(type, handler, { signal: events.signal });
    container.className = 'perspective-world';
    container.setAttribute('aria-labelledby', 'perspective-world-heading');
    const heading = node('h3', '', 'Answers around the world'); heading.id = 'perspective-world-heading';
    const instructions = node('p', 'world-instructions', 'Hover or focus on a country for its answer, or a connecting line to compare two countries. Click or tap to keep the explanation and sources open. Short gray lines locate offset markers. Drag to pan, or use the zoom buttons.');
    const sharedQuestion = node('p', 'world-shared-question', question);
    const controls = node('div', 'world-controls'); controls.setAttribute('aria-label', 'World map controls');
    function control(label, text, handler){
      const button = node('button', '', text); button.type = 'button'; button.setAttribute('aria-label', label);
      listen(button, 'click', handler); controls.append(button); return button;
    }
    const zoomIn = control('Zoom in on world map', '+', () => changeZoom(zoom * 1.6));
    const zoomOut = control('Zoom out on world map', '−', () => changeZoom(zoom / 1.6));
    control('Show the whole world', 'World', () => changeZoom(1));
    control('Fit all countries with answers', 'Fit countries', fitCountries);
    const viewport = node('div', 'world-viewport');
    const svg = svgNode('svg', { viewBox: '0 0 1000 430', preserveAspectRatio: 'xMidYMid meet', role: 'group', 'aria-label': 'Country comparisons on the world map' });
    const land = svgNode('g', { class: 'world-land' }), leaders = svgNode('g', { class: 'world-leaders' });
    land.setAttribute('aria-hidden', 'true'); leaders.setAttribute('aria-hidden', 'true');
    const routes = svgNode('g', { class: 'world-connections' });
    svg.append(land, routes, leaders); viewport.append(svg);
    const tooltip = node('div', 'world-tooltip'); tooltip.id = 'perspective-world-tooltip'; tooltip.hidden = true; tooltip.setAttribute('role', 'tooltip');
    const lineLegend = node('div', 'world-line-legend'); lineLegend.setAttribute('aria-label', 'Comparison line meanings');
    lineLegend.append(node('span', 'world-line-shared', 'Similar answers'), node('span', 'world-line-contrast', 'Different answers'));
    const status = node('p', 'world-status', 'Loading world map…'); status.setAttribute('role', 'status');
    const countryList = node('div', 'world-country-list'); countryList.setAttribute('role', 'group'); countryList.setAttribute('aria-label', 'Countries with answers');
    const detail = node('section', 'world-detail'); detail.id = 'perspective-world-detail'; detail.hidden = true; detail.setAttribute('aria-live', 'polite');
    const credit = node('p', 'world-credit');
    const creditLink = node('a', '', 'Natural Earth'); creditLink.href = 'https://www.naturalearthdata.com/'; creditLink.target = '_blank'; creditLink.rel = 'noopener noreferrer';
    credit.append(document.createTextNode('Map: '), creditLink);
    const comparisonList = node('details', 'world-comparison-list');
    comparisonList.append(node('summary', '', 'Browse country comparisons'));
    container.append(heading, sharedQuestion, instructions, lineLegend, controls, viewport, tooltip, status, countryList, comparisonList, detail, credit);

    function country(index){ return perspectives[index].country || perspectives[index].label; }
    function hue(index){ return String((index * 137.508 + 24) % 360); }
    function choose(index){ select(selected === index ? null : index); }
    function dismissTouchPreview(event){
      if (event.pointerType === 'touch') { hovered = null; hoveredConnection = null; hoverPoint = null; updateTooltip(); updateHighlights(); }
    }
    function kind(connection){ return connection.kind === 'shared' ? 'Similar answers' : connection.kind === 'contrast' ? 'Different answers' : 'Comparison'; }
    function pair(edge){ return country(edge.from) + ' / ' + country(edge.to); }
    perspectives.forEach((perspective, index) => {
      const button = node('button', 'world-country-choice', country(index)); button.type = 'button';
      button.style.setProperty('--perspective-hue', hue(index)); button.setAttribute('aria-pressed', 'false'); button.setAttribute('aria-controls', detail.id);
      listen(button, 'click', event => { revealLocation(index); choose(index); dismissTouchPreview(event); });
      listen(button, 'focus', () => preview(index)); listen(button, 'blur', () => hidePreview(index));
      countryList.append(button); choices.push(button);
    });
    connections.forEach(connection => {
      const from = perspectives.findIndex(p => p.id === connection.from), to = perspectives.findIndex(p => p.id === connection.to);
      if (from < 0 || to < 0) return;
      const index = edges.length;
      const group = svgNode('g', { class: 'world-connection ' + (connection.kind === 'shared' ? 'is-shared' : 'is-contrast') });
      const path = svgNode('path', { class: 'world-connection-path', 'aria-hidden': 'true' });
      const hit = svgNode('path', { class: 'world-connection-hit', role: 'button', tabindex: '-1', 'data-world-connection': index,
        'aria-controls': detail.id, 'aria-describedby': tooltip.id, 'aria-pressed': 'false' });
      const edge = { connection, from, to, group, path, hit }; edges.push(edge);
      hit.setAttribute('aria-label', pair(edge) + ': ' + kind(connection) + '. ' + connection.label);
      group.append(path, hit); routes.append(group);
      listen(hit, 'pointerenter', event => { if (event.pointerType !== 'touch') previewConnection(index, event); });
      listen(hit, 'pointerleave', () => { if (document.activeElement !== hit) hideConnectionPreview(index); });
      listen(hit, 'focus', () => previewConnection(index)); listen(hit, 'blur', () => hideConnectionPreview(index));
      listen(hit, 'click', event => { chooseConnection(index); dismissTouchPreview(event); });
      listen(hit, 'keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseConnection(index); }
      });
      const button = node('button', 'world-comparison-choice', pair(edge) + ' — ' + kind(connection)); button.type = 'button';
      button.setAttribute('aria-controls', detail.id); button.setAttribute('aria-pressed', 'false');
      listen(button, 'click', event => { chooseConnection(index); dismissTouchPreview(event); }); listen(button, 'focus', () => previewConnection(index));
      listen(button, 'blur', () => hideConnectionPreview(index)); comparisonList.append(button); comparisonChoices.push(button);
    });
    if (!edges.length){
      comparisonList.hidden = true; lineLegend.hidden = true;
      container.insertBefore(node('p', 'world-status', 'No direct comparisons were identified between these answers.'), credit);
    }
    if (!perspectives.length) status.textContent = 'There are no country answers to place on the map.';

    function metrics(){
      const width = viewport.clientWidth, height = viewport.clientHeight;
      const scale = Math.min(width / view.width, height / view.height);
      return { width, height, scale, left: (width - view.width * scale) / 2, top: (height - view.height * scale) / 2 };
    }
    function constrain(){
      view.width = 1000 / zoom; view.height = 430 / zoom;
      view.x = clamp(view.x, 0, 1000 - view.width); view.y = clamp(view.y, 0, 430 - view.height);
    }
    function changeZoom(next, center){
      const x = center?.x ?? view.x + view.width / 2, y = center?.y ?? view.y + view.height / 2;
      zoom = clamp(next, 1, 8); view.width = 1000 / zoom; view.height = 430 / zoom;
      view.x = x - view.width / 2; view.y = y - view.height / 2; constrain(); schedule();
    }
    function fitCountries(){
      const points = locations.filter(Boolean).map(location => location.anchor);
      if (!points.length) return;
      const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      changeZoom(Math.min(1000 / Math.max(80, maxX - minX + 110), 430 / Math.max(50, maxY - minY + 70)), { x: (minX + maxX) / 2, y: (minY + maxY) / 2 });
    }
    function revealLocation(index){
      const point = locations[index]?.anchor;
      if (point && (point[0] < view.x || point[0] > view.x + view.width || point[1] < view.y || point[1] > view.y + view.height))
        changeZoom(zoom, { x: point[0], y: point[1] });
    }
    function preview(index){ hovered = index; hoveredConnection = null; hoverPoint = null; updateTooltip(); updateHighlights(); }
    function hidePreview(index){ if (hovered === index) { hovered = null; updateTooltip(); updateHighlights(); } }
    function previewConnection(index, event){
      hovered = null; hoveredConnection = index;
      const box = viewport.getBoundingClientRect();
      hoverPoint = event ? { x: event.clientX - box.left, y: event.clientY - box.top } : null;
      updateTooltip(); updateHighlights();
    }
    function hideConnectionPreview(index){
      if (hoveredConnection === index) { hoveredConnection = null; hoverPoint = null; updateTooltip(); updateHighlights(); }
    }
    function updateTooltip(){
      if ((hovered === null && hoveredConnection === null) || !active) { tooltip.hidden = true; return; }
      let point;
      if (hoveredConnection !== null){
        const edge = edges[hoveredConnection], connection = edge.connection;
        tooltip.replaceChildren(node('span', 'world-tooltip-country', pair(edge)), node('span', 'world-tooltip-kind', kind(connection)),
          node('strong', '', connection.label), node('p', 'world-tooltip-explanation', connection.explanation), node('span', 'world-tooltip-hint', 'Click or tap for sources'));
        point = hoverPoint || edgePoints.get(hoveredConnection);
      } else {
        const perspective = perspectives[hovered];
        tooltip.replaceChildren(node('span', 'world-tooltip-country', country(hovered)), node('strong', '', perspective.coverage_label || perspective.framing || perspective.label));
        point = screenPoints.get(hovered);
      }
      tooltip.hidden = false;
      point ||= { x: viewport.clientWidth / 2, y: 20 };
      const viewportBox = viewport.getBoundingClientRect(), containerBox = container.getBoundingClientRect();
      const left = viewportBox.left - containerBox.left, top = viewportBox.top - containerBox.top;
      const width = tooltip.offsetWidth, height = tooltip.offsetHeight;
      tooltip.style.left = left + clamp(point.x - width / 2, 8, Math.max(8, viewport.clientWidth - width - 8)) + 'px';
      const above = top + point.y - height - 20;
      tooltip.style.top = (above >= 8 ? above : top + point.y + 20) + 'px';
    }
    function updateHighlights(){
      const edgeIndex = hoveredConnection ?? selectedConnection;
      const edge = edgeIndex === null ? null : edges[edgeIndex];
      const countryIndex = hovered ?? selected;
      edges.forEach((item, index) => {
        item.group.classList.toggle('is-selected', index === edgeIndex);
        item.group.classList.toggle('is-muted', edge ? index !== edgeIndex : countryIndex !== null && item.from !== countryIndex && item.to !== countryIndex);
        item.hit.setAttribute('aria-pressed', String(index === selectedConnection));
        comparisonChoices[index].setAttribute('aria-pressed', String(index === selectedConnection));
      });
      markers.forEach(({button, index}) => button.classList.toggle('is-related', Boolean(edge && (edge.from === index || edge.to === index))));
      paths.forEach((path, id) => path.classList.toggle('is-selected', edge ? locations[edge.from]?.id === id || locations[edge.to]?.id === id : selected !== null && locations[selected]?.id === id));
    }
    function chooseConnection(index){
      const closing = selectedConnection === index;
      select(null);
      if (closing) return;
      selectedConnection = index;
      const edge = edges[index], connection = edge.connection;
      detail.hidden = false;
      const close = node('button', 'world-detail-close', 'Close comparison'); close.type = 'button';
      close.addEventListener('click', event => {
        select(null);
        if (event.detail === 0){
          if (edge.hit.getAttribute('tabindex') === '0') edge.hit.focus();
          else { comparisonList.open = true; comparisonChoices[index].focus(); }
        }
      });
      detail.append(close, node('p', 'perspective-kicker', pair(edge)), node('p', 'world-comparison-kind', kind(connection)),
        node('h4', '', connection.label), node('p', 'world-explanation', connection.explanation));
      appendSources(detail, connection.article_ids); updateHighlights();
    }
    function select(index){
      selected = index; selectedConnection = null;
      choices.forEach((button, i) => button.setAttribute('aria-pressed', String(i === index)));
      markers.forEach(({button, index: i}) => button.setAttribute('aria-pressed', String(i === index)));
      detail.replaceChildren(); detail.hidden = index === null;
      if (index !== null){
        const perspective = perspectives[index];
        const close = node('button', 'world-detail-close', 'Close answer'); close.type = 'button';
        close.addEventListener('click', () => { select(null); choices[index]?.focus(); });
        detail.append(close, node('p', 'perspective-kicker', country(index)), node('h4', '', perspective.coverage_label || perspective.framing),
          node('p', 'world-explanation', perspective.explanation || perspective.framing));
        appendSources(detail, perspective.article_ids);
      }
      updateHighlights();
    }

    function layout(){
      if (!active || !atlas || !viewport.isConnected || !viewport.clientWidth) return;
      svg.setAttribute('viewBox', [view.x, view.y, view.width, view.height].join(' '));
      const m = metrics(), placed = []; screenPoints.clear(); leaders.replaceChildren();
      markers.forEach(({button, index}) => {
        const [x, y] = locations[index].anchor;
        const visible = x >= view.x && x <= view.x + view.width && y >= view.y && y <= view.y + view.height;
        button.hidden = !visible; if (!visible) return;
        const anchor = { x: (x - view.x) * m.scale + m.left, y: (y - view.y) * m.scale + m.top };
        let point = { ...anchor };
        // Spread colliding hit targets in screen pixels, retaining a line to their true location.
        for (let attempt = 0; attempt < 240; attempt++){
          const radius = attempt ? 7 * Math.sqrt(attempt) : 0, angle = attempt * 2.399963;
          point = { x: clamp(anchor.x + Math.cos(angle) * radius, 18, m.width - 18), y: clamp(anchor.y + Math.sin(angle) * radius, 18, m.height - 18) };
          if (placed.every(other => Math.hypot(other.x - point.x, other.y - point.y) >= 34)) break;
        }
        placed.push(point); screenPoints.set(index, point);
        button.style.left = point.x + 'px'; button.style.top = point.y + 'px';
        if (Math.hypot(point.x - anchor.x, point.y - anchor.y) > 3){
          leaders.append(svgNode('line', { x1: x, y1: y, x2: (point.x - m.left) / m.scale + view.x, y2: (point.y - m.top) / m.scale + view.y }),
            svgNode('circle', { cx: x, cy: y, r: 2 / m.scale }));
        }
      });
      edgePoints.clear();
      edges.forEach((edge, index) => {
        const start = locations[edge.from]?.anchor, end = locations[edge.to]?.anchor;
        if (!start || !end) { edge.group.setAttribute('display', 'none'); edge.hit.setAttribute('tabindex', '-1'); return; }
        const fromScreen = screenPoints.get(edge.from), toScreen = screenPoints.get(edge.to);
        const a = fromScreen ? { x: (fromScreen.x - m.left) / m.scale + view.x, y: (fromScreen.y - m.top) / m.scale + view.y } : {x:start[0], y:start[1]};
        const b = toScreen ? { x: (toScreen.x - m.left) / m.scale + view.x, y: (toScreen.y - m.top) / m.scale + view.y } : {x:end[0], y:end[1]};
        const dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy) || 1;
        const bend = Math.min(32 + Math.floor(index / 2) * 14, distance * m.scale * .4 + 20) / m.scale * (index % 2 ? 1 : -1);
        const c = { x: (a.x + b.x) / 2 - dy / distance * bend, y: (a.y + b.y) / 2 + dx / distance * bend };
        const d = `M ${a.x} ${a.y} Q ${c.x} ${c.y} ${b.x} ${b.y}`;
        edge.path.setAttribute('d', d); edge.hit.setAttribute('d', d);
        const visible = Math.max(a.x,b.x,c.x) >= view.x && Math.min(a.x,b.x,c.x) <= view.x + view.width && Math.max(a.y,b.y,c.y) >= view.y && Math.min(a.y,b.y,c.y) <= view.y + view.height;
        edge.group.setAttribute('display', visible ? 'inline' : 'none'); edge.hit.setAttribute('tabindex', visible ? '0' : '-1');
        edgePoints.set(index, { x: (a.x / 4 + c.x / 2 + b.x / 4 - view.x) * m.scale + m.left, y: (a.y / 4 + c.y / 2 + b.y / 4 - view.y) * m.scale + m.top });
      });
      zoomIn.disabled = zoom >= 8; zoomOut.disabled = zoom <= 1; updateTooltip();
    }
    function schedule(){ if (active) { cancelAnimationFrame(frame); frame = requestAnimationFrame(layout); } }
    listen(viewport, 'pointerdown', event => {
      if (!atlas || event.button !== 0 || event.target.closest('button,[data-world-connection]')) return;
      const m = metrics(); drag = { x: event.clientX, y: event.clientY, viewX: view.x, viewY: view.y, scale: m.scale };
      viewport.setPointerCapture(event.pointerId); viewport.classList.add('is-dragging'); hovered = null; hoveredConnection = null; tooltip.hidden = true; updateHighlights();
    });
    listen(viewport, 'pointermove', event => {
      if (!drag) return;
      view.x = drag.viewX - (event.clientX - drag.x) / drag.scale; view.y = drag.viewY - (event.clientY - drag.y) / drag.scale;
      constrain(); schedule();
    });
    const stopDrag = () => { drag = null; viewport.classList.remove('is-dragging'); };
    listen(viewport, 'pointerup', stopDrag); listen(viewport, 'pointercancel', stopDrag); listen(viewport, 'lostpointercapture', stopDrag);
    listen(viewport, 'dblclick', event => {
      if (!atlas || event.target.closest('button,[data-world-connection]')) return;
      const box = viewport.getBoundingClientRect(), m = metrics();
      changeZoom(zoom * 1.6, { x: view.x + (event.clientX - box.left - m.left) / m.scale, y: view.y + (event.clientY - box.top - m.top) / m.scale });
    });
    listen(container, 'keydown', event => { if (event.key === 'Escape') { hovered = null; hoveredConnection = null; tooltip.hidden = true; select(null); } });
    const observer = globalThis.ResizeObserver ? new ResizeObserver(schedule) : null;
    observer?.observe(viewport); listen(window, 'resize', schedule);

    loadAtlas().then(data => {
      if (!active) return;
      atlas = data;
      const byName = new Map();
      const displayNames = globalThis.Intl?.DisplayNames ? new Intl.DisplayNames(['en'], { type: 'region' }) : null;
      atlas.countries.forEach(location => {
        location.names.forEach(name => byName.set(normalize(name), location));
        if (/^[A-Z]{2}$/.test(location.iso2 || '')) byName.set(normalize(displayNames?.of(location.iso2)), location);
        if (location.path){
          const path = svgNode('path', { d: location.path, 'fill-rule': 'evenodd' }); paths.set(location.id, path); land.append(path);
        }
      });
      perspectives.forEach((perspective, index) => {
        const location = byName.get(normalize(country(index))); locations[index] = location;
        if (!location) { choices[index].title = 'Location unavailable; select to read the answer'; return; }
        const path = paths.get(location.id);
        if (path) { path.classList.add('has-answer'); path.style.setProperty('--perspective-hue', hue(index)); }
        const button = node('button', 'world-marker'); button.type = 'button'; button.style.setProperty('--perspective-hue', hue(index));
        button.setAttribute('aria-label', country(index) + ': ' + (perspective.coverage_label || perspective.framing || 'Read answer'));
        button.setAttribute('aria-describedby', tooltip.id); button.setAttribute('aria-controls', detail.id); button.setAttribute('aria-pressed', String(selected === index));
        listen(button, 'pointerenter', event => { if (event.pointerType !== 'touch') preview(index); });
        listen(button, 'pointerleave', () => { if (document.activeElement !== button) hidePreview(index); });
        listen(button, 'focus', () => preview(index)); listen(button, 'blur', () => hidePreview(index));
        listen(button, 'click', event => { choose(index); dismissTouchPreview(event); });
        viewport.append(button); markers.push({button, index});
      });
      const missing = perspectives.map((_, index) => !locations[index] ? country(index) : '').filter(Boolean);
      status.textContent = !perspectives.length ? 'There are no country answers to place on the map.' : missing.length ?
        'Location unavailable for ' + missing.join(', ') + '. Select a country below to read its answer.' : '';
      status.hidden = Boolean(perspectives.length) && !missing.length;
      updateHighlights(); schedule();
    }).catch(() => {
      if (active) { status.hidden = false; status.textContent = 'The map could not be loaded. You can still select a country below to read its answer.'; }
    });
    return { select, destroy(){ active = false; events.abort(); observer?.disconnect(); cancelAnimationFrame(frame); } };
  }
  return { mount };
})();
