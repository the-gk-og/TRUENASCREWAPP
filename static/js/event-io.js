/*
 * event-io.js - the "Import / export" menu on the event page, plus the
 * PDF / photo gallery shown under the schedule and the run list.
 *
 *   EventIO.init({ eventId, canManage, attachments, counts })
 *   EventIO.openMenu()
 *
 * Needs sw-ui.js (SW.dialog, SW.api, SW.confirm, SW.toast, SW.esc).
 * Anything that came from a user (file names) goes in with textContent / SW.esc.
 */
(function () {
  'use strict';
  const SW = window.SW;
  const EventIO = (window.EventIO = {});

  const MAX_FILE = 15 * 1024 * 1024;
  const KINDS = {
    schedule: { label: 'Schedule', icon: 'fa-clock', where: 'under the schedule' },
    run: { label: 'Run list', icon: 'fa-list-ol', where: 'under the run list' },
  };
  let CFG = null;
  let refreshMenuFiles = () => {};

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function fmtSize(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }
  const list = (kind) => CFG.attachments[kind] || (CFG.attachments[kind] = []);

  EventIO.init = function (cfg) {
    CFG = cfg;
    CFG.attachments = CFG.attachments || { schedule: [], run: [] };
    Object.keys(KINDS).forEach(renderGallery);
  };

  // ======================================================== gallery on the page
  function tile(a, i, kind) {
    const b = el('button', 'sw-gal-tile');
    b.type = 'button';
    b.title = a.name;
    b.setAttribute('aria-label', `Open ${a.name}`);
    if (a.thumb) {
      const img = el('img'); img.src = a.thumb; img.alt = a.name; img.loading = 'lazy';
      b.appendChild(img);
    } else {
      b.classList.add('pdf');
      b.innerHTML = '<i class="fas fa-file-pdf"></i><span class="sw-gal-tname"></span>';
      b.querySelector('.sw-gal-tname').textContent = a.name;
    }
    b.addEventListener('click', () => openLightbox(kind, i));
    return b;
  }

  function renderGallery(kind) {
    const box = document.querySelector(`[data-gallery="${kind}"]`);
    if (!box) return;
    const items = list(kind);
    box.innerHTML = '';
    box.hidden = !items.length;
    if (!items.length) return;

    const head = el('div', 'sw-gal-head');
    head.innerHTML = '<i class="fas fa-paperclip"></i> ';
    head.appendChild(document.createTextNode(items.length === 1 ? 'Attached file' : `Attached files (${items.length})`));
    box.appendChild(head);

    if (items.length === 1) {                       // one file: show it, don't make people click through a gallery
      const a = items[0];
      const b = el('button', 'sw-gal-single');
      b.type = 'button';
      b.setAttribute('aria-label', `Open ${a.name}`);
      if (a.kind === 'image') {
        const img = el('img'); img.src = a.url; img.alt = a.name; img.loading = 'lazy';
        b.appendChild(img);
      } else {
        b.classList.add('pdf');
        b.innerHTML = '<i class="fas fa-file-pdf"></i><span class="sw-gal-pmain"><b></b><small></small></span><span class="btn btn-secondary btn-sm">View</span>';
        b.querySelector('b').textContent = a.name;
        b.querySelector('small').textContent = `PDF · ${fmtSize(a.size)}`;
      }
      b.addEventListener('click', () => openLightbox(kind, 0));
      box.appendChild(b);
      if (a.kind === 'image') {
        const cap = el('div', 'sw-gal-cap'); cap.textContent = `${a.name} · tap to enlarge`;
        box.appendChild(cap);
      }
      return;
    }
    const grid = el('div', 'sw-gal-grid');
    items.forEach((a, i) => grid.appendChild(tile(a, i, kind)));
    box.appendChild(grid);
  }

  // ================================================================== lightbox
  function openLightbox(kind, start) {
    let idx = start;
    let zoomed = false;
    const ov = el('div', 'sw-lb');
    ov.setAttribute('role', 'dialog');
    ov.setAttribute('aria-modal', 'true');
    ov.innerHTML =
      `<div class="sw-lb-top">
         <div class="sw-lb-title"></div>
         <div class="sw-lb-tools">
           <a class="btn btn-ghost btn-sm sw-lb-open" target="_blank" rel="noopener"><i class="fas fa-external-link-alt"></i><span>Open</span></a>
           <a class="btn btn-ghost btn-sm sw-lb-dl"><i class="fas fa-download"></i><span>Download</span></a>
           ${CFG.canManage ? '<button type="button" class="btn btn-ghost btn-sm sw-lb-del" title="Delete this file"><i class="fas fa-trash"></i><span>Delete</span></button>' : ''}
           <button type="button" class="sw-lb-close" aria-label="Close">&times;</button>
         </div>
       </div>
       <div class="sw-lb-stage"></div>
       <button type="button" class="sw-lb-nav prev" aria-label="Previous"><i class="fas fa-chevron-left"></i></button>
       <button type="button" class="sw-lb-nav next" aria-label="Next"><i class="fas fa-chevron-right"></i></button>
       <div class="sw-lb-strip" role="tablist"></div>`;
    document.body.appendChild(ov);
    document.body.classList.add('sw-noscroll');

    const $ = (s) => ov.querySelector(s);
    const stage = $('.sw-lb-stage'), strip = $('.sw-lb-strip'), title = $('.sw-lb-title');

    function close() {
      document.removeEventListener('keydown', onKey, true);
      ov.remove();
      if (!document.querySelector('.sw-overlay')) document.body.classList.remove('sw-noscroll');
    }
    function buildStrip() {
      const items = list(kind);
      strip.innerHTML = '';
      strip.hidden = items.length < 2;
      items.forEach((a, i) => {
        const b = el('button', 'sw-lb-thumb');
        b.type = 'button'; b.title = a.name; b.setAttribute('aria-label', a.name);
        if (a.thumb) { const im = el('img'); im.src = a.thumb; im.alt = ''; b.appendChild(im); }
        else b.innerHTML = '<i class="fas fa-file-pdf"></i>';
        b.addEventListener('click', () => show(i));
        strip.appendChild(b);
      });
    }
    function show(i) {
      const items = list(kind);
      if (!items.length) return close();
      idx = (i + items.length) % items.length;
      const a = items[idx];
      zoomed = false;
      title.textContent = items.length > 1 ? `${a.name}  ·  ${idx + 1} / ${items.length}` : a.name;
      $('.sw-lb-open').href = a.url;
      $('.sw-lb-dl').href = a.download;
      $('.sw-lb-dl').setAttribute('download', a.name);
      stage.innerHTML = '';
      stage.classList.remove('zoomed');
      if (a.kind === 'image') {
        const img = el('img', 'sw-lb-img'); img.src = a.url; img.alt = a.name; img.draggable = false;
        img.addEventListener('click', () => {
          zoomed = !zoomed;
          stage.classList.toggle('zoomed', zoomed);
        });
        stage.appendChild(img);
      } else {
        const f = el('iframe', 'sw-lb-pdf'); f.src = a.url; f.title = a.name;
        stage.appendChild(f);
      }
      ov.querySelectorAll('.sw-lb-nav').forEach((n) => { n.hidden = items.length < 2; });
      [...strip.children].forEach((c, n) => {
        c.classList.toggle('on', n === idx);
        if (n === idx && c.scrollIntoView) c.scrollIntoView({ inline: 'center', block: 'nearest' });
      });
    }
    function onKey(e) {
      if (document.querySelector('.sw-overlay')) return;          // a confirm dialog is open on top: leave keys to it
      if (e.key === 'Escape') { e.preventDefault(); close(); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); show(idx - 1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); show(idx + 1); }
    }
    document.addEventListener('keydown', onKey, true);

    $('.sw-lb-close').addEventListener('click', close);
    $('.sw-lb-nav.prev').addEventListener('click', () => show(idx - 1));
    $('.sw-lb-nav.next').addEventListener('click', () => show(idx + 1));
    ov.addEventListener('click', (e) => { if (e.target === stage) close(); });

    let sx = 0, sy = 0;                                             // swipe between files
    stage.addEventListener('touchstart', (e) => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
    stage.addEventListener('touchend', (e) => {
      if (zoomed || list(kind).length < 2) return;
      const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
      if (Math.abs(dx) > 50 && Math.abs(dy) < 60) show(idx + (dx < 0 ? 1 : -1));
    }, { passive: true });

    const del = $('.sw-lb-del');
    if (del) {
      del.addEventListener('click', async () => {
        const a = list(kind)[idx];
        const sure = await SW.confirm(`Delete "${a.name}"?`, { danger: true, okText: 'Delete' });
        document.body.classList.add('sw-noscroll');                // closing the confirm dialog clears this
        if (!sure) return;
        if (!(await SW.run(() => SW.api('DELETE', `/events/attachments/${a.id}`)))) return;
        removeLocal(kind, a.id);
        SW.toast('File deleted');
        buildStrip();
        show(Math.min(idx, list(kind).length - 1));
      });
    }
    buildStrip();
    show(idx);
    $('.sw-lb-close').focus();
  }

  function removeLocal(kind, id) {
    CFG.attachments[kind] = list(kind).filter((x) => x.id !== id);
    renderGallery(kind);
    refreshMenuFiles();
  }

  // ===================================================================== menu
  async function postForm(url, fd) {
    let res;
    try {
      res = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' } });
    } catch (e) {
      const err = new Error('Network error - check your connection and try again'); throw err;
    }
    if (res.status === 413) throw new Error('That file is too big to upload (max 15 MB each)');
    if (!(res.headers.get('content-type') || '').includes('json')) {
      throw new Error(res.ok ? 'Your session has expired - please log in again' : `Request failed (${res.status})`);
    }
    const payload = await res.json();
    if (!res.ok || payload.error) {
      const err = new Error(payload.error || `Request failed (${res.status})`);
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  function linkBtn(href, icon, text, disabled) {
    const a = el('a', 'btn btn-secondary btn-sm' + (disabled ? ' disabled' : ''));
    a.innerHTML = `<i class="fas ${icon}"></i>`;
    a.appendChild(document.createTextNode(text));
    if (disabled) { a.setAttribute('aria-disabled', 'true'); a.title = 'Nothing to export yet'; }
    else { a.href = href; }
    return a;
  }

  function showProblems(box, err) {
    box.innerHTML = '';
    box.hidden = false;
    box.className = 'sw-io-result bad';
    const p = el('div'); p.textContent = err.message; box.appendChild(p);
    const probs = (err.payload && err.payload.problems) || [];
    if (probs.length) {
      const ul = el('ul', 'sw-problems');
      probs.forEach((x) => {
        const li = el('li'); const b = el('b'); b.textContent = `Row ${x.row}: `;
        li.append(b, document.createTextNode(x.message)); ul.appendChild(li);
      });
      if (err.payload.more) { const li = el('li'); li.textContent = `…and ${err.payload.more} more`; ul.appendChild(li); }
      box.appendChild(ul);
    }
  }

  function buildPanel(kind) {
    const K = KINDS[kind];
    const base = `/events/${CFG.eventId}/io`;
    const n = CFG.counts[kind] || 0;
    const panel = el('div', 'sw-io-panel');

    // ---- spreadsheet
    const sheet = el('section', 'sw-io-sec');
    sheet.innerHTML = '<h3><i class="fas fa-file-excel"></i> Spreadsheet (Excel or CSV)</h3>';
    const rowT = el('div', 'sw-io-row');
    rowT.innerHTML = '<span class="sw-io-label">Blank template</span>';
    const bt = el('span', 'sw-io-btns');
    bt.append(linkBtn(`${base}/template/${kind}.xlsx`, 'fa-download', 'Excel'), linkBtn(`${base}/template/${kind}.csv`, 'fa-download', 'CSV'));
    rowT.appendChild(bt); sheet.appendChild(rowT);

    const rowE = el('div', 'sw-io-row');
    rowE.innerHTML = `<span class="sw-io-label">Export what's here now (${n})</span>`;
    const be = el('span', 'sw-io-btns');
    be.append(linkBtn(`${base}/export/${kind}.xlsx`, 'fa-file-export', 'Excel', !n), linkBtn(`${base}/export/${kind}.csv`, 'fa-file-export', 'CSV', !n));
    rowE.appendChild(be); sheet.appendChild(rowE);

    if (CFG.canManage) {
      const imp = el('div', 'sw-io-import');
      const uid = 'io' + kind + Math.random().toString(36).slice(2, 6);
      imp.innerHTML =
        `<div class="sw-io-label">Import</div>
         <input type="file" class="sw-io-file" accept=".xlsx,.xlsm,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" aria-label="Spreadsheet to import">
         <div class="sw-io-modes">
           <label><input type="radio" name="${uid}" value="append" checked> Add to what's here</label>
           <label><input type="radio" name="${uid}" value="replace"> Replace all ${n ? `${n} existing` : 'existing'}</label>
         </div>
         <button type="button" class="btn btn-primary btn-sm sw-io-go" disabled><i class="fas fa-file-import"></i>Import</button>
         <div class="sw-io-result" hidden></div>`;
      const file = imp.querySelector('.sw-io-file'), go = imp.querySelector('.sw-io-go'), result = imp.querySelector('.sw-io-result');
      file.addEventListener('change', () => { go.disabled = !file.files.length; result.hidden = true; });
      go.addEventListener('click', async () => {
        const f = file.files[0];
        if (!f) return;
        const mode = imp.querySelector('input[type=radio]:checked').value;
        if (mode === 'replace' && n && !(await SW.confirm(
          `Replace all ${n} existing ${K.label.toLowerCase()} ${n === 1 ? 'item' : 'items'} with the contents of this file?\nThis can't be undone.`,
          { danger: true, okText: 'Replace' }))) return;
        const fd = new FormData(); fd.append('file', f); fd.append('mode', mode);
        go.disabled = true;
        const label = go.innerHTML; go.innerHTML = '<i class="fas fa-spinner fa-spin"></i>Importing…';
        try {
          const r = await postForm(`${base}/import/${kind}`, fd);
          result.hidden = false; result.className = 'sw-io-result ok';
          result.textContent = `Imported ${r.imported} ${r.imported === 1 ? 'item' : 'items'}.`;
          SW.toast(`${r.imported} ${K.label.toLowerCase()} ${r.imported === 1 ? 'item' : 'items'} imported`);
          SW.reloadSoon();
        } catch (e) {
          showProblems(result, e);
          go.disabled = false;
        } finally { go.innerHTML = label; }
      });
      sheet.appendChild(imp);
      const hint = el('p', 'sw-hint');
      hint.textContent = 'Import is all-or-nothing: if any row has a problem nothing changes and the problems are listed. Rows marked "(example)" are ignored.';
      sheet.appendChild(hint);
    }
    panel.appendChild(sheet);

    // ---- PDF / photos (admins)
    if (CFG.canManage) {
      const files = el('section', 'sw-io-sec');
      files.innerHTML =
        `<h3><i class="fas fa-paperclip"></i> PDF &amp; photos</h3>
         <p class="sw-hint">Shown on the event ${K.where}. JPG, PNG, WebP or PDF, up to 15 MB each. Pick as many as you like - with more than one they appear as a gallery.</p>
         <label class="btn btn-secondary btn-sm sw-file-btn"><i class="fas fa-upload"></i>Choose files
           <input type="file" multiple hidden accept="application/pdf,.pdf,image/jpeg,image/png,image/webp"></label>
         <div class="sw-up-list" aria-live="polite"></div>
         <div class="sw-io-files"></div>`;
      const input = files.querySelector('input[type=file]');
      const upList = files.querySelector('.sw-up-list');
      const existing = files.querySelector('.sw-io-files');

      const paintExisting = () => {
        existing.innerHTML = '';
        const items = list(kind);
        if (!items.length) return;
        const h = el('div', 'sw-io-label'); h.textContent = `Attached (${items.length})`; existing.appendChild(h);
        items.forEach((a) => {
          const row = el('div', 'sw-io-file-row');
          const th = el('span', 'sw-io-thumb');
          if (a.thumb) { const im = el('img'); im.src = a.thumb; im.alt = ''; th.appendChild(im); } else th.innerHTML = '<i class="fas fa-file-pdf"></i>';
          const nm = el('span', 'sw-io-fname'); nm.textContent = a.name;
          const sz = el('small'); sz.textContent = fmtSize(a.size); nm.appendChild(sz);
          const d = el('button', 'btn btn-ghost btn-icon'); d.type = 'button'; d.title = 'Delete'; d.setAttribute('aria-label', `Delete ${a.name}`);
          d.innerHTML = '<i class="fas fa-trash"></i>';
          d.addEventListener('click', async () => {
            if (!(await SW.confirm(`Delete "${a.name}"?`, { danger: true, okText: 'Delete' }))) return;
            if (await SW.run(() => SW.api('DELETE', `/events/attachments/${a.id}`))) { removeLocal(kind, a.id); SW.toast('File deleted'); }
          });
          row.append(th, nm, d); existing.appendChild(row);
        });
      };
      panel.paint = paintExisting;
      paintExisting();

      input.addEventListener('change', async () => {
        const picked = [...input.files];
        input.value = '';
        if (!picked.length) return;
        upList.innerHTML = '';
        let ok = 0;
        for (const f of picked) {
          const row = el('div', 'sw-up-row');
          row.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span></span>';
          row.querySelector('span').textContent = f.name;
          upList.appendChild(row);
          const fail = (msg) => {
            row.className = 'sw-up-row bad';
            row.innerHTML = '<i class="fas fa-exclamation-circle"></i><span></span>';
            row.querySelector('span').textContent = `${f.name} - ${msg}`;
          };
          if (f.size > MAX_FILE) { fail(`too big (${fmtSize(f.size)}, max 15 MB)`); continue; }
          const fd = new FormData(); fd.append('target', kind); fd.append('files', f);
          try {
            const r = await postForm(`/events/${CFG.eventId}/attachments`, fd);
            r.added.forEach((a) => list(kind).push(a));
            if (r.errors && r.errors.length) { fail(r.errors[0].error); continue; }
            ok += r.added.length;
            row.className = 'sw-up-row ok';
            row.innerHTML = '<i class="fas fa-check-circle"></i><span></span>';
            row.querySelector('span').textContent = f.name;
            renderGallery(kind); paintExisting();
          } catch (e) { fail(e.message); }
        }
        if (ok) SW.toast(`${ok} ${ok === 1 ? 'file' : 'files'} uploaded`);
      });
      panel.appendChild(files);
    }
    return panel;
  }

  EventIO.openMenu = function () {
    const d = SW.dialog({ title: 'Import / export', wide: true, onClose: () => { refreshMenuFiles = () => {}; } });
    const kinds = Object.keys(KINDS);
    const panels = {};
    const tabs = el('div', 'sw-io-tabs'); tabs.setAttribute('role', 'tablist');
    const body = el('div', 'sw-io-body');
    kinds.forEach((k) => {
      const t = el('button', 'sw-io-tab'); t.type = 'button'; t.setAttribute('role', 'tab'); t.dataset.kind = k;
      t.innerHTML = `<i class="fas ${KINDS[k].icon}"></i> ${KINDS[k].label}`;
      t.addEventListener('click', () => select(k));
      tabs.appendChild(t);
      panels[k] = buildPanel(k);
      body.appendChild(panels[k]);
    });
    function select(k) {
      kinds.forEach((x) => {
        panels[x].hidden = x !== k;
        tabs.querySelector(`[data-kind="${x}"]`).classList.toggle('on', x === k);
        tabs.querySelector(`[data-kind="${x}"]`).setAttribute('aria-selected', String(x === k));
      });
    }
    refreshMenuFiles = () => kinds.forEach((k) => panels[k].paint && panels[k].paint());
    d.body.append(tabs, body);
    select('schedule');
  };
})();
