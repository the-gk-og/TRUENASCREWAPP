/*
 * sw-shell.js - the app shell (top bar) and gear dialogs shared by every page.
 *
 *   SWGear.scan()                         camera / typed code -> what is it, with actions
 *   SWGear.quarantine(unit)               report a problem: takes the item out of use -> Promise<quarantine | null> (any crew)
 *   SWGear.release(unit, quarantine)      -> Promise<result | null>       (admins)
 *   SWGear.history(unitId, {isAdmin})     one timeline of everything that happened to an item
 *   SWGear.labels({equipmentIds, unitIds, hasItems, name})   print group / item labels (admins)
 *
 * Needs sw-ui.js (SW.api, SW.form, SW.dialog, SW.toast). `unit` is {id, asset_tag, equipment_name?}.
 */
(function () {
  'use strict';
  const SW = window.SW;
  const esc = SW.esc;
  const $ = (s, r) => (r || document).querySelector(s);

  // ------------------------------------------------------------ user menu
  const userBtn = $('#swUserBtn'), userMenu = $('#swUserMenu');
  if (userBtn && userMenu) {
    const setOpen = (on) => { userMenu.classList.toggle('open', on); userBtn.setAttribute('aria-expanded', on ? 'true' : 'false'); };
    userBtn.addEventListener('click', (e) => { e.stopPropagation(); setOpen(!userMenu.classList.contains('open')); });
    document.addEventListener('click', (e) => { if (!userMenu.contains(e.target)) setOpen(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); });
  }

  // --------------------------------------------------------------- search
  const input = $('#swSearchInput'), box = $('#swSearchResults');
  if (input && box) {
    let timer = 0, seq = 0, hits = [], on = -1;
    const close = () => { box.hidden = true; on = -1; };
    const paint = () => box.querySelectorAll('.sw-gs-hit').forEach((a, i) => a.classList.toggle('on', i === on));
    const show = (groups, q) => {
      hits = [];
      if (!groups.length) {
        box.innerHTML = `<div class="sw-gs-empty">Nothing matches “${esc(q)}”.</div>`;
      } else {
        box.innerHTML = groups.map((g) => `<div class="sw-gs-group">${esc(g.label)}</div>` + g.hits.map((h) => {
          hits.push(h);
          return `<a class="sw-gs-hit" href="${esc(h.url)}"><span>${esc(h.title)}</span><small>${esc(h.meta || '')}</small></a>`;
        }).join('')).join('');
      }
      on = -1; box.hidden = false;
    };
    const run = async () => {
      const q = input.value.trim();
      if (q.length < 2) return close();
      const mine = ++seq;
      try {
        const r = await SW.api('GET', '/api/search?q=' + encodeURIComponent(q));
        if (mine === seq) show(r.groups || [], q);
      } catch (e) { if (mine === seq) close(); }
    };
    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 180); });
    input.addEventListener('focus', () => { if (input.value.trim().length >= 2) run(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { close(); input.blur(); return; }
      if (box.hidden || !hits.length) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); on = (on + 1) % hits.length; paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); on = (on - 1 + hits.length) % hits.length; paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); location.href = hits[Math.max(on, 0)].url; }
    });
    document.addEventListener('click', (e) => { if (!$('#swSearch').contains(e.target)) close(); });
    document.addEventListener('keydown', (e) => {
      // "/" jumps to search, unless you're typing somewhere
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
      e.preventDefault(); input.focus();
    });
  }

  // ================================================================ gear
  const Gear = (window.SWGear = {});
  const pill = (state, label) => `<span class="pill ${esc(state)}">${esc(label)}</span>`;
  Gear.pill = pill;

  async function postForm(url, fd) {
    let res;
    try { res = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { Accept: 'application/json' } }); }
    catch (e) { throw new Error('Network error - check your connection and try again'); }
    let data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  /** Phone photos are huge: shrink before upload. */
  async function shrink(file) {
    if (!file || !/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 1.2 * 1024 * 1024) return file;
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
      const s = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
      const c = document.createElement('canvas');
      c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.85));
      return blob ? new File([blob], 'photo.jpg', { type: 'image/jpeg' }) : file;
    } catch (e) { return file; }
  }
  Gear.shrink = shrink;

  // ------------------------------------------------- report a problem
  // No typing needed: tap what's wrong, optionally add a note or photo. The item is
  // taken out of use until an admin has looked at it.
  const PROBLEMS = [
    ['Broken or damaged', 'hammer', 'damaged'], ['Parts missing', 'puzzle-piece', 'missing_parts'],
    ['Won’t turn on', 'power-off', 'no_power'], ['Something else', 'ellipsis', 'other'],
  ];
  const SEVERITIES = [['minor', 'Minor'], ['major', 'Not usable'], ['unsafe', 'Unsafe']];
  Gear.quarantine = function (unit, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      let result = null, picked = null, sending = false, severity = 'major', shots = [];
      const d = SW.dialog({ title: `Problem with ${unit.asset_tag}`, onClose: () => resolve(result) });
      d.body.innerHTML = `
        <p class="sw-confirm-text">${unit.equipment_name ? esc(unit.equipment_name) + '. ' : ''}What’s wrong with it?</p>
        <div class="sw-problem-grid">${PROBLEMS.map(([label, icon], i) =>
          `<button type="button" class="sw-problem" data-i="${i}" aria-pressed="false"><i class="fas fa-${icon}"></i><span>${esc(label)}</span></button>`).join('')}</div>
        <div class="sw-field"><label class="sw-label" for="swProbNote">Anything to add? <span class="sw-muted" id="swProbOpt">(optional)</span></label>
          <textarea id="swProbNote" rows="2" class="sw-input" placeholder="e.g. cuts out when the cable is moved">${esc(opts.reason || '')}</textarea></div>
        <div class="sw-field"><span class="sw-label">How bad?</span>
          <div class="sw-seg sw-sev">${SEVERITIES.map(([v, l]) => `<button type="button" data-sev="${v}" aria-pressed="${v === 'major'}">${l}</button>`).join('')}</div></div>
        <div class="sw-field"><label class="btn btn-secondary sw-problem-photo"><i class="fas fa-camera"></i> <span>Add photos</span>
          <input type="file" accept="image/*" capture="environment" multiple class="sr-only"></label></div>
        <p class="sw-hint" style="margin-bottom:.9rem">It will be taken out of use until someone has checked it.</p>
        <div class="sw-error" hidden></div>
        <div class="sw-actions">
          <button type="button" class="btn btn-secondary" data-cancel>Cancel</button>
          <button type="button" class="btn btn-danger" data-send>Take it out of use</button>
        </div>`;
      const note = $('#swProbNote', d.body), file = $('input[type=file]', d.body), err = $('.sw-error', d.body), send = $('[data-send]', d.body);
      d.body.querySelectorAll('.sw-problem').forEach((b) => b.addEventListener('click', () => {
        picked = PROBLEMS[b.dataset.i][0];
        d.body.querySelectorAll('.sw-problem').forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
        $('#swProbOpt', d.body).textContent = picked === 'Something else' ? '(please say what)' : '(optional)';
        err.hidden = true;
      }));
      d.body.querySelectorAll('[data-sev]').forEach((b) => b.addEventListener('click', () => {
        severity = b.dataset.sev;
        d.body.querySelectorAll('[data-sev]').forEach((x) => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
      }));
      file.addEventListener('change', () => {
        shots = shots.concat(Array.from(file.files)).slice(0, 6);     // each camera shot adds one
        file.value = '';
        $('.sw-problem-photo span', d.body).textContent = shots.length ? `${shots.length} photo${shots.length > 1 ? 's' : ''} · add more` : 'Add photos';
      });
      $('[data-cancel]', d.body).onclick = () => d.close();
      send.onclick = async () => {
        if (sending) return;
        const extra = note.value.trim();
        const fail = (m) => { err.textContent = m; err.hidden = false; };
        if (!picked && !extra) return fail('Tap what’s wrong with it');
        if (picked === 'Something else' && !extra) return fail('Say what’s wrong with it');
        const cat = picked ? PROBLEMS.find((p) => p[0] === picked)[2] : '';
        sending = true; send.disabled = true; send.textContent = 'Saving…';
        try {
          if (opts.before) await opts.before();
          const fd = new FormData();
          fd.append('summary', extra);
          if (cat) fd.append('category', cat);
          fd.append('severity', severity);
          for (const f of shots) fd.append('photos', await shrink(f));
          if (opts.eventId) fd.append('event_id', opts.eventId);
          result = (await postForm(`/equipment/unit/${unit.id}/fault`, fd)).quarantine;
          SW.toast(`${unit.asset_tag} taken out of use`);
          d.close();
        } catch (e) { sending = false; send.disabled = false; send.textContent = 'Take it out of use'; fail(e.message); }
      };
    });
  };

  Gear.release = function (unit, q) {
    q = q || {};
    const why = q.reason ? `Taken out of use${q.quarantined_at ? ' ' + q.quarantined_at : ''}${q.quarantined_by ? ' by ' + q.quarantined_by : ''}: ${q.reason}` : '';
    return SW.form({
      title: `${unit.asset_tag}: checked?`,
      submitText: 'Save',
      fields: [
        ...(why ? [{ type: 'info', text: why }] : []),
        { name: 'outcome', label: 'What happens to it?', type: 'select', value: 'available', options: [
          { value: 'available', label: 'It’s fine: put it back in use' },
          { value: 'repair', label: 'Send for repair (stays out of use)' },
          { value: 'retired', label: 'Retire it (beyond repair)' },
        ] },
        { name: 'kind', label: 'Cleared by', type: 'select', value: 'inspection', half: true, show: (v) => v.outcome === 'available', options: [
          { value: 'inspection', label: 'Inspection' }, { value: 'repair', label: 'Repair' }, { value: 'pat', label: 'PAT test' },
        ] },
        { name: 'next_due', label: 'Next check due (optional)', type: 'date', half: true, show: (v) => v.outcome === 'available' },
        { name: 'note', label: 'What was checked or fixed?', type: 'textarea', rows: 3,
          hint: 'Needed to put it back in use. Saved to the item’s history.' },
      ],
      onSubmit: async (v) => {
        if (v.outcome === 'available' && !(v.note || '').trim()) throw new Error('Say what was checked or fixed');
        const r = await SW.api('POST', `/equipment/unit/${unit.id}/release`, v);
        SW.toast(`${unit.asset_tag}: ${r.quarantine.outcome_label.toLowerCase()}`);
        return r;
      },
    });
  };

  // -------------------------------------------------------------- history
  const ICONS = { out: 'arrow-right-from-bracket', return: 'arrow-right-to-bracket', maintenance: 'screwdriver-wrench',
                  quarantine: 'triangle-exclamation', fault: 'triangle-exclamation', release: 'circle-check', created: 'plus' };
  Gear.history = async function (unitId, opts) {
    opts = opts || {};
    const d = SW.dialog({ title: 'History', wide: true });
    d.body.innerHTML = '<p class="sw-muted">Loading…</p>';
    const load = async () => {
      let h;
      try { h = await SW.api('GET', `/equipment/unit/${unitId}/history`); }
      catch (e) { d.body.innerHTML = `<p class="sw-error">${esc(e.message)}</p>`; return; }
      d.setTitle(`History: ${h.unit.asset_tag}`);
      const due = h.maintenance_due;
      const rows = h.timeline.map((t) => `<li class="sw-hist-item ${esc(t.kind)}">
          <span class="sw-hist-dot"><i class="fas fa-${ICONS[t.kind] || 'circle'}"></i></span>
          <div class="sw-hist-body">
            <div class="sw-hist-title">${t.severity ? pill(t.severity === 'minor' ? 'warn' : 'bad', t.severity === 'unsafe' ? 'Unsafe' : t.severity === 'minor' ? 'Minor' : 'Not usable') + ' ' : ''}${esc(t.title)}
              ${opts.isAdmin && t.maintenance_id ? `<button type="button" class="btn-link sw-hist-del" data-del="${t.maintenance_id}">Delete</button>` : ''}</div>
            <div class="sw-hist-meta">${esc(t.when)}${t.by ? ' · ' + esc(t.by) : ''}${t.event_title ? ' · after ' + esc(t.event_title) : ''}</div>
            ${t.detail ? `<div class="sw-hist-detail">${esc(t.detail)}</div>` : ''}
            ${(t.photos || []).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener"><img class="sw-hist-photo" src="${esc(u)}" alt="Photo of the fault"></a>`).join('')}
            ${t.photo_url ? `<a href="${esc(t.photo_url)}" target="_blank" rel="noopener"><img class="sw-hist-photo" src="${esc(t.photo_url)}" alt="Photo of the damage"></a>` : ''}
          </div></li>`).join('');
      d.body.innerHTML = (due ? `<p style="margin-bottom:.75rem">${pill(due.state, `Next ${due.kind_label}: ${due.date_text}${due.state === 'overdue' ? ' (overdue)' : ''}`)}</p>` : '')
        + `<ul class="sw-hist">${rows}</ul>`;
      d.body.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
        if (!await SW.confirm('Delete this maintenance record?', { danger: true, okText: 'Delete' })) return;
        try { await SW.api('DELETE', `/equipment/maintenance/${b.dataset.del}`); load(); }
        catch (e) { SW.toast(e.message, 'error'); }
      }));
    };
    load();
  };

  // --------------------------------------------------------------- labels
  const SIZES = { 'portrait-s': ['portrait', 60, 80], 'portrait-m': ['portrait', 75, 100],
                  'landscape-s': ['landscape', 90, 55], 'landscape-m': ['landscape', 110, 65] };
  Gear.labels = function (o) {
    const nTypes = (o.equipmentIds || []).length, nUnits = (o.unitIds || []).length;
    const what = o.name || (nUnits ? `${nUnits} item${nUnits === 1 ? '' : 's'}` : `${nTypes} type${nTypes === 1 ? '' : 's'}`);
    const kinds = [];
    if (!nUnits) kinds.push({ value: 'group', label: 'Group labels: one per type, for the case or shelf' });
    if (o.hasItems || nUnits) {
      kinds.push({ value: 'unit', label: 'Item labels: one for each individual item' });
      kinds.push({ value: 'both', label: 'Both: the group label, then every item' });
    }
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('showwise-labels') || '{}'); } catch (e) {}
    return SW.form({
      title: `Print labels: ${what}`,
      submitText: 'Download PDF',
      fields: [
        { name: 'mode', label: 'Which labels?', type: 'select', options: kinds,
          value: kinds.some((k) => k.value === (o.mode || saved.mode)) ? (o.mode || saved.mode) : kinds[0].value },
        ...(o.hasItems || nUnits ? [] : [{ type: 'info', text: 'These types are only counted, so they have a group label but no item labels.' }]),
        { name: 'size', label: 'Label size', type: 'select', value: saved.size || 'portrait-s', options: [
          { value: 'portrait-s', label: 'Portrait small (60 × 80 mm)' }, { value: 'portrait-m', label: 'Portrait medium (75 × 100 mm)' },
          { value: 'landscape-s', label: 'Landscape small (90 × 55 mm)' }, { value: 'landscape-m', label: 'Landscape medium (110 × 65 mm)' },
          { value: 'custom', label: 'Custom size…' },
        ] },
        { name: 'layout', label: 'Layout', type: 'select', value: saved.layout || 'portrait', show: (v) => v.size === 'custom',
          options: [{ value: 'portrait', label: 'Portrait (QR under the name)' }, { value: 'landscape', label: 'Landscape (QR beside the name)' }] },
        { name: 'w', label: 'Width (mm)', type: 'number', min: 30, max: 200, half: true, value: saved.w || 60, show: (v) => v.size === 'custom' },
        { name: 'h', label: 'Height (mm)', type: 'number', min: 30, max: 280, half: true, value: saved.h || 80, show: (v) => v.size === 'custom' },
        { type: 'info', text: 'Prints on A4. Each label has a QR code that opens the item when scanned.' },
      ],
      onSubmit: async (v) => {
        const [layout, w, h] = v.size === 'custom' ? [v.layout, v.w, v.h] : SIZES[v.size];
        if (!(w >= 30 && w <= 200 && h >= 30 && h <= 280)) throw new Error('Width must be 30–200 mm and height 30–280 mm');
        try { localStorage.setItem('showwise-labels', JSON.stringify({ mode: v.mode, size: v.size, layout: v.layout, w: v.w, h: v.h })); } catch (e) {}
        const res = await fetch('/equipment/generate-qrcodes', {
          method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode: v.mode, layout, card_width_mm: w, card_height_mm: h,
                                 equipment_ids: o.equipmentIds || [], unit_ids: o.unitIds || [], base_url: location.origin }),
        });
        if (!res.ok) {
          let msg = `Could not make the labels (${res.status})`;
          try { msg = (await res.json()).error || msg; } catch (e) {}
          throw new Error(msg);
        }
        const a = document.createElement('a');
        a.href = URL.createObjectURL(await res.blob());
        a.download = `labels_${new Date().toISOString().slice(0, 10)}.pdf`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 2000);
        SW.toast('Labels downloaded');
        return true;
      },
    });
  };

  // ----------------------------------------------------------------- scan
  const loaded = {};
  function loadScript(src) {
    if (!loaded[src]) {
      loaded[src] = new Promise((resolve) => {
        const s = document.createElement('script');
        s.src = src; s.onload = resolve; s.onerror = resolve;      // a missing decoder just means that code type won't read
        document.head.appendChild(s);
      });
    }
    return loaded[src];
  }
  Gear.loadScanner = async function () {
    const jobs = [];
    if (typeof jsQR !== 'function') jobs.push(loadScript('https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js'));
    if (typeof Quagga === 'undefined') jobs.push(loadScript('https://cdn.jsdelivr.net/npm/@ericblade/quagga2@1.8.4/dist/quagga.min.js'));
    if (!window.SWScanner) jobs.push(loadScript((document.documentElement.dataset.scanner) || '/static/js/sw-scanner.js'));
    await Promise.all(jobs);
    return window.SWScanner;
  };

  /** Camera box + status line + typed-code row inside `host`. Returns {start, stop, scanner}. */
  Gear.scannerUI = async function (host, opts) {
    host.innerHTML = `
      <div class="sw-cam"><div class="sw-cam-idle"><i class="fas fa-camera"></i><span>Camera is off</span></div><div class="sw-cam-frame"></div></div>
      <div class="sw-cam-row">
        <span class="sw-cam-status"><span class="sw-dot"></span><span class="txt">Camera off</span></span>
        <button type="button" class="btn btn-secondary btn-sm sw-cam-toggle">Start camera</button>
      </div>
      <form class="sw-cam-manual">
        <input type="text" class="sw-input" placeholder="${esc(opts.placeholder || 'Or type the code on the label')}" autocomplete="off" spellcheck="false" enterkeyhint="go" aria-label="Type a code">
        <button type="submit" class="btn btn-secondary">Find</button>
      </form>`;
    const cam = $('.sw-cam', host), dot = $('.sw-dot', host), txt = $('.txt', host), toggle = $('.sw-cam-toggle', host);
    const manual = $('.sw-cam-manual input', host);
    const SWScanner = await Gear.loadScanner();
    let scanner = null;
    const paintBtn = () => { toggle.textContent = scanner && scanner.scanning ? 'Stop camera' : 'Start camera'; };
    if (SWScanner) {
      scanner = SWScanner.create({
        container: cam, continuous: !!opts.continuous,
        isOpen: () => document.body.contains(host),
        onCode: (code) => opts.onCode(code),
        onState: (live, text) => {
          dot.classList.toggle('live', live); txt.textContent = text; cam.classList.toggle('live', live);
          $('.sw-cam-idle', host).style.display = scanner && scanner.scanning ? 'none' : '';
          paintBtn();
        },
        onError: (msg) => { if (!opts.quiet) SW.toast(msg, 'error'); },      // the status line already says it
      });
    } else { txt.textContent = 'Scanner could not load - type the code instead'; toggle.hidden = true; }
    const api = {
      scanner,
      start: () => scanner && scanner.start(),
      stop: () => scanner && scanner.stop(),
      status: (text) => { txt.textContent = text; },
    };
    toggle.addEventListener('click', () => { if (scanner.scanning) api.stop(); else api.start(); });
    $('.sw-cam-manual', host).addEventListener('submit', (e) => {
      e.preventDefault();
      const code = manual.value.trim();
      if (!code) return;
      if (!opts.continuous) api.stop();
      manual.value = '';
      opts.onCode(code);
    });
    return api;
  };

  Gear.scan = async function () {
    let ui = null;
    const d = SW.dialog({ title: 'Scan a label', onClose: () => ui && ui.stop() });
    const camHost = document.createElement('div'), out = document.createElement('div');
    out.setAttribute('aria-live', 'polite');
    // Switch between looking an item up (here) and checking gear out or in (the Scan gear page)
    const seg = document.createElement('div');
    seg.className = 'sw-seg sw-scan-what';
    seg.innerHTML = '<button type="button" aria-pressed="true"><i class="fas fa-magnifying-glass"></i> Look it up</button>'
      + '<a href="/equipment/checkout"><i class="fas fa-right-left"></i> Check out / in</a>';
    d.body.append(seg, camHost, out);

    const again = () => { out.innerHTML = ''; ui.start(); };
    const lookup = async (code) => {
      out.innerHTML = '<p class="sw-muted" style="margin-top:.9rem">Looking up…</p>';
      let r;
      try { r = await SW.api('POST', '/api/scan', { code }); }
      catch (e) {
        out.innerHTML = `<div class="sw-scan-result"><strong>Not found</strong><p class="sw-muted">${esc(e.message)}</p>
          <div class="sw-actions"><button type="button" class="btn btn-secondary" data-again>Scan again</button></div></div>`;
        $('[data-again]', out).onclick = again;
        return;
      }
      const eq = r.equipment, u = r.unit, s = eq.summary;
      const counts = eq.tracking === 'individual'
        ? `${s.available} of ${s.owned} available${s.out ? ` · ${s.out} out` : ''}${s.quarantined ? ` · ${s.quarantined} out of use` : ''}`
        : `${s.available} of ${s.owned} in storage${s.out ? ` · ${s.out} out` : ''}`;
      const co = u && u.checkout;
      const where = !u ? '' : u.quarantine ? `Out of use since ${esc(u.quarantine.quarantined_at)}` : co ? `Out on ${esc(co.event_title)} since ${esc(co.checked_out_at)}`
        : (u.allocations && u.allocations.length ? `Booked for ${esc(u.allocations[0].event_title)}` : 'In storage');
      const canQuarantine = u && !['retired', 'lost'].includes(u.status);
      out.innerHTML = `<div class="sw-scan-result">
          ${eq.picture_url ? `<img class="thumb" src="${esc(eq.picture_url)}" alt="">` : ''}
          <div class="main">
            <strong>${esc(eq.name)}</strong>
            ${u ? `<div><code>${esc(u.asset_tag)}</code> ${pill(u.state, u.state_label)}</div>` : `<div class="sw-muted">Group label</div>`}
            ${u && u.quarantine ? `<div class="sw-scan-why">${esc(u.quarantine.reason)}</div>` : ''}
            <dl>
              ${u ? `<dt>Where</dt><dd>${where}</dd>` : ''}
              <dt>Lives in</dt><dd>${esc(eq.location || 'No location set')}</dd>
              <dt>Stock</dt><dd>${counts}</dd>
              ${u && u.maintenance_due && u.maintenance_due.state !== 'ok' ? `<dt>${esc(u.maintenance_due.kind_label)}</dt><dd>${u.maintenance_due.state === 'overdue' ? 'Overdue since' : 'Due'} ${esc(u.maintenance_due.date_text)}</dd>` : ''}
            </dl>
          </div>
          <div class="sw-actions">
            ${canQuarantine ? `<a class="btn btn-outline-danger sw-left" href="${esc(r.fault_url)}"><i class="fas fa-triangle-exclamation"></i> Report a fault</a>` : ''}
            <button type="button" class="btn btn-secondary" data-again>Scan again</button>
            <a class="btn btn-primary" href="${esc(r.url)}">Open</a>
          </div></div>`;
      $('[data-again]', out).onclick = again;
    };
    ui = await Gear.scannerUI(camHost, { onCode: lookup });
    ui.start();
  };

  // ------------------------------------------- works with bad wifi
  // 1. The service worker keeps the event-day pages so they open with no connection.
  // 2. A bar says so when the device is offline.
  // 3. Scans queued on the Scan gear page are sent from whatever page is open once the
  //    connection is back (the Scan gear page sends its own, and shows any that failed).
  const QKEY = 'showwise-scan-queue';
  const readQueue = () => { try { return JSON.parse(localStorage.getItem(QKEY) || '[]'); } catch (e) { return []; } };
  const offlineBar = $('#swOffline');
  let reachable = navigator.onLine;       // navigator.onLine says "has wifi", not "can reach ShowWise": ask the server
  async function checkConnection() {
    const was = reachable;
    try { await fetch('/sw.js', { method: 'HEAD', cache: 'no-store' }); reachable = true; }
    catch (e) { reachable = false; }
    paintOffline();
    if (reachable && !was) sendQueuedScans();
  }
  function paintOffline() {
    if (!offlineBar) return;
    offlineBar.hidden = reachable;
    const n = readQueue().length;
    $('#swOfflineQueue').textContent = n ? `${n} scan${n === 1 ? ' is' : 's are'} saved here and will be sent when it comes back.` : '';
  }
  let sending = false;
  async function sendQueuedScans() {
    if (sending || !reachable || $('#coQueue')) return;        // the Scan gear page handles its own
    let queue = readQueue();
    if (!queue.length) return;
    sending = true;
    let sent = 0, failed = 0;
    while (queue.length) {
      try { await SW.api('POST', '/equipment/checkout/scan', queue[0].body); sent++; }
      catch (e) { if (e.status === 0) break; failed++; }               // 0 = still no connection: keep the rest
      queue = readQueue().slice(1);
      try { localStorage.setItem(QKEY, JSON.stringify(queue)); } catch (e) {}
    }
    sending = false;
    if (sent) SW.toast(`${sent} saved scan${sent === 1 ? '' : 's'} sent`);
    if (failed) SW.toast(`${failed} saved scan${failed === 1 ? '' : 's'} could not be recorded. Scan ${failed === 1 ? 'it' : 'them'} again.`, 'error');
    paintOffline();
  }
  window.addEventListener('online', checkConnection);
  window.addEventListener('offline', () => { reachable = false; paintOffline(); });
  paintOffline();
  checkConnection().then(sendQueuedScans);
  setInterval(() => { if (!reachable && !document.hidden) checkConnection(); }, 20000);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready).then((reg) => {
      // Save the event-day pages and scanner files ahead of time (at most every 10 minutes)
      let last = 0;
      try { last = Number(sessionStorage.getItem('showwise-warm') || 0); } catch (e) {}
      if (!navigator.onLine || !reg.active || Date.now() - last < 10 * 60 * 1000 || !$('.sw-tabbar')) return;
      try { sessionStorage.setItem('showwise-warm', String(Date.now())); } catch (e) {}
      reg.active.postMessage({
        type: 'warm',
        pages: ['/dashboard', '/equipment/checkout', '/picklist'],
        files: ['/static/js/sw-scanner.js', 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js',
                'https://cdn.jsdelivr.net/npm/@ericblade/quagga2@1.8.4/dist/quagga.min.js'],
      });
    }).catch(() => {});
  }

  const scanBtn = $('#swScanBtn');
  if (scanBtn) scanBtn.addEventListener('click', () => Gear.scan());
})();
