// VersiDen colour themes. Loaded in the <head> of every page so the saved theme applies
// before anything is drawn (no flash of the wrong colours). The choice is per device/browser.
(function () {
  const THEMES = [
    {id: 'dusk',      name: 'Dusk Grove',    note: 'twilight fantasy',      group: 'Dark',  bg: '#121015', accent: '#b48cf0'},
    {id: 'ember',     name: 'Ember Hearth',  note: 'taverns, cosy fantasy', group: 'Dark',  bg: '#14100d', accent: '#e8a15c'},
    {id: 'sea',       name: 'Moonlit Sea',   note: 'calm, coastal, mystery', group: 'Dark', bg: '#0c1217', accent: '#7cc4e0'},
    {id: 'verdant',   name: 'Verdant Wilds', note: 'forests, adventure',    group: 'Dark',  bg: '#0e130f', accent: '#8fcf8a'},
    {id: 'crimson',   name: 'Crimson Court', note: 'gothic, intrigue, romance', group: 'Dark', bg: '#140b0e', accent: '#e57a92'},
    {id: 'starfall',  name: 'Starfall',      note: 'sci-fi, space opera',   group: 'Dark',  bg: '#0a0e1a', accent: '#5fd3e6'},
    {id: 'neon',      name: 'Neon Noir',     note: 'cyberpunk, city nights', group: 'Dark', bg: '#0b0a10', accent: '#ff4fd8'},
    {id: 'frost',     name: 'Frostbound',    note: 'winter, northern sagas', group: 'Dark', bg: '#0f1419', accent: '#a9d6ff'},
    {id: 'desert',    name: 'Desert Sun',    note: 'sands, old empires',    group: 'Dark',  bg: '#15110b', accent: '#e3c06b'},
    {id: 'eldritch',  name: 'Eldritch',      note: 'horror, the unknown',   group: 'Dark',  bg: '#0b0d0a', accent: '#b5d65a'},
    {id: 'ink',       name: 'Midnight Ink',  note: 'neutral, pure black',   group: 'Dark',  bg: '#000000', accent: '#d9d9d9'},
    {id: 'parchment', name: 'Parchment',     note: 'warm, daytime reading', group: 'Light', bg: '#f4eee3', accent: '#8a5a2b'},
    {id: 'sakura',    name: 'Sakura Dawn',   note: 'soft romance',          group: 'Light', bg: '#fbf3f5', accent: '#b54a72'},
    {id: 'mist',      name: 'Mist',          note: 'cool and calm',         group: 'Light', bg: '#eef2f5', accent: '#356f94'},
    {id: 'contrast',  name: 'High Contrast', note: 'easiest to read',       group: 'Accessibility', bg: '#000000', accent: '#ffd400'},
  ];
  const KEY = 'versiden-theme';
  const byId = id => THEMES.find(t => t.id === id) || THEMES[0];
  const read = () => { try { return localStorage.getItem(KEY) || 'dusk'; } catch (e) { return 'dusk'; } };

  function apply(id) {
    const t = byId(id), root = document.documentElement;
    if (t.id === 'dusk') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', t.id);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', t.bg);
    return t;
  }

  function set(id) {
    try { localStorage.setItem(KEY, byId(id).id); } catch (e) { /* private mode: applies to this page only */ }
    const t = apply(id);
    document.querySelectorAll('.theme-sw').forEach(b => b.classList.toggle('on', b.dataset.theme === t.id));
    document.querySelectorAll('.theme-name').forEach(n => { n.textContent = `${t.name} · ${t.note}`; });
    document.dispatchEvent(new CustomEvent('themechange', {detail: t}));
  }

  // A grid of round swatches, grouped Dark / Light / Accessibility, with the chosen theme's name below.
  function picker() {
    const box = document.createElement('div');
    const current = byId(read());
    for (const g of ['Dark', 'Light', 'Accessibility']) {
      const h = document.createElement('div'); h.className = 'theme-group'; h.textContent = g;
      const grid = document.createElement('div'); grid.className = 'theme-grid'; grid.setAttribute('role', 'radiogroup');
      grid.setAttribute('aria-label', `${g} themes`);
      THEMES.filter(t => t.group === g).forEach(t => {
        const b = document.createElement('button'); b.type = 'button'; b.className = 'theme-sw' + (t.id === current.id ? ' on' : '');
        b.dataset.theme = t.id; b.title = `${t.name}: ${t.note}`; b.setAttribute('aria-label', t.name);
        b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', t.id === current.id);
        b.style.setProperty('--sw-bg', t.bg); b.style.setProperty('--sw-accent', t.accent);
        b.onclick = () => { set(t.id); grid.closest('div').parentElement.querySelectorAll('.theme-sw')
          .forEach(x => x.setAttribute('aria-checked', x.dataset.theme === t.id)); };
        grid.append(b);
      });
      box.append(h, grid);
    }
    const name = document.createElement('div'); name.className = 'theme-name'; name.textContent = `${current.name} · ${current.note}`;
    box.append(name);
    return box;
  }

  apply(read());
  // Another tab changed the theme: follow it.
  window.addEventListener('storage', e => { if (e.key === KEY) set(read()); });
  window.VersiTheme = {list: THEMES, current: () => byId(read()), set, picker};
})();
