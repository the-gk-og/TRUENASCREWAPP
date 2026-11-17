/* running-order.js - an event's running order: acts / segments (a band, a changeover, the interval),
 * each with its songs. Planned times come from the server (worked out from the order and lengths);
 * the live clock records when each act and song actually starts, and shows how late the show is.
 *
 *   RunningOrder.init({ eventId, canManage, data })   // data = page_data.running_order
 *
 * Depends on sw-ui.js (SW.api, SW.form, SW.confirm, SW.toast, SW.esc) and SortableJS (optional).
 * Everything user-typed is escaped with SW.esc before it touches innerHTML.
 */
(function () {
  'use strict';
  const RO = (window.RunningOrder = {});
  const esc = (s) => SW.esc(s);
  let CFG, P, list, offset = 0, sortables = [], tick = null, poll = null, busy = false;

  /* ---------------------------------------------------------------- time helpers */
  const parse = (iso) => (iso ? new Date(iso) : null);           // naive ISO = the venue's wall clock
  const serverNow = () => Date.now() - offset;
  function clock(iso) {
    if (!iso) return '';
    const h = Number(iso.slice(11, 13)), m = iso.slice(14, 16);
    return `${h % 12 || 12}:${m} ${h < 12 ? 'am' : 'pm'}`;
  }
  function len(mins) {
    if (mins == null) return '';
    const s = Math.round(mins);
    return s >= 60 ? `${Math.floor(s / 60)} h ${String(s % 60).padStart(2, '0')} min` : `${s} min`;
  }
  function mmss(ms) {
    const t = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  }
  function late(mins) {
    const m = Math.round(mins);
    if (!m) return 'on time';
    return `${len(Math.abs(m))} ${m > 0 ? 'late' : 'early'}`;
  }
  const lateClass = (mins) => (Math.abs(mins) <= 2 ? 'ok' : mins > 10 ? 'bad' : 'warn');

  /* ---------------------------------------------------------------- data */
  const flat = () => P.acts.flatMap((a) => [a, ...a.songs]);
  const byId = (id) => flat().find((x) => x.id === Number(id));
  function actOf(row) { return row.parent_id ? P.acts.find((a) => a.id === row.parent_id) : null; }

  function load(data) {
    P = data;
    offset = Date.now() - parse(P.now).getTime();
    render();
  }
  async function refresh() {
    try { load(await SW.api('GET', `/events/${CFG.eventId}/running-order`)); }
    catch (err) { SW.toast(err.message, 'error'); }
  }
  async function mutate(fn) {
    if (busy) return;
    busy = true;
    try { const r = await fn(); if (r && r.acts) load(r); else await refresh(); }
    catch (err) { if (err !== SW.CANCEL) SW.toast(err.message, 'error'); }
    finally { busy = false; }
  }

  /* ---------------------------------------------------------------- drawing */
  function actual(r) {
    if (!r.started_at) return '';
    const parts = [];
    if (r.live) parts.push(`<span class="sw-chip ${lateClass(r.late || 0)}"><i class="fas fa-circle ro-dot"></i>On since ${clock(r.started_at)}${r.late != null && Math.round(r.late) ? ` · ${late(r.late)}` : ''}</span>`);
    else {
      const over = r.length != null && r.actual_length != null ? r.actual_length - r.length : null;
      parts.push(`<span class="sw-chip plain" title="Actual start and length">Started ${clock(r.started_at)}${r.late != null && Math.round(r.late) ? ` (${Math.round(r.late) > 0 ? '+' : '−'}${Math.abs(Math.round(r.late))})` : ''}`
        + `${r.actual_length != null ? ` · ran ${r.actual_length < 1 ? mmss(r.actual_length * 60000) : len(r.actual_length)}` : ''}</span>`);
      if (over != null && Math.round(over) >= 1) parts.push(`<span class="sw-chip ${lateClass(over)}">${Math.round(over)} min over</span>`);
    }
    return parts.join('');
  }
  function buttons(r, song) {
    if (!CFG.canManage) return '';
    const t = song ? 'song' : 'act';
    return `<div class="ro-btns">
      <button class="btn btn-ghost btn-icon ro-go" data-ro="go" data-id="${r.id}" title="Start this ${t} now"><i class="fas fa-play"></i></button>
      <button class="btn btn-ghost btn-icon" data-ro="up" data-id="${r.id}" title="Move up"><i class="fas fa-arrow-up"></i></button>
      <button class="btn btn-ghost btn-icon" data-ro="down" data-id="${r.id}" title="Move down"><i class="fas fa-arrow-down"></i></button>
      <button class="btn btn-ghost btn-icon" data-ro="edit" data-id="${r.id}" title="Edit"><i class="fas fa-pen"></i></button>
      <button class="btn btn-ghost btn-icon" data-ro="del" data-id="${r.id}" title="Delete"><i class="fas fa-trash"></i></button></div>`;
  }
  function state(r) {
    return (r.live ? ' ro-on' : '') + (r.started_at && !r.live ? ' ro-done' : '') + (P.next_id === r.id && P.started ? ' ro-next' : '');
  }
  function songHtml(s) {
    return `<div class="ro-row ro-song${state(s)}" data-id="${s.id}">
      ${CFG.canManage ? '<span class="handle ro-h-song" title="Drag to reorder or move to another act"><i class="fas fa-grip-vertical"></i></span>' : ''}
      <span class="ro-sn">${s.n}</span>
      <span class="ro-time">${P.timed ? clock(s.planned) : ''}</span>
      <div class="ro-main"><div class="ro-title">${esc(s.title)}</div>
        <div class="ro-meta">${s.duration ? `<span class="ro-len">${esc(s.duration)}</span>` : ''}${actual(s)}</div>
        ${s.description || s.notes ? `<div class="ro-notes">${esc([s.description, s.notes].filter(Boolean).join('\n'))}</div>` : ''}</div>
      ${buttons(s, true)}</div>`;
  }
  function actHtml(a) {
    const quiet = a.quiet ? ' ro-quiet' : '';
    let length = a.duration ? `<span class="sw-chip plain"><i class="fas fa-hourglass-half"></i>${esc(a.duration)}</span>` : '';
    if (!a.duration && a.songs_length) length = `<span class="sw-chip plain" title="The songs' lengths added up"><i class="fas fa-hourglass-half"></i>${len(a.songs_length)}</span>`;
    else if (a.duration && a.songs_length && a.minutes != null && Math.round(a.songs_length) > Math.round(a.minutes))
      length += `<span class="sw-chip warn" title="The songs add up to more than the act's length">Songs add up to ${len(a.songs_length)}</span>`;
    const songs = a.songs.length ? `<span class="sw-chip plain">${a.songs.length} song${a.songs.length === 1 ? '' : 's'}</span>` : '';
    return `<div class="ro-act${quiet}" data-id="${a.id}">
      <div class="ro-row ro-act-row${state(a)}">
        ${CFG.canManage ? '<span class="handle ro-h-act" title="Drag to reorder"><i class="fas fa-grip-vertical"></i></span>' : ''}
        <span class="num">${a.n}</span>
        <span class="ro-time">${P.timed ? clock(a.planned) : ''}</span>
        <div class="ro-main">
          <div class="ro-title">${esc(a.title)}${a.kind ? ` <span class="sw-chip ro-kind">${esc(a.kind)}</span>` : ''}</div>
          <div class="ro-meta">${length}${songs}${actual(a)}</div>
          ${a.description ? `<div class="ro-notes">${esc(a.description)}</div>` : ''}
          ${a.notes ? `<div class="ro-notes sw-muted">${esc(a.notes)}</div>` : ''}
        </div>
        ${buttons(a, false)}
      </div>
      <div class="ro-songs" data-act="${a.id}">${a.songs.map(songHtml).join('')}</div>
      ${CFG.canManage && !a.quiet || CFG.canManage && a.songs.length ? `<form class="ro-addsong" data-act="${a.id}" autocomplete="off">
        <input type="text" name="title" class="sw-input" maxlength="200" placeholder="+ Add a song to ${esc(a.title)}" aria-label="Add a song to ${esc(a.title)}">
        <input type="text" name="duration" class="sw-input ro-addsong-len" maxlength="50" placeholder="Length" aria-label="Song length">
        <button type="submit" class="btn btn-ghost btn-sm" title="Add song"><i class="fas fa-plus"></i></button></form>` : ''}
    </div>`;
  }

  function render() {
    const focus = document.activeElement && document.activeElement.closest('.ro-addsong');
    const focusAct = focus ? focus.dataset.act : null, focusName = focus ? document.activeElement.name : null;
    list.innerHTML = P.acts.map(actHtml).join('');
    document.getElementById('runEmpty').hidden = P.acts.length > 0;
    document.getElementById('runCount').textContent = P.count;
    document.querySelectorAll('.ev-tabs [data-tab="run"] .n').forEach((n) => { n.textContent = P.count; });
    const total = document.getElementById('runTotal');
    let t = '';
    if (P.timed) {
      t = `Runs ${len(P.total)}, finishing about ${clock(P.end)}`;
      if (P.missing) t += ` · ${P.missing} act${P.missing === 1 ? ' has' : 's have'} no length`;
    } else if (P.acts.length) t = 'Add lengths to see when each act starts.';
    total.textContent = t;
    if (focusAct) {
      const f = list.querySelector(`.ro-addsong[data-act="${focusAct}"] [name="${focusName}"]`);
      if (f) f.focus();
    }
    drawLive();
    makeSortable();
  }

  function drawLive() {
    const box = document.getElementById('roLive');
    const cur = P.current_id ? byId(P.current_id) : null;
    box.hidden = !P.started;
    box.classList.toggle('on', !!cur);
    if (P.started) {
      document.getElementById('roLiveTag').textContent = cur ? 'Live' : P.finished ? 'Finished' : 'Paused';
      const act = cur ? actOf(cur) : null;
      document.getElementById('roNow').textContent = cur ? cur.title : P.finished ? 'The running order has finished' : 'Nothing on stage';
      document.getElementById('roNowSub').textContent = act ? ` · ${act.title}` : '';
      const d = document.getElementById('roDrift');
      if (P.drift != null) {
        d.className = `ro-live-drift ${lateClass(P.drift)}`;
        d.textContent = (P.finished ? `Finished ${late(P.drift)}` : `Running ${late(P.drift)}`)
          + (P.expected_end && !P.finished ? ` · finish about ${clock(P.expected_end)} (planned ${clock(P.end)})` : '');
      } else d.textContent = '';
    }
    tickClock();
    clearInterval(tick);
    if (cur) tick = setInterval(tickClock, 1000);

    const ctl = document.getElementById('roControls');
    if (ctl) {
      ctl.hidden = !P.acts.length;
      const nxt = P.next_id ? byId(P.next_id) : null, b = document.getElementById('roNext');
      b.disabled = !nxt;
      b.querySelector('span').textContent = !nxt ? 'Nothing left' : P.started ? `Next: ${nxt.title}` : `Start the show: ${nxt.title}`;
      document.getElementById('roStop').hidden = !P.live;
      document.getElementById('roReset').hidden = !P.started;
    }
  }
  function tickClock() {
    const el = document.getElementById('roElapsed'), cur = P.current_id ? byId(P.current_id) : null;
    if (!cur) { el.textContent = ''; return; }
    const ms = serverNow() - parse(cur.started_at).getTime();
    const of = cur.length != null ? cur.length * 60000 : null;
    el.textContent = mmss(ms) + (of != null ? ` / ${mmss(of)}` : '');
    el.classList.toggle('over', of != null && ms > of);
  }

  /* ---------------------------------------------------------------- ordering */
  const orderFrom = (acts) => acts.map((a) => ({ id: a.id, songs: a.songs.map((s) => s.id) }));
  function domOrder() {
    return [...list.querySelectorAll(':scope > .ro-act')].map((a) => ({
      id: Number(a.dataset.id),
      songs: [...a.querySelectorAll('.ro-songs > .ro-song')].map((s) => Number(s.dataset.id)),
    }));
  }
  const saveOrder = (order) => mutate(async () => {
    await SW.api('POST', `/events/${CFG.eventId}/crew-run/reorder`, { tree: order });
  });
  function move(id, dir) {
    const order = orderFrom(P.acts);
    const ai = order.findIndex((a) => a.id === id);
    if (ai >= 0) {                                         // an act, with its songs
      const to = ai + dir;
      if (to < 0 || to >= order.length) return;
      [order[ai], order[to]] = [order[to], order[ai]];
      return saveOrder(order);
    }
    const a = order.find((x) => x.songs.includes(id));
    if (!a) return;
    const si = a.songs.indexOf(id), to = si + dir;
    a.songs.splice(si, 1);
    if (to >= 0 && to <= a.songs.length) a.songs.splice(to, 0, id);
    else {                                                 // off the end of the set: into the next / previous act
      const ni = order.indexOf(a) + dir;
      if (ni < 0 || ni >= order.length) return;
      if (dir < 0) order[ni].songs.push(id); else order[ni].songs.unshift(id);
    }
    return saveOrder(order);
  }
  function makeSortable() {
    sortables.forEach((s) => s.destroy());
    sortables = [];
    if (!CFG.canManage || !window.Sortable) return;
    const onEnd = () => saveOrder(domOrder());
    sortables.push(Sortable.create(list, { handle: '.ro-h-act', draggable: '.ro-act', animation: 150, onEnd }));
    list.querySelectorAll('.ro-songs').forEach((el) => sortables.push(Sortable.create(el, {
      group: 'ro-songs', handle: '.ro-h-song', draggable: '.ro-song', animation: 150, onEnd,
    })));
  }

  /* ---------------------------------------------------------------- adding */
  const SONG_MARK = /^\s*(?:[-•*–]|\t|\s{2,})\s*/;
  async function addAct(v) {
    return SW.api('POST', `/events/${CFG.eventId}/crew-run/add`, v);
  }
  async function addSong(actId, v) {
    return SW.api('POST', `/events/${CFG.eventId}/crew-run/add`, { ...v, parent_id: actId });
  }

  function quickAct(form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const v = Object.fromEntries(new FormData(form).entries());
      let title = (v.title || '').trim();
      if (!title) return;
      const last = P.acts[P.acts.length - 1];
      const song = /^[-•*–]/.test(title) && last;
      title = title.replace(/^[-•*–]\s*/, '');
      mutate(async () => {
        if (song) await addSong(last.id, { title, duration: v.duration.trim() });
        else await addAct({ title, duration: v.duration.trim(), kind: v.kind.trim() });
        form.reset(); form.title.focus();
      }).then(() => { const r = list.lastElementChild; if (r) r.scrollIntoView({ block: 'nearest' }); });
    });
  }

  async function paste() {
    const r = await SW.form({
      title: 'Paste a running order', submitText: 'Add these', wide: true,
      fields: [{ type: 'info', text: 'One line per act. Put songs under their act, starting with “-” (or indented). '
                 + 'Add more with a tab or “|”: Act | Length | Type | Notes, and for songs: - Song | Length | Notes. '
                 + 'A table copied from Word or Excel works too.' },
               { name: 'text', label: 'Running order', type: 'textarea', rows: 12, required: true,
                 placeholder: 'The Openers | 30 min | Band\n- First song | 3:45\n- Second song | 4:10\nChangeover | 15 min | Changeover\nHeadliner | 60 min | Band\n- Opener | 4:00' }],
      onSubmit: async (v) => {
        const lines = v.text.split('\n').filter((l) => l.trim());
        if (!lines.length) throw new Error('Nothing to add');
        let act = P.acts.length ? P.acts[P.acts.length - 1].id : null, n = 0;
        for (const raw of lines) {
          const song = SONG_MARK.test(raw);
          const cells = raw.replace(SONG_MARK, '').replace(/^\s*\d+[.)]\s+/, '').split(/\t|\s*\|\s*/).map((c) => c.trim());
          if (!cells[0]) continue;
          const title = cells[0].slice(0, 200), duration = (cells[1] || '').slice(0, 50);
          if (song && act) await addSong(act, { title, duration, notes: cells.slice(2).join(' ') });
          else act = (await addAct({ title, duration, kind: (cells[2] || '').slice(0, 50), notes: cells[3] || '' })).id;
          n += 1;
        }
        return n;
      },
    });
    if (r) { SW.toast(`${r} line${r === 1 ? '' : 's'} added`); refresh(); }
  }

  async function edit(id) {
    const row = byId(id);
    if (!row) return;
    if (await SW.runForm({ eventId: CFG.eventId, item: row })) { SW.toast('Saved'); refresh(); }
  }

  async function remove(id) {
    const row = byId(id);
    if (!row) return;
    const what = row.parent_id ? `the song “${row.title}”` : row.songs.length
      ? `“${row.title}” and its ${row.songs.length} song${row.songs.length === 1 ? '' : 's'}` : `“${row.title}”`;
    if (!(await SW.confirm(`Delete ${what}?`, { danger: true, okText: 'Delete' }))) return;
    mutate(() => SW.api('DELETE', `/events/crew-run/${id}/delete`));
  }

  /* ---------------------------------------------------------------- live */
  const go = (id) => mutate(() => SW.api('POST', `/events/${CFG.eventId}/running-order/go`, id ? { item_id: id } : {}));

  RO.init = function (cfg) {
    CFG = cfg;
    list = document.getElementById('runList');
    if (!list) return;
    load(cfg.data);

    list.addEventListener('click', (e) => {
      const b = e.target.closest('[data-ro]');
      if (!b) return;
      e.preventDefault();
      const id = Number(b.dataset.id);
      ({ go: () => go(id), up: () => move(id, -1), down: () => move(id, 1), edit: () => edit(id), del: () => remove(id) })[b.dataset.ro]();
    });
    list.addEventListener('submit', (e) => {
      const form = e.target.closest('.ro-addsong');
      if (!form) return;
      e.preventDefault();
      const title = form.title.value.trim();
      if (!title) return;
      const duration = form.duration.value.trim();
      form.title.value = ''; form.duration.value = '';
      form.title.focus();
      mutate(() => addSong(Number(form.dataset.act), { title, duration }));
    });
    const q = document.getElementById('runQuick');
    if (q) quickAct(q);

    const start = document.getElementById('runStart');
    if (start && cfg.canManage) start.addEventListener('change', () => mutate(async () => {
      await SW.api('PUT', `/events/${CFG.eventId}/run-start`, { time: start.value });
    }));

    RO.actions = {
      'ro-next': () => go(null),
      'ro-stop': () => mutate(() => SW.api('POST', `/events/${CFG.eventId}/running-order/stop`, {})),
      'ro-reset': async () => {
        if (!(await SW.confirm('Clear the actual start times? The running order itself stays.', { okText: 'Clear times' }))) return;
        mutate(() => SW.api('POST', `/events/${CFG.eventId}/running-order/reset`, {}));
      },
      'paste-run': paste,
    };

    // Other people's phones follow the show: refresh while the tab is open and the show is on
    poll = setInterval(() => {
      const pane = list.closest('.ev-pane');
      if (document.hidden || (pane && pane.hidden) || busy) return;
      if (document.activeElement && document.activeElement.closest('#runList, #runQuick')) return;
      refresh();
    }, 20000);
  };
})();
