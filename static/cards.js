// Export / import of character and player cards (.json), plus a small choice dialog.
// Used by the start screen and the editor.
(function () {
  const css = `
  .cd-shade { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:210; display:flex; align-items:center; justify-content:center; padding:20px; }
  .cd { background:var(--card); color:var(--text); border:1px solid var(--line); border-radius:20px;
        width:min(440px, 100%); padding:20px 22px 18px; font:15px/1.5 'Inter', system-ui, sans-serif; }
  .cd h3 { margin:0 0 8px; font-size:17px; font-weight:600; }
  .cd p { margin:0; color:var(--muted); font-size:14px; white-space:pre-line; }
  .cd .cdb { display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; margin-top:18px; }
  .cd button { background:var(--field); color:var(--text); border:1px solid var(--line); border-radius:12px; padding:9px 14px; cursor:pointer; font:inherit; font-size:14px; }
  .cd button.primary { background:var(--accent); border-color:var(--accent); color:var(--on-accent); }
  .pa { display:flex; flex-wrap:wrap; gap:6px 8px; align-items:center; }
  .pa label { flex-basis:100%; color:var(--muted); font-size:12.5px; padding-left:2px; }
  .pa select { flex:1000 1 160px; min-width:0; background:var(--field); color:var(--text); border:1px solid transparent; border-radius:10px;
               padding:8px 10px; font:inherit; font-size:14px; outline:none; cursor:pointer; }
  .pa select:focus { border-color:var(--line-strong); }
  .pa button { flex:1 0 auto; background:var(--accent); color:var(--on-accent); border:0; border-radius:10px; padding:8px 13px; font:inherit; font-size:14px;
               cursor:pointer; white-space:nowrap; }
  .pa button.new { background:var(--field); color:var(--text); border:1px solid var(--line-strong); }
  .pa button[hidden] { display:none; }`;
  const tag = document.createElement('style'); tag.textContent = css; document.head.append(tag);

  // buttons: [{label, value, primary}]; resolves with the value, or null for Cancel / Esc / click outside.
  window.chooseDialog = function ({title, text, body, buttons, wide}) {
    return new Promise(resolve => {
      const shade = document.createElement('div'); shade.className = 'cd-shade';
      const box = document.createElement('div'); box.className = 'cd'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
      const h = document.createElement('h3'); h.textContent = title;
      const p = document.createElement('p'); p.textContent = text || '';
      const row = document.createElement('div'); row.className = 'cdb';
      const done = v => { document.removeEventListener('keydown', esc); shade.remove(); resolve(v); };
      const esc = e => { if (e.key === 'Escape') done(null); };
      [{label: 'Cancel', value: null}, ...buttons].forEach(b => {
        const btn = document.createElement('button'); btn.type = 'button'; btn.textContent = b.label;
        if (b.primary) btn.className = 'primary';
        btn.onclick = () => done(b.value); row.append(btn);
      });
      box.append(h, p); if (body) box.append(body);
      if (wide) box.style.width = 'min(560px, 100%)';
      if (!text) p.remove();
      box.append(row); shade.append(box);
      shade.onclick = e => { if (e.target === shade) done(null); };
      document.addEventListener('keydown', esc);
      document.body.append(shade);
      (row.querySelector('.primary') || row.lastChild).focus();
    });
  };

  // One row per character: "Play as [player ▾] [Continue / Start new story]".
  // c: {id, name, stories, last}; users: [{id, name}]; here: the player whose story is open now (or null).
  // onGo(userId, isNew) is called when the button is pressed.
  window.playAsRow = function (c, users, here, onGo) {
    const row = document.createElement('div'); row.className = 'pa';
    const label = document.createElement('label'); label.textContent = 'Play as';
    const sel = document.createElement('select'); sel.title = `Who you play as with ${c.name}`;
    const btn = document.createElement('button'); btn.type = 'button';
    const order = [...users].sort((a, b) => (c.stories.includes(b.id) - c.stories.includes(a.id)) || a.name.localeCompare(b.name));
    order.forEach(p => sel.append(new Option(`${p.name} · ${p.id === here ? 'you are here' : c.stories.includes(p.id) ? 'your story' : 'new story'}`, p.id)));
    const id = `pa-${c.id}`; sel.id = id; label.htmlFor = id;
    sel.value = here || c.last || (order[0] || {}).id || '';
    const sync = () => {
      const has = c.stories.includes(sel.value);
      btn.hidden = sel.value === here;     // the dropdown already says "you are here"
      btn.textContent = has ? 'Continue' : 'Start new story';
      btn.className = has || sel.value === here ? '' : 'new';
    };
    sel.onchange = sync; sync();
    btn.onclick = () => onGo(sel.value, !c.stories.includes(sel.value));
    row.append(label, sel, btn);
    return row;
  };

  // Download a character or player as a .json card.
  window.exportCard = async function (universe, kind, id) {
    let extra = '';
    if (kind === 'user') {
      const pick = await chooseDialog({title: 'Export player',
        text: 'Include the Private section? It holds this player\'s background and secrets. Leave it out if you\'re sharing the file with someone.',
        buttons: [{label: 'Include private', value: 'yes'}, {label: 'Leave it out', value: 'no', primary: true}]});
      if (!pick) return;
      if (pick === 'yes') extra = '&private=1';
    }
    const a = document.createElement('a');
    a.href = `/api/export?u=${encodeURIComponent(universe)}&kind=${kind}&id=${encodeURIComponent(id)}${extra}`;
    a.download = ''; document.body.append(a); a.click(); a.remove();
  };

  // Pick a .json card and add it to a universe. Resolves with {kind, id, name} or null.
  window.importCard = function (universe) {
    return new Promise(resolve => {
      const input = document.createElement('input'); input.type = 'file'; input.accept = '.json,application/json';
      input.onchange = async () => {
        const file = input.files[0]; if (!file) return resolve(null);
        let data;
        try { data = JSON.parse(await file.text()); }
        catch (e) { alert('That file isn\'t a character or player file (it couldn\'t be read as JSON).'); return resolve(null); }
        const send = async mode => {
          try {
            const r = await fetch('/api/import', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({u: universe, data, mode})});
            return await r.json();
          } catch (e) { return {error: 'The app isn\'t responding. If you just updated it, restart it from the tray icon.'}; }
        };
        let r = await send(null);
        if (r.conflict) {
          const what = r.kind === 'user' ? 'player' : 'character';
          const mode = await chooseDialog({title: `${r.name} already exists`,
            text: `This world already has a ${what} called ${r.name}.\n\nAdd as a copy: a separate ${what} with a new name.\nReplace: swaps in the imported description${r.kind === 'character' ? ' and premises' : ''}. Your stories with them are kept.`,
            buttons: [{label: 'Replace', value: 'replace'}, {label: 'Add as a copy', value: 'copy', primary: true}]});
          if (!mode) return resolve(null);
          r = await send(mode);
        }
        if (r.error) { alert(r.error); return resolve(null); }
        resolve(r);
      };
      input.click();
    });
  };
})();
