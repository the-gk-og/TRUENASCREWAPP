/* roster.js - admin shift scheduler. Depends on sw-ui.js (SW.api, SW.form, SW.confirm, SW.toast). */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = SW.esc;
  const DAY_MS = 86400000;
  const ROLES = ['Sound', 'Lighting', 'Stage Manager', 'Video', 'Backstage', 'FOH', 'Crew Member', 'Rigger', 'Runner', 'Setup', 'Pack down'];

  const state = {
    start: null,                              // Monday of the first column (YYYY-MM-DD)
    days: Number(localStorage.getItem('rsDays')) === 14 ? 14 : 7,
    data: null, filter: '',
  };

  // ---------------------------------------------------------------- dates (wall-clock, no timezone maths)
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parse = (s) => { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
  const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
  const mondayOf = (s) => { const d = parse(s); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d); };
  const hm = (s) => s.slice(11, 16);
  const minutes = (s) => Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16));
  const durationH = (a, b) => (new Date(b) - new Date(a)) / 3600000;
  const fmtDay = (s) => parse(s).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  const todayIso = () => iso(new Date());
  const hue = (id) => (id * 47) % 360;

  // ---------------------------------------------------------------- data
  async function load() {
    try {
      state.data = await SW.api('GET', `/api/roster?start=${state.start}&days=${state.days}`);
      render();
    } catch (err) {
      $('rsGrid').innerHTML = `<div class="sw-empty">${esc(err.message)}</div>`;
    }
  }

  function dayKeys() { return Array.from({ length: state.days }, (_, i) => addDays(state.start, i)); }

  // ---------------------------------------------------------------- render
  function render() {
    const d = state.data, days = dayKeys(), today = todayIso();
    $('rsRange').textContent = `${fmtDay(days[0])} – ${fmtDay(days[days.length - 1])}`;
    $('rsSpan').value = String(state.days);

    // bucket shifts by person + day (a shift lives in the box of the day it starts)
    const box = new Map();
    const put = (uid, day, item) => { const k = `${uid}|${day}`; (box.get(k) || box.set(k, []).get(k)).push(item); };
    const clampDay = (s) => (s.slice(0, 10) < days[0] ? days[0] : s.slice(0, 10));
    const hours = new Map();
    d.shifts.forEach((s) => {
      put(s.user_id, clampDay(s.start), s);
      if (s.status !== 'rejected') hours.set(s.user_id, (hours.get(s.user_id) || 0) + durationH(s.start, s.end));
    });
    d.open.forEach((s) => put('open', clampDay(s.start), s));

    // unavailability: mark each day a window touches
    const away = new Map();
    d.unavailable.forEach((w) => {
      let day = w.start.slice(0, 10);
      const last = w.end.slice(11, 16) === '00:00' ? addDays(w.end.slice(0, 10), -1) : w.end.slice(0, 10);
      for (let n = 0; day <= last && n < 40; n++, day = addDays(day, 1)) away.set(`${w.user_id}|${day}`, w.title);
    });

    const q = state.filter.trim().toLowerCase();
    const people = d.people.filter((p) => !q || p.name.toLowerCase().includes(q) || p.username.toLowerCase().includes(q));

    const g = $('rsGrid');
    g.style.setProperty('--cols', state.days);
    let html = '<div class="rs-head rs-corner"></div>';
    days.forEach((day) => {
      html += `<div class="rs-head${day === today ? ' today' : ''}" role="columnheader">${esc(parse(day).toLocaleDateString(undefined, { weekday: 'short' }))}<small>${esc(parse(day).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }))}</small></div>`;
    });

    const row = (uid, label, sub, avatar, cls) => {
      html += `<div class="rs-person ${cls || ''}" role="rowheader">${avatar}<div class="rs-pname"><b title="${esc(label)}">${esc(label)}</b><small class="rs-hours">${esc(sub)}</small></div></div>`;
      days.forEach((day) => {
        const items = (box.get(`${uid}|${day}`) || []).sort((a, b) => a.start.localeCompare(b.start));
        const off = uid !== 'open' && away.get(`${uid}|${day}`);
        html += `<div class="rs-cell${day === today ? ' today' : ''}${off ? ' unavail' : ''}" role="gridcell" data-user="${uid}" data-date="${day}">`
          + (off ? `<div class="rs-un" title="${esc(off)}">Unavailable · ${esc(off)}</div>` : '')
          + items.map((s) => shiftHtml(s, days[0])).join('')
          + `<button class="rs-add" type="button" aria-label="Add shift" title="Add shift">+</button></div>`;
      });
    };

    const initials = (n) => esc(n.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase());
    row('open', 'Unassigned', `${d.open.length} open shift${d.open.length === 1 ? '' : 's'}`, '<div class="rs-avatar"><i class="fas fa-user-clock"></i></div>', 'rs-open');
    people.forEach((p) => {
      const h = hours.get(p.id) || 0;
      const av = p.avatar ? `<div class="rs-avatar"><img src="/profile/picture/${encodeURIComponent(p.username)}" alt="" onerror="this.parentNode.textContent='${initials(p.name)}'"></div>`
        : `<div class="rs-avatar">${initials(p.name)}</div>`;
      row(p.id, p.name, h ? `${Math.round(h * 10) / 10}h scheduled` : 'No shifts', av);
    });
    if (!people.length) html += '<div class="rs-empty-row">No one matches that search.</div>';
    g.innerHTML = html;
  }

  function shiftHtml(s, firstDay) {
    const overnight = s.end.slice(0, 10) > s.start.slice(0, 10) && !(s.end.slice(11, 16) === '00:00' && s.end.slice(0, 10) === addDays(s.start.slice(0, 10), 1));
    const cont = s.start.slice(0, 10) < firstDay;
    const label = s.status === 'open' ? 'Open' : { pending: 'Awaiting reply', rejected: 'Declined' }[s.status] || '';
    const name = [s.event, s.role].filter(Boolean).join(' › ');
    const style = s.status === 'open' ? '' : ` style="--c:hsl(${hue(s.event_id)} 42% 32%)"`;
    return `<button type="button" class="rs-shift st-${esc(s.status)}${cont ? ' cont' : ''}" draggable="true" data-key="${esc(s.key)}"${style}`
      + ` title="${esc(name)}${s.location ? ' @ ' + esc(s.location) : ''}${label ? ' (' + label + ')' : ''}">`
      + `<span class="t">${hm(s.start)} – ${hm(s.end)}${overnight ? ' <span class="x">+1d</span>' : ''}${cont ? ' <span class="x">↳</span>' : ''}</span>`
      + `<span class="n">${esc(name)}</span>${label ? `<span class="x">${label}</span>` : ''}</button>`;
  }

  // ---------------------------------------------------------------- helpers for forms
  function findItem(key) {
    return state.data.shifts.concat(state.data.open).find((s) => s.key === key);
  }

  function defaultTimes(eventId, day) {
    const ev = state.data.events.find((e) => e.id === Number(eventId));
    if (ev && !ev.all_day && ev.start.slice(0, 10) === day) return { start: ev.start, end: ev.end > ev.start ? ev.end : SW.addHours(ev.start, 3) };
    return { start: `${day}T09:00`, end: `${day}T17:00` };
  }

  function pickEvent(day) {
    const evs = state.data.events;
    const on = evs.find((e) => e.start.slice(0, 10) <= day && e.end.slice(0, 10) >= day);
    return (on || evs.find((e) => e.start.slice(0, 10) >= day) || evs[evs.length - 1] || {}).id || '';
  }

  /** run `fn(force)`; if the server reports a clash, ask before forcing it through. */
  async function withClashCheck(fn) {
    try { return await fn(false); } catch (err) {
      if (err.status === 409 && err.payload && err.payload.conflicts) {
        const list = err.payload.conflicts.map((c) => '• ' + c.title).join('\n');
        const ok = await SW.confirm(`${err.message}:\n\n${list}\n\nSave anyway?`, { title: 'Scheduling clash', okText: 'Save anyway', danger: true });
        if (!ok) throw SW.CANCEL;
        return fn(true);
      }
      throw err;
    }
  }

  // ---------------------------------------------------------------- create / edit dialog
  /**  item: existing shift (edit) | null (create).  preset: {user_id, date} for create. */
  async function shiftDialog(item, preset) {
    const d = state.data, edit = !!item, assigned = edit && item.assignment_id;
    const day = edit ? item.start.slice(0, 10) : (preset.date || todayIso());
    const evId = edit ? item.event_id : pickEvent(day);
    const t = edit ? { start: item.start, end: item.end } : defaultTimes(evId, day);
    if (!d.events.length) { SW.toast('Create an event first - every shift belongs to an event.', 'error'); return; }

    const fields = [
      { name: 'event_id', label: 'Event', type: 'select', required: true,
        options: d.events.map((e) => ({ value: e.id, label: `${e.title} · ${fmtDay(e.start.slice(0, 10))}` })) },
      { name: 'user_id', label: 'Person', type: 'select',
        options: (assigned ? [] : [{ value: '', label: 'Unassigned (open shift)' }]).concat(d.people.map((p) => ({ value: p.id, label: p.name }))) },
      { name: 'role', label: 'Role', suggestions: ROLES, placeholder: 'e.g. Sound', maxLength: 100 },
      { name: 'start', label: 'Starts', type: 'datetime', required: true, half: true },
      { name: 'end', label: 'Ends', type: 'datetime', required: true, half: true },
      { name: 'status', label: 'Status', type: 'select', show: (v) => assigned || !!v.user_id,
        options: [{ value: 'pending', label: 'Pending (waiting for them to accept)' }, { value: 'accepted', label: 'Accepted' },
                  { value: 'confirmed', label: 'Confirmed' }].concat(assigned ? [{ value: 'rejected', label: 'Declined' }] : []) },
      { name: 'notes', label: 'Notes for this shift', type: 'textarea', rows: 2, show: (v) => assigned || !!v.user_id },
    ];
    const values = {
      event_id: evId, user_id: edit ? (item.user_id || '') : (preset.user_id || ''),
      role: edit ? item.role : '', start: SW.toInput(t.start), end: SW.toInput(t.end),
      status: edit && assigned ? item.status : 'pending', notes: edit ? item.notes : '',
    };

    const extra = [];
    if (edit) {
      extra.push({ label: '<i class="fas fa-trash"></i> Delete', danger: true, onClick: async () => {
        const ok = await SW.confirm('Delete this shift?', { title: 'Delete shift', okText: 'Delete', danger: true });
        if (!ok) return null;
        try {
          await (assigned ? SW.api('DELETE', `/events/shift-assignments/${item.assignment_id}`) : SW.api('DELETE', `/api/roster/open/${item.shift_id}`));
          return { deleted: true };
        } catch (err) { SW.toast(err.message, 'error'); return null; }
      } });
      if (assigned) extra.push({ label: 'Unassign', onClick: async () => {
        try { await SW.api('POST', '/api/roster/drop', { key: item.key, user_id: null, date: item.start.slice(0, 10) }); return { moved: true }; }
        catch (err) { SW.toast(err.message, 'error'); return null; }
      } });
    }

    const pending = SW.form({
      title: edit ? 'Edit shift' : 'New shift', values, fields, extraButtons: extra, submitText: edit ? 'Save shift' : 'Create shift',
      onSubmit: (v) => {
        if (v.end <= v.start) throw new Error('The shift must end after it starts');
        const body = { event_id: Number(v.event_id), user_id: v.user_id ? Number(v.user_id) : null, role: v.role,
                       start: v.start, end: v.end, status: v.status || 'pending', notes: v.notes || '' };
        return withClashCheck((force) => {
          const b = { ...body, force };
          if (!edit) return SW.api('POST', '/api/roster/shift', b);
          return assigned ? SW.api('PUT', `/api/roster/assignment/${item.assignment_id}`, b)
                          : SW.api('PUT', `/api/roster/open/${item.shift_id}`, b);
        });
      },
    });

    // picking another event re-suggests the times, until the admin has typed their own
    const overlays = document.querySelectorAll('.sw-overlay');
    const form = overlays.length ? overlays[overlays.length - 1].querySelector('form') : null;
    if (form) {
      let touched = edit;
      form.addEventListener('input', (e) => { if (e.target.name === 'start' || e.target.name === 'end') touched = true; });
      form.addEventListener('change', (e) => {
        if (e.target.name !== 'event_id' || touched) return;
        const tt = defaultTimes(e.target.value, form.elements.start.value.slice(0, 10) || day);
        form.elements.start.value = SW.toInput(tt.start); form.elements.end.value = SW.toInput(tt.end);
      });
    }
    const res = await pending;
    if (res) { SW.toast(edit ? 'Shift updated' : 'Shift created'); load(); }
  }

  // ---------------------------------------------------------------- drag & drop
  async function dropShift(key, cell) {
    const item = findItem(key);
    if (!item) return;
    const uid = cell.dataset.user === 'open' ? null : Number(cell.dataset.user);
    if (item.user_id === uid && item.start.slice(0, 10) === cell.dataset.date) return;
    try {
      await withClashCheck((force) => SW.api('POST', '/api/roster/drop', { key, user_id: uid, date: cell.dataset.date, force }));
      SW.toast('Shift moved');
    } catch (err) { if (err !== SW.CANCEL) SW.toast(err.message, 'error'); }
    load();
  }

  // ---------------------------------------------------------------- wiring
  function go(start) { state.start = mondayOf(start); load(); }
  $('rsPrev').onclick = () => go(addDays(state.start, -state.days));
  $('rsNext').onclick = () => go(addDays(state.start, state.days));
  $('rsToday').onclick = () => go(todayIso());
  $('rsJump').onchange = (e) => { if (e.target.value) go(e.target.value); };
  $('rsSpan').onchange = (e) => { state.days = Number(e.target.value); localStorage.setItem('rsDays', state.days); load(); };
  $('rsSearch').oninput = (e) => { state.filter = e.target.value; if (state.data) render(); };
  $('rsNew').onclick = () => shiftDialog(null, { date: todayIso() });

  const grid = $('rsGrid');
  grid.addEventListener('click', (e) => {
    const add = e.target.closest('.rs-add');
    const shift = e.target.closest('.rs-shift');
    const cell = e.target.closest('.rs-cell');
    if (shift) shiftDialog(findItem(shift.dataset.key));
    else if (add && cell) shiftDialog(null, { user_id: cell.dataset.user === 'open' ? '' : cell.dataset.user, date: cell.dataset.date });
  });
  grid.addEventListener('dragstart', (e) => {
    const s = e.target.closest('.rs-shift'); if (!s) return;
    e.dataTransfer.setData('text/plain', s.dataset.key); e.dataTransfer.effectAllowed = 'move'; s.classList.add('dragging');
  });
  grid.addEventListener('dragend', (e) => { e.target.classList && e.target.classList.remove('dragging'); grid.querySelectorAll('.over').forEach((c) => c.classList.remove('over')); });
  grid.addEventListener('dragover', (e) => {
    const c = e.target.closest('.rs-cell'); if (!c) return;
    e.preventDefault(); grid.querySelectorAll('.over').forEach((x) => x !== c && x.classList.remove('over')); c.classList.add('over');
  });
  grid.addEventListener('drop', (e) => {
    const c = e.target.closest('.rs-cell'); if (!c) return;
    e.preventDefault(); c.classList.remove('over');
    dropShift(e.dataTransfer.getData('text/plain'), c);
  });

  go(todayIso());
})();
