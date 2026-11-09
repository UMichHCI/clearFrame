// Shared template catalog, validation, and deterministic caption rendering.
// Artwork stays local; the model returns only IDs and text.
globalThis.ClearFrameMemes = (() => {
  let catalogPromise;
  const imagePromises = new Map();

  function catalog(){
    if (!catalogPromise){
      catalogPromise = fetch('/static/meme-templates/catalog.json').then(response => {
        if (!response.ok) throw new Error('Could not load the meme templates. Reload and try again.');
        return response.json();
      }).catch(error => { catalogPromise = null; throw error; });
    }
    return catalogPromise;
  }

  function itemIds(data){
    const ids = [];
    if (data.summary && data.summary.trim()) ids.push('overview');
    (data.categories || []).forEach((category, index) => {
      if (category.paragraph && category.paragraph.trim()) ids.push('finding-' + (index + 1));
    });
    return ids;
  }

  function validate(view, data, templates){
    const fail = () => { throw new Error('These saved memes do not match readable results. Generate a new set to continue.'); };
    if (!view || ![1, 2].includes(view.version) || !Array.isArray(view.items)) fail();
    const expected = itemIds(data);
    if (view.items.length !== expected.length) fail();
    const known = new Map(templates.map(template => [template.id, template]));
    const byId = new Map();
    const text = (value, limit, words) => {
      if (typeof value !== 'string' || !value.trim() || Array.from(value).length > limit || value.trim().split(/\s+/u).length > words) fail();
      return value.trim();
    };
    view.items.forEach(item => {
      if (!item || !expected.includes(item.id) || byId.has(item.id) || !known.has(item.template_id)) fail();
      const template = known.get(item.template_id);
      const slots = template.slots.filter(slot => view.version !== 1 || !slot.legacy_optional);
      if (!item.captions || typeof item.captions !== 'object' || Array.isArray(item.captions) || Object.keys(item.captions).length !== slots.length) fail();
      const captions = {};
      slots.forEach(slot => { captions[slot.id] = text(item.captions[slot.id], slot.max_chars, slot.max_words); });
      byId.set(item.id, {
        id: item.id, template_id: template.id, captions,
        sentence: text(item.sentence, view.version === 1 ? 400 : 240, view.version === 1 ? 35 : 20), alt_text: text(item.alt_text, 500, 100),
      });
    });
    return { version: view.version, analysis_hash: typeof view.analysis_hash === 'string' ? view.analysis_hash : '', items: expected.map(id => byId.get(id)) };
  }

  function imageFor(filename){
    if (!imagePromises.has(filename)){
      imagePromises.set(filename, new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => { imagePromises.delete(filename); reject(new Error('A meme image could not load. Reload and try again.')); };
        image.src = '/static/meme-templates/' + encodeURIComponent(filename);
      }));
    }
    return imagePromises.get(filename);
  }

  function wrap(context, text, width){
    const lines = [];
    let line = '';
    for (const word of text.split(/\s+/u)){
      if (context.measureText(word).width > width){
        if (line) { lines.push(line); line = ''; }
        let part = '';
        for (const character of word){
          if (part && context.measureText(part + character).width > width) { lines.push(part); part = ''; }
          part += character;
        }
        line = part;
      } else if (line && context.measureText(line + ' ' + word).width > width){
        lines.push(line); line = word;
      } else line += (line ? ' ' : '') + word;
    }
    if (line) lines.push(line);
    return lines;
  }

  async function render(item, template){
    const image = await imageFor(template.file);
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1200 / image.naturalWidth);
    canvas.width = Math.round(image.naturalWidth * scale);
    canvas.height = Math.round(image.naturalHeight * scale);
    const context = canvas.getContext('2d');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    for (const slot of template.slots){
      // Saved version-one cards did not have actor labels or tailored conclusions.
      if (!Object.hasOwn(item.captions, slot.id) && slot.legacy_optional) continue;
      const [x, y, width, height] = slot.box.map((fraction, index) => fraction * (index % 2 ? canvas.height : canvas.width));
      context.save();
      context.beginPath(); context.rect(x, y, width, height); context.clip();
      if (slot.background) { context.fillStyle = slot.background; context.fillRect(x, y, width, height); }
      const padding = Math.max(5, canvas.width * 0.012);
      const available = width - padding * 2;
      let size = Math.min(canvas.width * 0.065, height * 0.43);
      let lines;
      do {
        context.font = 'bold ' + size + 'px Arial, sans-serif';
        lines = wrap(context, item.captions[slot.id], available);
        if (lines.length * size * 1.15 <= height - padding * 2) break;
        size -= 0.5;
      } while (size > 5);
      context.textAlign = 'center'; context.textBaseline = 'middle';
      context.fillStyle = slot.color || '#ffffff';
      context.lineJoin = 'round'; context.strokeStyle = '#111111'; context.lineWidth = Math.max(1, size * 0.11);
      const start = y + height / 2 - (lines.length - 1) * size * 1.15 / 2;
      lines.forEach((line, index) => {
        const baseline = start + index * size * 1.15;
        if (!slot.color) context.strokeText(line, x + width / 2, baseline);
        context.fillText(line, x + width / 2, baseline);
      });
      context.restore();
    }
    return canvas.toDataURL('image/png');
  }

  return { catalog, itemIds, validate, render, wrap };
})();
