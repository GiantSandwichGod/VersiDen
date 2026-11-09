// Portrait cropper: drag to move, slider / mouse wheel / pinch to zoom, round preview.
// cropImage(source) -> Promise<Blob | null>, where source is a File/Blob or an image URL.
// The result is a square 512×512 picture (WebP, or PNG if the browser can't make WebP).
(function () {
  const css = `
  .crop-shade { position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:220; display:flex; align-items:center; justify-content:center; padding:16px; }
  .crop { background:var(--card); color:var(--text); border:1px solid var(--line); border-radius:22px;
          width:min(420px, 100%); padding:18px 20px; font:15px/1.5 'Inter', system-ui, sans-serif; }
  .crop h3 { margin:0 0 2px; font-size:17px; font-weight:600; }
  .crop .chint { color:var(--muted); font-size:13px; margin:0 0 14px; }
  .crop .stage { position:relative; width:100%; aspect-ratio:1; border-radius:16px; overflow:hidden; background:var(--stage);
                 touch-action:none; cursor:grab; user-select:none; }
  .crop .stage.drag { cursor:grabbing; }
  .crop canvas { position:absolute; inset:0; width:100%; height:100%; }
  .crop .ring { position:absolute; inset:0; pointer-events:none;
                background:radial-gradient(circle closest-side at center, transparent calc(100% - 1px), rgba(11,11,12,.62) 100%);
                box-shadow:inset 0 0 0 1px rgba(255,255,255,.08); }
  .crop .ring::after { content:''; position:absolute; inset:0; border-radius:50%; box-shadow:0 0 0 1.5px rgba(255,255,255,.55); }
  .crop .zoom { display:flex; align-items:center; gap:10px; margin:14px 2px 4px; color:var(--muted); font-size:16px; }
  .crop .zoom input { flex:1; accent-color:var(--accent); }
  .crop .cbtns { display:flex; gap:10px; justify-content:flex-end; margin-top:14px; }
  .crop .cbtns button { background:var(--field); color:var(--text); border:1px solid var(--line); border-radius:12px;
                        padding:9px 16px; font:inherit; cursor:pointer; }
  .crop .cbtns .primary { background:var(--accent); border-color:var(--accent); color:var(--on-accent); }
  .crop .cbtns .reset { margin-right:auto; background:none; border-color:transparent; color:var(--muted); padding-left:4px; }`;
  const tag = document.createElement('style'); tag.textContent = css; document.head.append(tag);

  function loadImage(source) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = typeof source === 'string' ? source : URL.createObjectURL(source);
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error('That picture could not be opened.'));
      img.src = url;
    });
  }

  window.cropImage = async function (source) {
    let img;
    try { img = await loadImage(source); } catch (e) { alert(e.message); return null; }
    return new Promise(resolve => {
      const shade = document.createElement('div'); shade.className = 'crop-shade';
      shade.innerHTML = `<div class="crop" role="dialog" aria-modal="true" aria-label="Position the portrait">
        <h3>Position the portrait</h3>
        <p class="chint">Drag to move, zoom with the slider or the mouse wheel. The circle is what's shown in the chat.</p>
        <div class="stage"><canvas></canvas><div class="ring"></div></div>
        <div class="zoom"><span>−</span><input type="range" min="1" max="4" step="0.01" value="1" aria-label="Zoom"><span>+</span></div>
        <div class="cbtns"><button type="button" class="reset">Reset</button><button type="button" class="cancel">Cancel</button><button type="button" class="primary">Use picture</button></div>
      </div>`;
      document.body.append(shade);
      const stage = shade.querySelector('.stage'), canvas = shade.querySelector('canvas'), ctx = canvas.getContext('2d');
      const slider = shade.querySelector('input[type=range]');
      const W = img.naturalWidth, H = img.naturalHeight;
      // View state, in "stage units" (0..1 across the square): zoom 1 = picture just covers the square.
      let zoom = 1, cx = 0.5, cy = 0.5;          // which point of the picture (0..1) sits in the middle
      const scale = () => zoom / Math.min(W, H);   // stage units per picture pixel
      const clamp = () => {
        const s = scale(), halfW = 0.5 / (s * W), halfH = 0.5 / (s * H);
        cx = Math.min(1 - halfW, Math.max(halfW, cx));
        cy = Math.min(1 - halfH, Math.max(halfH, cy));
      };
      const draw = () => {
        const px = stage.clientWidth * (window.devicePixelRatio || 1);
        if (canvas.width !== px) { canvas.width = px; canvas.height = px; }
        clamp();
        const s = scale() * px;                     // canvas pixels per picture pixel
        ctx.fillStyle = '#0d0b10'; ctx.fillRect(0, 0, px, px);
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, px / 2 - cx * W * s, px / 2 - cy * H * s, W * s, H * s);
      };
      const setZoom = (z, ax = 0.5, ay = 0.5) => {   // zoom around a point of the stage (0..1)
        const before = scale();
        zoom = Math.min(4, Math.max(1, z));
        const after = scale();
        // keep the picture point under (ax, ay) where it is
        cx += (ax - 0.5) * (1 / (before * W) - 1 / (after * W));
        cy += (ay - 0.5) * (1 / (before * H) - 1 / (after * H));
        slider.value = zoom; draw();
      };

      // dragging (mouse, pen, one finger) and pinching (two fingers)
      const pts = new Map(); let pinch = null;
      stage.addEventListener('pointerdown', e => { stage.setPointerCapture(e.pointerId); pts.set(e.pointerId, {x: e.clientX, y: e.clientY}); stage.classList.add('drag'); });
      stage.addEventListener('pointermove', e => {
        if (!pts.has(e.pointerId)) return;
        const prev = pts.get(e.pointerId); pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
        const size = stage.clientWidth;
        if (pts.size === 1) {
          cx -= (e.clientX - prev.x) / size / (scale() * W);
          cy -= (e.clientY - prev.y) / size / (scale() * H);
          draw();
        } else if (pts.size === 2) {
          const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
          if (pinch) setZoom(zoom * d / pinch);
          pinch = d;
        }
      });
      const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) stage.classList.remove('drag'); };
      stage.addEventListener('pointerup', up); stage.addEventListener('pointercancel', up);
      stage.addEventListener('wheel', e => {
        e.preventDefault();
        const r = stage.getBoundingClientRect();
        setZoom(zoom * Math.exp(-e.deltaY * 0.0015), (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
      }, {passive: false});
      slider.oninput = () => setZoom(parseFloat(slider.value));

      const close = v => { document.removeEventListener('keydown', key); window.removeEventListener('resize', draw); shade.remove(); resolve(v); };
      const key = e => { if (e.key === 'Escape') close(null); };
      document.addEventListener('keydown', key); window.addEventListener('resize', draw);
      shade.querySelector('.cancel').onclick = () => close(null);
      shade.querySelector('.reset').onclick = () => { zoom = 1; cx = 0.5; cy = 0.5; slider.value = 1; draw(); };
      shade.onclick = e => { if (e.target === shade) close(null); };
      shade.querySelector('.primary').onclick = () => {
        const out = document.createElement('canvas'); out.width = out.height = 512;
        const o = out.getContext('2d'), s = scale() * 512;
        o.imageSmoothingQuality = 'high';
        o.drawImage(img, 256 - cx * W * s, 256 - cy * H * s, W * s, H * s);
        out.toBlob(b => {
          if (b && b.type === 'image/webp') return close(b);
          out.toBlob(p => close(p), 'image/png');      // browsers without WebP export
        }, 'image/webp', 0.92);
      };
      requestAnimationFrame(draw);
    });
  };
})();
