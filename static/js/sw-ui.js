/*
 * sw-ui.js - shared UI helpers for the events system.
 *
 *   SW.api(method, url, data)      fetch JSON, throws Error(.status, .payload)
 *   SW.toast(msg, type)            small notification
 *   SW.confirm(msg, opts)          -> Promise<boolean>
 *   SW.choice(msg, options, opts)  -> Promise<value|null>
 *   SW.form({...})                 declarative modal form (see below)
 *   SW.mdEditor(textarea)          Markdown toolbar + live preview
 *   SW.eventForm({...})            create / edit an event
 *   SW.shiftForm({...})            add / edit a person's shift
 *   SW.scheduleForm / SW.runForm   schedule + run-list items
 *
 * Everything user-supplied is escaped with SW.esc before touching innerHTML.
 * Markdown HTML comes from the server, already sanitised.
 */
(function () {
  'use strict';
  const SW = (window.SW = window.SW || {});
  SW.CANCEL = { cancelled: true };

  const pad = (n) => String(n).padStart(2, '0');

  SW.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /** Date | ISO string -> 'YYYY-MM-DDTHH:MM' (or 'YYYY-MM-DD'), wall-clock, no timezone maths. */
  SW.toInput = (v, dateOnly) => {
    if (!v) return '';
    if (typeof v === 'string') return dateOnly ? v.slice(0, 10) : v.slice(0, 16);
    const d = `${v.getFullYear()}-${pad(v.getMonth() + 1)}-${pad(v.getDate())}`;
    return dateOnly ? d : `${d}T${pad(v.getHours())}:${pad(v.getMinutes())}`;
  };

  SW.addHours = (input, h) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(input || '');
    if (!m) return '';
    const d = new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
    d.setHours(d.getHours() + h);
    return SW.toInput(d);
  };

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  // ------------------------------------------------------------------ API
  SW.api = async function (method, url, data) {
    const opts = { method, headers: { Accept: 'application/json' }, credentials: 'same-origin' };
    if (data !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      const err = new Error('Network error - check your connection and try again');
      err.status = 0;
      throw err;
    }
    if (!(res.headers.get('content-type') || '').includes('json')) {
      const err = new Error(res.ok ? 'Your session has expired - please log in again'
        : `Request failed (${res.status})`);
      err.status = res.ok ? 401 : res.status;
      err.payload = {};
      throw err;
    }
    const payload = await res.json();
    if (!res.ok || (payload && payload.error)) {
      const err = new Error((payload && payload.error) || `Request failed (${res.status})`);
      err.status = res.status;
      err.payload = payload || {};
      throw err;
    }
    return payload;
  };

  SW.reloadSoon = () => setTimeout(() => location.reload(), 300);

  // ---------------------------------------------------------------- toasts
  SW.toast = function (msg, type) {
    let box = document.querySelector('.sw-toasts');
    if (!box) { box = el('div', 'sw-toasts'); document.body.appendChild(box); }
    const t = el('div', `sw-toast ${type === 'error' ? 'error' : 'ok'}`);
    t.setAttribute('role', 'status');
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 250); }, type === 'error' ? 5000 : 2800);
  };

  // --------------------------------------------------------------- dialogs
  const stack = [];
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && stack.length) stack[stack.length - 1].close();
  });

  function openDialog({ title, wide, onClose }) {
    const overlay = el('div', 'sw-overlay');
    const dlg = el('div', `sw-dialog${wide ? ' wide' : ''}`);
    dlg.setAttribute('role', 'dialog');
    dlg.setAttribute('aria-modal', 'true');
    const head = el('div', 'sw-dialog-head');
    const h = el('h2'); h.textContent = title || '';
    const x = el('button', 'sw-x', '&times;'); x.type = 'button'; x.setAttribute('aria-label', 'Close');
    head.append(h, x);
    const bodyEl = el('div', 'sw-dialog-body');
    dlg.append(head, bodyEl);
    overlay.appendChild(dlg);
    document.body.appendChild(overlay);
    document.body.classList.add('sw-noscroll');
    const api = {
      el: dlg, body: bodyEl, setTitle: (t) => { h.textContent = t; },
      close() {
        const i = stack.indexOf(api);
        if (i >= 0) stack.splice(i, 1);
        overlay.remove();
        if (!stack.length) document.body.classList.remove('sw-noscroll');
        if (onClose) onClose();
      },
    };
    x.addEventListener('click', () => api.close());
    stack.push(api);
    return api;
  }
  SW.dialog = openDialog;

  SW.confirm = function (message, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      let answer = false;
      const d = openDialog({ title: opts.title || 'Are you sure?', onClose: () => resolve(answer) });
      const p = el('p', 'sw-confirm-text'); p.textContent = message;
      if (opts.html) p.innerHTML = opts.html;
      const foot = el('div', 'sw-actions');
      const no = el('button', 'btn btn-secondary', 'Cancel'); no.type = 'button';
      const yes = el('button', `btn ${opts.danger ? 'btn-danger' : 'btn-primary'}`); yes.type = 'button';
      yes.textContent = opts.okText || 'Confirm';
      no.onclick = () => d.close();
      yes.onclick = () => { answer = true; d.close(); };
      foot.append(no, yes);
      d.body.append(p, foot);
      yes.focus();
    });
  };

  SW.choice = function (message, options, opts) {
    opts = opts || {};
    return new Promise((resolve) => {
      let answer = null;
      const d = openDialog({ title: opts.title || 'Choose', onClose: () => resolve(answer) });
      const p = el('p', 'sw-confirm-text'); p.textContent = message;
      const list = el('div', 'sw-choices');
      options.forEach((o) => {
        const b = el('button', `btn ${o.danger ? 'btn-danger' : 'btn-secondary'} sw-choice`);
        b.type = 'button'; b.textContent = o.label;
        b.onclick = () => { answer = o.value; d.close(); };
        list.appendChild(b);
      });
      d.body.append(p, list);
    });
  };

  // -------------------------------------------------------------- markdown
  SW.mdEditor = function (ta) {
    const wrap = el('div', 'sw-md');
    ta.parentNode.insertBefore(wrap, ta);
    const bar = el('div', 'sw-md-bar');
    const tabs = el('div', 'sw-md-tabs');
    const tWrite = el('button', 'on', 'Write'); tWrite.type = 'button';
    const tPrev = el('button', '', 'Preview'); tPrev.type = 'button';
    tabs.append(tWrite, tPrev);
    const tools = el('div', 'sw-md-tools');
    const preview = el('div', 'sw-md-preview md-content'); preview.hidden = true;

    const wrapSel = (pre, post, ph) => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const sel = ta.value.slice(s, e) || ph;
      ta.setRangeText(pre + sel + post, s, e, 'end');
      ta.focus();
      ta.setSelectionRange(s + pre.length, s + pre.length + sel.length);
    };
    const linePre = (pre) => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const from = ta.value.lastIndexOf('\n', s - 1) + 1;
      const block = ta.value.slice(from, e).split('\n').map((l, i) => (typeof pre === 'function' ? pre(i) : pre) + l).join('\n');
      ta.setRangeText(block, from, e, 'end');
      ta.focus();
    };
    const link = () => {
      const s = ta.selectionStart, e = ta.selectionEnd;
      const sel = ta.value.slice(s, e) || 'link text';
      ta.setRangeText(`[${sel}](https://)`, s, e, 'end');
      ta.focus();
      const end = s + sel.length + 3;
      ta.setSelectionRange(end, end + 8);
    };
    const buttons = [
      ['<b>B</b>', 'Bold (Ctrl+B)', () => wrapSel('**', '**', 'bold')],
      ['<i>I</i>', 'Italic (Ctrl+I)', () => wrapSel('*', '*', 'italic')],
      ['H', 'Heading', () => linePre('## ')],
      ['&bull;', 'Bullet list', () => linePre('- ')],
      ['1.', 'Numbered list', () => linePre((i) => `${i + 1}. `)],
      ['&ldquo;', 'Quote', () => linePre('> ')],
      ['&lt;/&gt;', 'Code', () => wrapSel('`', '`', 'code')],
      ['<i class="fas fa-link"></i>', 'Link (Ctrl+K)', link],
    ];
    buttons.forEach(([label, title, fn]) => {
      const b = el('button', '', label); b.type = 'button'; b.title = title;
      b.setAttribute('aria-label', title);
      b.addEventListener('mousedown', (ev) => ev.preventDefault());
      b.onclick = fn;
      tools.appendChild(b);
    });
    bar.append(tabs, tools);

    ta.addEventListener('keydown', (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'b') { e.preventDefault(); wrapSel('**', '**', 'bold'); }
      else if (k === 'i') { e.preventDefault(); wrapSel('*', '*', 'italic'); }
      else if (k === 'k') { e.preventDefault(); link(); }
    });

    const show = (mode) => {
      const prev = mode === 'preview';
      tWrite.classList.toggle('on', !prev); tPrev.classList.toggle('on', prev);
      ta.hidden = prev; preview.hidden = !prev; tools.style.visibility = prev ? 'hidden' : '';
    };
    tWrite.onclick = () => show('write');
    tPrev.onclick = async () => {
      show('preview');
      if (!ta.value.trim()) { preview.innerHTML = '<p class="sw-muted">Nothing to preview yet.</p>'; return; }
      preview.innerHTML = '<p class="sw-muted">Rendering…</p>';
      try {
        const r = await SW.api('POST', '/api/markdown/preview', { text: ta.value });
        preview.innerHTML = r.html || '<p class="sw-muted">Nothing to preview yet.</p>';
      } catch (err) {
        preview.innerHTML = `<p class="sw-error">${SW.esc(err.message)}</p>`;
      }
    };
    wrap.append(bar, ta, preview);
    const hint = el('div', 'sw-hint', 'Markdown supported: **bold**, *italic*, lists, links, tables.');
    wrap.appendChild(hint);
    return wrap;
  };

  // ------------------------------------------------------------------ forms
  /**
   * SW.form({
   *   title, fields: [{name,label,type,required,options,placeholder,hint,half,show,rows,
   *                    suggestions, allDayToggle, min, max, value}],
   *   values, submitText, danger, wide,
   *   onSubmit: async (values) => result    // throw Error to show it in the dialog
   * }) -> Promise<result | null>
   * Types: text number textarea markdown datetime date select checkbox days info
   */
  SW.form = function (cfg) {
    return new Promise((resolve) => {
      let result = null;
      const d = openDialog({ title: cfg.title, wide: cfg.wide, onClose: () => resolve(result) });
      const form = el('form', 'sw-form');
      const values = cfg.values || {};
      const nodes = {};
      const uid = 'f' + Math.random().toString(36).slice(2, 7);
      let row = null;

      cfg.fields.forEach((f) => {
        const wrap = el('div', 'sw-field' + (f.half ? ' half' : ''));
        const id = `${uid}-${f.name}`;
        const init = values[f.name] != null ? values[f.name] : (f.value != null ? f.value : '');
        let input;
        if (f.type === 'info') {
          wrap.className = 'sw-info';
          wrap.textContent = f.text || init;
          form.appendChild(wrap);
          row = null;
          return;
        }
        if (f.type !== 'checkbox' && f.label) {
          const lab = el('label'); lab.htmlFor = id;
          lab.innerHTML = SW.esc(f.label) + (f.required ? ' <span class="req">*</span>' : '');
          wrap.appendChild(lab);
        }
        switch (f.type) {
          case 'textarea':
          case 'markdown':
            input = el('textarea'); input.rows = f.rows || (f.type === 'markdown' ? 6 : 3);
            input.value = init; break;
          case 'select':
            input = el('select');
            (f.options || []).forEach((o) => {
              const op = el('option'); op.value = o.value; op.textContent = o.label;
              input.appendChild(op);
            });
            input.value = init !== '' ? init : (f.options && f.options[0] ? f.options[0].value : '');
            break;
          case 'checkbox': {
            input = el('input'); input.type = 'checkbox'; input.checked = !!init;
            const lab = el('label', 'sw-check'); lab.htmlFor = id;
            lab.append(input, document.createTextNode(' ' + (f.label || '')));
            wrap.appendChild(lab);
            break;
          }
          case 'days': {
            input = el('div', 'sw-days');
            const chosen = String(init || '').match(/[0-6]/g) || [];
            ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach((n, i) => {
              const l = el('label'); const c = el('input'); c.type = 'checkbox'; c.value = i;
              c.checked = chosen.includes(String(i)); l.append(c, document.createTextNode(n));
              input.appendChild(l);
            });
            break;
          }
          case 'datetime':
          case 'date':
          case 'number':
          default:
            input = el('input');
            input.type = f.type === 'datetime' ? 'datetime-local' : (f.type || 'text');
            if (f.type === 'number') { input.min = f.min ?? ''; input.max = f.max ?? ''; }
            input.value = init;
            if (f.type === 'datetime' && f.allDayToggle && values[f.allDayToggle]) {
              input.type = 'date'; input.value = SW.toInput(init, true);
            }
        }
        input.id = id; input.name = f.name;
        if (f.required && f.type !== 'checkbox') input.required = true;
        if (f.placeholder) input.placeholder = f.placeholder;
        if (f.maxLength) input.maxLength = f.maxLength;
        if (f.suggestions) {
          const dl = el('datalist'); dl.id = id + '-dl';
          f.suggestions.forEach((s) => { const o = el('option'); o.value = s; dl.appendChild(o); });
          wrap.appendChild(dl); input.setAttribute('list', dl.id);
        }
        if (f.type !== 'checkbox') wrap.appendChild(input);
        if (f.hint) wrap.appendChild(el('div', 'sw-hint', SW.esc(f.hint)));
        nodes[f.name] = { f, wrap, input };

        if (f.half) {
          if (!row || row.children.length >= 2) { row = el('div', 'sw-row'); form.appendChild(row); }
          row.appendChild(wrap);
        } else { row = null; form.appendChild(wrap); }
        if (f.type === 'markdown') SW.mdEditor(input);
      });

      const read = () => {
        const out = {};
        Object.values(nodes).forEach(({ f, wrap, input }) => {
          if (wrap.hidden) return;
          if (f.type === 'checkbox') out[f.name] = input.checked;
          else if (f.type === 'number') out[f.name] = input.value === '' ? null : Number(input.value);
          else if (f.type === 'file') out[f.name] = input.files[0] || null;
          else if (f.type === 'days') out[f.name] = [...input.querySelectorAll('input:checked')].map((c) => c.value).join(',');
          else out[f.name] = input.value;
        });
        return out;
      };

      const refresh = () => {
        const vals = read();
        // all-day toggles switch datetime inputs between date and datetime-local
        Object.values(nodes).forEach(({ f, input }) => {
          if (f.type === 'datetime' && f.allDayToggle && nodes[f.allDayToggle]) {
            const wantDate = nodes[f.allDayToggle].input.checked;
            if (wantDate && input.type !== 'date') {
              const v = input.value; input.type = 'date'; input.value = v.slice(0, 10);
            } else if (!wantDate && input.type !== 'datetime-local') {
              const v = input.value; input.type = 'datetime-local';
              input.value = v ? `${v.slice(0, 10)}T${f.defaultTime || '09:00'}` : '';
            }
          }
        });
        Object.values(nodes).forEach(({ f, wrap, input }) => {
          if (!f.show) return;
          const vis = !!f.show(read());
          wrap.hidden = !vis;
          if (input.tagName && 'disabled' in input) input.disabled = !vis;
        });
        void vals;
      };
      form.addEventListener('input', refresh);
      form.addEventListener('change', refresh);

      const err = el('div', 'sw-error'); err.hidden = true; err.setAttribute('role', 'alert');
      const foot = el('div', 'sw-actions');
      (cfg.extraButtons || []).forEach((b) => {
        const btn = el('button', `btn ${b.danger ? 'btn-danger' : 'btn-secondary'} sw-left`);
        btn.type = 'button'; btn.innerHTML = b.label;
        btn.onclick = async () => { const r = await b.onClick(); if (r) { result = r; d.close(); } };
        foot.appendChild(btn);
      });
      const cancel = el('button', 'btn btn-secondary', 'Cancel'); cancel.type = 'button';
      cancel.onclick = () => d.close();
      const submit = el('button', `btn ${cfg.danger ? 'btn-danger' : 'btn-primary'}`);
      submit.type = 'submit'; submit.textContent = cfg.submitText || 'Save';
      foot.append(cancel, submit);
      form.append(err, foot);
      d.body.appendChild(form);
      refresh();
      const first = form.querySelector('input:not([type=checkbox]),select,textarea');
      if (first) setTimeout(() => first.focus(), 30);

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!form.reportValidity()) return;
        err.hidden = true;
        submit.disabled = true;
        const label = submit.textContent;
        submit.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving…';
        try {
          const r = await cfg.onSubmit(read());
          result = r === undefined ? true : r;
          d.close();
        } catch (ex) {
          if (ex !== SW.CANCEL) { err.textContent = ex.message || 'Something went wrong'; err.hidden = false; }
        } finally {
          submit.disabled = false; submit.textContent = label;
        }
      });
    });
  };

  // ----------------------------------------------------- domain-level forms
  const REC_OPTIONS = [
    { value: '', label: 'Does not repeat' }, { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' }, { value: 'biweekly', label: 'Every 2 weeks' },
    { value: 'monthly', label: 'Monthly' }, { value: 'yearly', label: 'Yearly' },
  ];

  /** Create (no `event`) or edit an event.  Resolves with the API response or null. */
  SW.eventForm = function ({ event, defaults, canRecur }) {
    const edit = !!event;
    const d = Object.assign({ all_day: false }, defaults || {}, event || {});
    if (!d.event_date) d.event_date = SW.toInput(new Date(Date.now() - (Date.now() % 900000) + 900000));
    if (!d.event_end_date) d.event_end_date = d.all_day ? d.event_date : SW.addHours(d.event_date, 3);
    const fields = [
      { name: 'title', label: 'Title', required: true, maxLength: 200, placeholder: 'e.g. Opening Night' },
      { name: 'all_day', label: 'All-day event', type: 'checkbox' },
      { name: 'event_date', label: 'Starts', type: 'datetime', allDayToggle: 'all_day', required: true, half: true, defaultTime: '09:00' },
      { name: 'event_end_date', label: 'Ends', type: 'datetime', allDayToggle: 'all_day', required: true, half: true, defaultTime: '12:00' },
      { name: 'location', label: 'Location', maxLength: 200, placeholder: 'Venue / room' },
      { name: 'description', label: 'Description', type: 'markdown', rows: 7 },
    ];
    if (edit && d.is_recurring) {
      fields.push({
        name: 'scope', label: 'Apply changes to', type: 'select', options: [
          { value: 'this', label: 'This event only' },
          { value: 'future', label: 'This and following events' },
          { value: 'all', label: `All events in the series${d.series_count ? ` (${d.series_count})` : ''}` },
        ],
      });
    }
    if (!edit && canRecur) {
      fields.push(
        { name: 'rec_pattern', label: 'Repeat', type: 'select', options: REC_OPTIONS },
        { name: 'rec_interval', label: 'Every', type: 'number', min: 1, max: 52, half: true, value: 1, show: (v) => v.rec_pattern },
        { name: 'rec_end', label: 'Ends', type: 'select', half: true, show: (v) => v.rec_pattern, options: [
          { value: 'count', label: 'After a number of events' }, { value: 'date', label: 'On a date' }] },
        { name: 'rec_count', label: 'Number of events', type: 'number', min: 2, max: 400, value: 10, show: (v) => v.rec_pattern && v.rec_end === 'count' },
        { name: 'rec_until', label: 'Repeat until', type: 'date', show: (v) => v.rec_pattern && v.rec_end === 'date' },
      );
    }
    return SW.form({
      title: edit ? 'Edit event' : 'New event', wide: true, values: d, fields,
      submitText: edit ? 'Save changes' : 'Create event',
      onSubmit: async (v) => {
        if (v.event_end_date && v.event_date && v.event_end_date <= v.event_date && !v.all_day) {
          throw new Error('The end must be after the start');
        }
        const payload = {
          title: v.title, all_day: v.all_day, event_date: v.event_date,
          event_end_date: v.event_end_date, location: v.location, description: v.description,
        };
        if (edit) {
          payload.scope = v.scope || 'this';
          return SW.api('PUT', `/events/${event.id}/edit`, payload);
        }
        if (v.rec_pattern) {
          payload.recurrence = { pattern: v.rec_pattern, interval: v.rec_interval || 1 };
          if (v.rec_end === 'date') {
            if (!v.rec_until) throw new Error('Choose a date to repeat until');
            payload.recurrence.end_date = v.rec_until;
          } else payload.recurrence.count = v.rec_count || 10;
        }
        return SW.api('POST', '/events/add', payload);
      },
    });
  };

  const ROLE_SUGGESTIONS = ['Sound', 'Lighting', 'Stage Manager', 'Video', 'Backstage', 'FOH', 'Crew Member', 'Rigger', 'Runner'];
  const STATUS = [
    { value: 'pending', label: 'Pending (waiting for them to accept)' },
    { value: 'accepted', label: 'Accepted' }, { value: 'confirmed', label: 'Confirmed' },
    { value: 'rejected', label: 'Declined' },
  ];

  /**
   * Add a person's shift to an event, or edit an existing one.
   * add:  { event:{id,start,end}, users:[{id,name}], user_id? }
   * edit: { shift:{assignment_id,username,role,start,end,status,notes}, event:{id,start,end} }
   */
  SW.shiftForm = function ({ event, users, shift, user_id }) {
    const edit = !!shift;
    const fields = [];
    if (edit) fields.push({ type: 'info', text: `Shift for ${shift.name || shift.username}` });
    else fields.push({
      name: 'user_id', label: 'Person', type: 'select', required: true,
      options: [{ value: '', label: 'Choose a person…' }].concat(users.map((u) => ({ value: u.id, label: u.name }))),
    });
    fields.push(
      { name: 'role', label: 'Role', suggestions: ROLE_SUGGESTIONS, placeholder: 'e.g. Sound', maxLength: 100 },
      { name: 'start', label: 'Shift starts', type: 'datetime', required: true, half: true },
      { name: 'end', label: 'Shift ends', type: 'datetime', required: true, half: true },
      { name: 'status', label: 'Status', type: 'select', options: edit ? STATUS : STATUS.slice(0, 3) },
      { name: 'notes', label: 'Notes for this shift', type: 'textarea', rows: 2 },
    );
    const values = edit
      ? { role: shift.role, start: SW.toInput(shift.start), end: SW.toInput(shift.end), status: shift.status, notes: shift.notes }
      : { role: '', start: SW.toInput(event.start), end: SW.toInput(event.end), status: 'pending', user_id: user_id || '' };

    const send = async (v, force) => {
      const body = { role: v.role, start: v.start, end: v.end, status: v.status, notes: v.notes, force };
      if (!edit) body.user_id = Number(v.user_id);
      return edit
        ? SW.api('PUT', `/events/shift-assignments/${shift.assignment_id}`, body)
        : SW.api('POST', `/events/${event.id}/team/add`, body);
    };
    return SW.form({
      title: edit ? 'Edit shift' : 'Add person to event', values, fields,
      submitText: edit ? 'Save shift' : 'Add shift',
      onSubmit: async (v) => {
        if (v.end <= v.start) throw new Error('The shift must end after it starts');
        try { return await send(v, false); } catch (err) {
          if (err.status === 409 && err.payload && err.payload.conflicts) {
            const list = err.payload.conflicts.map((c) => '• ' + c.title).join('\n');
            const ok = await SW.confirm(`${err.message}:\n\n${list}\n\nSave anyway?`,
              { title: 'Scheduling clash', okText: 'Save anyway', danger: true });
            if (!ok) throw SW.CANCEL;
            return send(v, true);
          }
          throw err;
        }
      },
    });
  };

  SW.scheduleForm = function ({ eventId, item, defaultTime }) {
    const edit = !!item;
    return SW.form({
      title: edit ? 'Edit schedule item' : 'Add schedule item',
      values: edit ? { title: item.title, scheduled_time: SW.toInput(item.time), description: item.description }
        : { scheduled_time: SW.toInput(defaultTime) },
      fields: [
        { name: 'title', label: 'What happens', required: true, maxLength: 100, placeholder: 'e.g. Bump in' },
        { name: 'scheduled_time', label: 'Time', type: 'datetime', required: true },
        { name: 'description', label: 'Details', type: 'markdown', rows: 4 },
      ],
      submitText: edit ? 'Save' : 'Add item',
      onSubmit: (v) => edit ? SW.api('PUT', `/events/schedule/${item.id}/edit`, v)
        : SW.api('POST', `/events/${eventId}/schedule/add`, v),
    });
  };

  const CUES = ['Lighting', 'Sound', 'Video', 'Stage', 'Fly', 'Pyro', 'Spot', 'Other'];
  SW.runForm = function ({ eventId, item }) {
    const edit = !!item;
    return SW.form({
      title: edit ? 'Edit run item' : 'Add run item',
      values: item || {},
      fields: [
        { name: 'title', label: 'Title', required: true, maxLength: 200 },
        { name: 'duration', label: 'Duration', half: true, placeholder: 'e.g. 5 min', maxLength: 50 },
        { name: 'cue_type', label: 'Cue type', half: true, suggestions: CUES, maxLength: 50 },
        { name: 'description', label: 'Description', type: 'markdown', rows: 4 },
        { name: 'notes', label: 'Notes', type: 'textarea', rows: 2 },
      ],
      submitText: edit ? 'Save' : 'Add item',
      onSubmit: (v) => edit ? SW.api('PUT', `/events/crew-run/${item.id}/edit`, v)
        : SW.api('POST', `/events/${eventId}/crew-run/add`, v),
    });
  };

  SW.noteForm = function ({ eventId, note }) {
    const edit = !!note;
    return SW.form({
      title: edit ? 'Edit note' : 'Add note', values: note ? { content: note.content } : {},
      fields: [{ name: 'content', label: '', type: 'markdown', required: true, rows: 8 }],
      submitText: edit ? 'Save note' : 'Post note',
      onSubmit: (v) => edit ? SW.api('PUT', `/events/notes/${note.id}/edit`, v)
        : SW.api('POST', `/events/${eventId}/notes/add`, v),
    });
  };

  /** Ask which part of a series an action applies to.  Resolves 'this'|'future'|'all'|null. */
  SW.seriesScope = function (verb, count) {
    return SW.choice(`This event repeats (${count} in the series). ${verb} which events?`, [
      { value: 'this', label: 'Only this event' },
      { value: 'future', label: 'This and following events', danger: verb === 'Delete' },
      { value: 'all', label: 'All events in the series', danger: verb === 'Delete' },
    ], { title: `${verb} recurring event` });
  };

  /** Accept / decline a shift (the person it belongs to, or an admin).
   *  Declining asks for an optional reason, which is included in the email to the admins. */
  SW.respondShift = async function (assignmentId, status) {
    const send = async (extra) => {
      await SW.api('POST', `/shifts/assignment/${assignmentId}/respond`, Object.assign({ status }, extra));
      SW.toast(status === 'rejected' ? 'Shift declined' : 'Shift accepted');
      SW.reloadSoon();
    };
    if (status !== 'rejected') { try { await send({}); } catch (e) { SW.toast(e.message, 'error'); } return; }
    await SW.form({
      title: "Can't make this shift?",
      fields: [{ type: 'info', text: 'The admins will be emailed so they can find cover.' },
        { name: 'reason', label: 'Reason (optional)', type: 'textarea', rows: 2, maxLength: 500, placeholder: 'e.g. exam that day' }],
      submitText: 'Decline shift', danger: true,
      onSubmit: (v) => send({ reason: v.reason }),
    });
  };

  /** Run an async action with an error toast. */
  SW.run = async function (fn, okMsg) {
    try { const r = await fn(); if (okMsg) SW.toast(okMsg); return r; } catch (e) {
      if (e !== SW.CANCEL) SW.toast(e.message || 'Something went wrong', 'error');
      return null;
    }
  };
})();
