// "Set the scene": the sheet shown before a brand-new story starts.
// Pick one of the character's story premises, tweak it if you like, and choose who opens the scene.
// Used by the start screen and by the Switch story drawer.
(function () {
  const css = `
  .scene-shade { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:200; display:flex; align-items:center; justify-content:center; padding:20px; }
  .scene { background:var(--card); color:var(--text); border:1px solid var(--line); border-radius:22px;
           width:min(620px, 100%); max-height:calc(100dvh - 40px); overflow:auto; padding:20px 22px 18px; font:15px/1.5 'Inter', system-ui, sans-serif; }
  .scene { position:relative; }
  .scene .sx { position:absolute; top:14px; right:14px; background:none; border:1px solid var(--line); color:var(--muted);
           border-radius:10px; width:32px; height:32px; cursor:pointer; font-size:14px; }
  .scene .sx:hover { color:var(--text); }
  .scene h3 { margin:0; font-size:19px; font-weight:600; }
  .scene .ssub { color:var(--muted); font-size:14px; margin:2px 0 16px; }
  .scene label.slabel { display:block; color:var(--muted); font-size:13px; margin:14px 4px 6px; }
  .scene select, .scene textarea, .scene input[type=text] { width:100%; background:var(--field); color:var(--text); border:0;
           border-radius:14px; padding:10px 14px; font:inherit; outline:none; }
  .scene textarea { resize:vertical; line-height:1.55; }
  .scene select:focus, .scene textarea:focus, .scene input[type=text]:focus { box-shadow:0 0 0 1px var(--line-strong) inset; }
  .scene .who { display:flex; gap:6px; background:var(--field); border-radius:12px; padding:3px; }
  .scene .who button { flex:1; background:none; border:0; color:var(--muted); border-radius:9px; padding:8px; cursor:pointer; font:inherit; font-size:14px; }
  .scene .who button.on { background:var(--card); color:var(--text); }
  .scene .shint { color:var(--dim); font-size:13px; margin:6px 4px 0; }
  .scene .snew { background:var(--here-bg); border:1px solid var(--here-line); border-radius:14px; padding:10px 12px; margin-top:14px; font-size:13.5px; color:var(--muted); }
  .scene .snew input { margin-top:8px; }
  .scene .sbtns { display:flex; gap:10px; justify-content:flex-end; align-items:center; margin-top:18px; }
  .scene .sbtns .serr { flex:1; color:var(--bad); font-size:13.5px; }
  .scene .sbtn { background:var(--field); color:var(--text); border:1px solid var(--line); border-radius:12px; padding:9px 16px; cursor:pointer; font:inherit; }
  .scene .sbtn.primary { background:var(--accent); border-color:var(--accent); color:var(--on-accent); }
  .scene .sbtn:disabled { opacity:.5; cursor:default; }
  @media (pointer: coarse) { .scene select, .scene textarea, .scene input { font-size:16px !important; } }
  @media (max-width: 560px) { .scene-shade { padding:0; align-items:flex-end; } .scene { border-radius:22px 22px 0 0; max-height:92dvh; } }`;
  const tag = document.createElement('style'); tag.textContent = css; document.head.append(tag);

  const make = (t, attrs = {}, ...kids) => {
    const e = document.createElement(t);
    for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k.startsWith('on')) e[k] = v; else e.setAttribute(k, v); }
    kids.forEach(k => e.append(k)); return e;
  };

  // Returns a promise: true once the story has started (the caller then opens it), false if cancelled.
  window.setTheScene = async function ({universe, character, user}) {
    const q = new URLSearchParams({universe, character, user});
    let data;
    try {
      const r = await fetch('/api/scene?' + q);
      data = await r.json();
    } catch (e) {
      alert('Couldn\'t open "Set the scene". If you just updated the app, restart it: right-click the tray icon → Restart, then refresh this page.');
      return false;
    }
    if (data.error) { alert(data.error); return false; }
    return new Promise(resolve => {
      let pick = data.premises.find(p => p.id === data.chosen) || data.premises[0];
      let opening = 'char';
      const shade = make('div', {class:'scene-shade'});
      const box = make('div', {class:'scene', role:'dialog', 'aria-modal':'true', 'aria-label':'Set the scene'});
      shade.append(box);

      const sel = make('select');
      data.premises.forEach(p => sel.append(new Option(p.name, p.id)));
      const premise = make('textarea', {rows:'6', placeholder:'Where and when the story begins, and how you meet. Leave empty to start with no premise.'});
      const greeting = make('textarea', {rows:'5', placeholder:`${data.char}'s first message. Use *asterisks* for narration.`});
      const who = make('div', {class:'who'});
      const btnChar = make('button', {type:'button'}, `${data.char} speaks first`);
      const btnUser = make('button', {type:'button'}, 'I\'ll start');
      who.append(btnChar, btnUser);
      const greetWrap = make('div', {}, make('label', {class:'slabel'}, 'Opening message'), greeting);
      const userHint = make('p', {class:'shint'}, `The chat starts empty. Your first message sets the scene, and ${data.char} replies.`);
      const newName = make('input', {type:'text', maxlength:'60'});
      const where = make('input', {type:'text', maxlength:'160', class:'swhere', placeholder:'e.g. Aestria, the road to Houlton (optional)'});
      const newBox = make('div', {class:'snew'}, 'You changed the text, so it will be saved as a new premise for ' + data.char +
        ' (the original stays as it is). Name it:', newName);
      const err = make('span', {class:'serr'});
      const cancel = make('button', {class:'sbtn', type:'button'}, 'Cancel');
      const start = make('button', {class:'sbtn primary', type:'button'}, 'Start story');

      const x = make('button', {type:'button', class:'sx', title:'Close (Esc)', 'aria-label':'Close'}, '✕');
      box.append(
        x,
        make('h3', {}, 'Set the scene'),
        make('div', {class:'ssub'}, `${data.char} & ${data.user} · new story`),
        ...(data.premises.length > 1 ? [make('label', {class:'slabel'}, 'Story premise'), sel] : [make('label', {class:'slabel'}, 'Story premise')]),
        premise,
        make('p', {class:'shint'}, `Only ${data.char} and you see this as background; it's never shown in the chat. Manage premises in the editor, on ${data.char}'s page.`),
        make('label', {class:'slabel'}, 'Where does it begin?'), where,
        make('p', {class:'shint'}, 'Region first, then the place. Its Places & Lore entry stays loaded while you\'re there. It updates itself as the story moves.'),
        make('label', {class:'slabel'}, 'Who opens the scene?'), who,
        greetWrap, userHint, newBox,
        make('div', {class:'sbtns'}, err, cancel, start));

      const edited = () => premise.value.trim() !== pick.premise.trim() ||
                           (opening === 'char' && greeting.value.trim() !== pick.greeting.trim());
      const refresh = () => {
        btnChar.classList.toggle('on', opening === 'char'); btnUser.classList.toggle('on', opening === 'user');
        greetWrap.hidden = opening !== 'char'; userHint.hidden = opening !== 'user';
        newBox.hidden = !edited();
      };
      const load = () => {
        premise.value = pick.premise; greeting.value = pick.greeting;
        newName.value = `${pick.id === 'default' ? data.user + '\'s story' : pick.name + ' (' + data.user + ')'}`;
        if (!pick.greeting.trim() && opening === 'char') opening = 'user';
        refresh();
      };
      sel.value = pick.id;
      sel.onchange = () => {
        if (edited() && !confirm('Switch premise? Your changes to the text will be lost.')) { sel.value = pick.id; return; }
        pick = data.premises.find(p => p.id === sel.value); opening = 'char'; load();
      };
      premise.oninput = greeting.oninput = refresh;
      btnChar.onclick = () => { opening = 'char'; refresh(); };
      btnUser.onclick = () => { opening = 'user'; refresh(); };
      const close = ok => { document.removeEventListener('keydown', esc); shade.remove(); resolve(ok); };
      const esc = e => { if (e.key === 'Escape') close(false); };
      document.addEventListener('keydown', esc);
      cancel.onclick = x.onclick = () => close(false);
      shade.onclick = e => { if (e.target === shade) close(false); };
      start.onclick = async () => {
        if (opening === 'char' && !greeting.value.trim()) { err.textContent = `Write an opening message, or choose "I'll start".`; return; }
        start.disabled = true; err.textContent = '';
        const body = {universe, character, user, premise: pick.id, opening, where: where.value.trim(),
                      edited: edited() ? {name: newName.value.trim(), premise: premise.value, greeting: opening === 'char' ? greeting.value : pick.greeting} : null};
        try {
          const r = await fetch('/api/scene/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
          let j;
          try { j = await r.json(); } catch (e) { j = {error: 'The app needs a restart to start new stories: right-click the tray icon → Restart.'}; }
          if (j.error) { err.textContent = j.error; start.disabled = false; return; }
          close(true);
        } catch (e) { err.textContent = 'The app isn\'t responding.'; start.disabled = false; }
      };
      load();
      document.body.append(shade);
      (data.premises.length > 1 ? sel : premise).focus();
    });
  };
})();
