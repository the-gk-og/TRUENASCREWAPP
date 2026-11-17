/* ShowWise scan station (kiosk). One shared device by the store-room door:
 * someone scans their badge (or picks their name + PIN), picks an event or "bring gear back",
 * then scans labels one after another. Works with the camera and with keyboard-wedge
 * scanners (fast typed text + Enter). Signs out by itself after a quiet spell.
 * Server side: routes/scan_station.py (every scan is recorded as the signed-in person). */
(function () {
    'use strict';
    const CFG = JSON.parse(document.getElementById('ks-data').textContent);
    const IDLE = Math.max(30, CFG.idle || 90) * 1000, WARN = 15 * 1000;
    const $ = (s, r = document) => r.querySelector(s);
    const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const isBadge = (code) => /^SWB[A-Z2-7]{8,}$/i.test(code.trim());

    let person = null, event = null, what = 'move', busy = false, screen = 'who';
    let lastActive = Date.now(), lastApi = Date.now();

    /* ---------- server ---------- */
    async function api(method, url, body) {
        let r;
        try {
            r = await fetch(url, { method, credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: body ? JSON.stringify(body) : undefined });
        } catch (e) { return { ok: false, status: 0, data: { error: 'No connection. Nothing was recorded' } }; }
        let data = {};
        try { data = await r.json(); } catch (e) { data = { error: `Something went wrong (${r.status})` }; }
        lastApi = Date.now();
        if (r.status === 401 && data.code === 'no_person' && screen !== 'who' && screen !== 'pin') {
            signedOut('You were signed out after a quiet spell. Scan your badge again.');
        }
        if (r.status === 401 && data.code === 'no_station') location.href = '/station/pair';
        return { ok: r.ok, status: r.status, data };
    }

    /* ---------- sound + buzz ---------- */
    let audio = null;
    function beep(kind) {
        try {
            audio = audio || new (window.AudioContext || window.webkitAudioContext)();
            const tones = { ok: [880, 1175], back: [660, 880], warn: [660, 520], err: [220, 180, 160], hi: [523, 784] }[kind] || [880];
            tones.forEach((f, i) => {
                const o = audio.createOscillator(), g = audio.createGain();
                o.frequency.value = f; o.type = kind === 'err' ? 'square' : 'sine';
                g.gain.value = kind === 'err' ? 0.06 : 0.12; o.connect(g); g.connect(audio.destination);
                const t = audio.currentTime + i * 0.13;
                o.start(t); o.stop(t + (kind === 'err' ? 0.18 : 0.11));
            });
        } catch (e) {}
        try { navigator.vibrate && navigator.vibrate(kind === 'err' ? [90, 60, 90] : 60); } catch (e) {}
    }

    /* ---------- screens ---------- */
    function show(name) {
        screen = name;
        $$('.ks-screen').forEach((s) => { s.hidden = s.id !== 'scr' + name[0].toUpperCase() + name.slice(1); });
        $('#ksWho').hidden = !person;
        $('#ksChangeEvent').hidden = name !== 'scan';
        $('#ksEventLabel').textContent = name === 'scan' ? eventLabel() : '';
    }
    const eventLabel = () => !event ? '' : event === 'return' ? 'Bringing gear back' : `For ${event.title}`;
    function msg(el, kind, text) { el.className = `ks-msg ${kind}`; el.textContent = text; el.hidden = !text; }

    function signedOut(text) {
        person = null; event = null; closeIdle();
        show('who');
        msg($('#whoMsg'), text ? 'info' : '', text || '');
    }

    /* ---------- 1. identify ---------- */
    async function identify(body) {
        if (busy) return;
        busy = true;
        const r = await api('POST', '/station/api/identify', body);
        busy = false;
        if (!r.ok) {
            beep('err');
            if (screen === 'pin') { msg($('#pinMsg'), 'err', r.data.error); pin = ''; paintPin(); }
            else { show('who'); msg($('#whoMsg'), 'err', r.data.error || 'Not recognised'); }
            return;
        }
        beep('hi');
        person = r.data.person; event = null;
        msg($('#whoMsg'), '', '');
        $('#ksPerson').textContent = person.name;
        renderEvents(r.data.events);
        show('event');
    }

    $('#ksUsePin').addEventListener('click', async () => {
        show('pin');
        $('#pinTitle').textContent = 'Who are you?';
        $('#pinPadWrap').hidden = true; $('#pinPeople').hidden = false;
        $('#pinPeople').innerHTML = '<p class="sw-muted">Loading…</p>';
        const r = await api('GET', '/station/api/people');
        const people = (r.data.people || []);
        $('#pinPeople').innerHTML = people.length ? people.map((p) =>
            `<button type="button" class="ks-person" data-id="${p.id}">${esc(p.name)}</button>`).join('')
            : '<p class="sw-muted">Nobody has set a PIN yet. Set one in ShowWise under Settings › Scan badge, or scan your badge.</p>';
        $$('#pinPeople [data-id]').forEach((b) => b.addEventListener('click', () => pickPerson(b.dataset.id, b.textContent)));
    });
    $('#pinBack').addEventListener('click', () => signedOut(''));

    let pin = '', pinUser = null;
    function pickPerson(id, name) {
        pinUser = parseInt(id, 10); pin = '';
        $('#pinTitle').textContent = `Hi ${name}. Enter your PIN`;
        $('#pinPeople').hidden = true; $('#pinPadWrap').hidden = false;
        msg($('#pinMsg'), '', ''); paintPin();
    }
    function paintPin() {
        $('#pinDots').innerHTML = Array.from({ length: Math.max(4, pin.length) }, (_, i) =>
            `<span class="${i < pin.length ? 'on' : ''}"></span>`).join('');
    }
    function pinKey(d) {
        if (d === 'del') pin = pin.slice(0, -1);
        else if (d === 'ok') { if (pin.length >= 4) identify({ user_id: pinUser, pin }); return; }
        else if (pin.length < 8) pin += d;
        paintPin();
    }
    $$('#pinPad button').forEach((b) => b.addEventListener('click', () => pinKey(b.dataset.d)));

    /* ---------- 2. event ---------- */
    function renderEvents(events) {
        $('#evGreet').textContent = `Hi ${person.name}`;
        const today = events.filter((e) => e.today && !e.archived);
        const rows = [`<button type="button" class="ks-choice back" data-ev="return">
                <i class="fas fa-arrow-right-to-bracket"></i><span><strong>Bring gear back</strong><small>Scan anything that’s coming back in</small></span></button>`]
            .concat(events.map((e) => `<button type="button" class="ks-choice${e.today && !e.archived ? ' today' : ''}" data-ev="${e.id}">
                <i class="fas fa-${e.archived ? 'clock-rotate-left' : 'calendar-day'}"></i>
                <span><strong>${esc(e.title)}</strong><small>${esc([e.date, e.location, e.today ? 'today' : '', e.archived ? 'finished' : '',
                    e.out ? `${e.out} out` : ''].filter(Boolean).join(' · '))}</small></span></button>`));
        $('#evList').innerHTML = rows.join('');
        const byId = Object.fromEntries(events.map((e) => [String(e.id), e]));
        $$('#evList [data-ev]').forEach((b) => b.addEventListener('click', () => {
            event = b.dataset.ev === 'return' ? 'return' : byId[b.dataset.ev];
            startScanning();
        }));
        if (today.length === 1) $(`#evList [data-ev="${today[0].id}"]`).classList.add('suggested');
    }
    $('#ksChangeEvent').addEventListener('click', async () => {
        const r = await api('GET', '/station/api/events');
        if (r.ok) { renderEvents(r.data.events); show('event'); }
    });

    /* ---------- 3. scan ---------- */
    const ICON = { ok: 'arrow-right-from-bracket', back: 'arrow-right-to-bracket', warn: 'circle-question', err: 'circle-xmark', idle: 'qrcode', info: 'circle-info' };
    function result(kind, title, sub, notes, actions, extra) {
        const box = $('#ksResult');
        box.innerHTML = `<div class="co-big ks-big ${kind}">
            <div class="co-big-word"><i class="fas fa-${ICON[kind]}"></i> <span>${esc(title)}</span></div>
            ${sub ? `<div class="co-big-item">${esc(sub)}</div>` : ''}
            ${notes && notes.length ? `<ul class="co-big-notes">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
            ${extra || ''}
            ${actions && actions.length ? `<div class="co-big-actions">${actions.map((a, i) => `<button type="button" class="btn ${a.cls || 'btn-secondary'} ks-btn" data-act="${i}">${a.icon ? `<i class="fas fa-${a.icon}"></i> ` : ''}${esc(a.label)}</button>`).join('')}</div>` : ''}
        </div>`;
        (actions || []).forEach((a, i) => $(`[data-act="${i}"]`, box).addEventListener('click', a.run));
    }
    const ready = () => result('idle', what === 'look' ? 'Scan a label to look it up' : event === 'return' ? 'Scan gear coming back' : 'Scan the next label',
        what === 'look' ? 'Nothing is checked out or in.' : event === 'return' ? 'Each scan checks one item back in.' : 'Scan once as it goes out. Scan again when it comes back.');

    function logRow(kind, text) {
        const li = document.createElement('li');
        li.className = kind;
        li.innerHTML = `<i class="fas fa-${ICON[kind] || 'circle'}"></i> ${esc(text)} <time>${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>`;
        $('#ksLog').prepend(li);
        while ($('#ksLog').children.length > 30) $('#ksLog').lastChild.remove();
    }

    function startScanning() {
        what = 'move';
        $('#ksLog').innerHTML = '';
        $('#whatMoveLabel').textContent = event === 'return' ? 'Bring back' : 'Check out / in';
        setWhat('move');
        show('scan');
    }
    function setWhat(w) {
        what = w;
        $$('.ks-what button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.what === w ? 'true' : 'false'));
        ready();
    }
    $$('.ks-what button').forEach((b) => b.addEventListener('click', () => setWhat(b.dataset.what)));

    const eventId = () => (event && event !== 'return' ? event.id : null);
    const baseMode = () => (event === 'return' ? 'return' : 'auto');

    async function submit(body) {
        if (busy) return;
        busy = true;
        const sent = Object.assign({ event_id: eventId(), mode: baseMode() }, body);
        const { ok, status, data } = await api('POST', '/station/api/scan', sent);
        busy = false;
        if (status === 401) return;
        const u = data.unit, label = u ? `${u.asset_tag} · ${u.equipment_name}` : '';
        if (ok) {
            const warns = (data.warnings || []).map((w) => w.message);
            const back = data.action === 'return';
            beep(warns.length ? 'warn' : back ? 'back' : 'ok');
            logRow(back ? 'back' : 'ok', `${back ? 'Back' : 'Out'}: ${label}`);
            result(back ? 'back' : 'ok', back ? 'Back in' : 'Going out', label, warns.concat(data.info ? [data.info] : []),
                data.quarantine ? [] : [undoButton(back ? 'return' : 'out', data.checkout.id),
                                        problemButton(u, data.checkout.event_id)]);
            return;
        }
        if (data.conflict === 'choose_unit') { beep('warn'); return chooseUnit(data); }
        if (data.conflict === 'choose_quantity') { beep('warn'); return chooseQuantity(data); }
        if (data.needs_confirm) {
            beep('warn');
            const elsewhere = (data.blockers || []).some((b) => b.code === 'out_elsewhere');
            return result('warn', elsewhere ? 'Is this coming back?' : 'Check before it goes', label,
                (data.blockers || []).map((b) => b.message), elsewhere ? [
                    { label: 'Yes, it’s back', cls: 'btn-primary', icon: 'arrow-right-to-bracket', run: () => submit(Object.assign({}, body, { mode: 'return' })) },
                    { label: 'No, it’s going out', run: () => submit(Object.assign({}, body, { force: true, mode: 'out' })) },
                ] : [
                    { label: 'Take it anyway', cls: 'btn-primary', run: () => submit(Object.assign({}, body, { force: true, mode: 'out' })) },
                    { label: 'Leave it', run: ready },
                ]);
        }
        beep('err');
        const title = data.conflict === 'quarantined' ? 'Don’t take this one'
            : data.conflict === 'not_found' ? 'Label not recognised'
            : data.conflict === 'not_out' ? 'That one isn’t out' : status === 0 ? 'No connection' : 'That didn’t work';
        logRow('err', `${title}${label ? ': ' + label : ''}`);
        result('err', title, label, [data.error || 'Could not record that scan']);
    }

    function undoButton(action, cid) {
        return { label: 'Undo', icon: 'rotate-left', run: async () => {
            const r = await api('POST', `/station/api/undo/${cid}`, { action });
            if (r.ok) { beep('warn'); logRow('warn', r.data.message); result('idle', 'Undone', r.data.message); }
            else { beep('err'); result('err', 'Could not undo', r.data.error); }
        } };
    }
    function problemButton(unit, evId) {
        return { label: 'Report a problem', icon: 'triangle-exclamation', run: () => {
            result('warn', 'What’s wrong with it?', `${unit.asset_tag} · ${unit.equipment_name}`, null, [
                { label: 'Take it out of use', cls: 'btn-primary', icon: 'ban', run: async () => {
                    const reason = ($('#ksReason').value || '').trim();
                    if (!reason) { $('#ksReason').focus(); return; }
                    const r = await api('POST', `/station/api/problem/${unit.id}`, { reason, event_id: evId });
                    if (r.ok) { beep('warn'); logRow('warn', `Out of use: ${unit.asset_tag}`); result('warn', 'Taken out of use', unit.asset_tag, [reason, 'Put it to one side. It can’t go out until someone has checked it.']); }
                    else { beep('err'); result('err', 'Could not report it', unit.asset_tag, [r.data.error]); }
                } },
                { label: 'Cancel', run: ready },
            ], '<textarea id="ksReason" class="sw-input ks-reason" rows="2" maxlength="500" placeholder="e.g. cable is cut near the plug"></textarea>');
            $('#ksReason').focus();
        } };
    }

    function chooseUnit(data) {
        const rows = data.units.map((u) => {
            let note = '', btn = '';
            if (u.out_here) { note = 'out on this event'; btn = `<button type="button" class="btn btn-secondary ks-btn-sm" data-pick="${u.id}" data-mode="return">Back in</button>`; }
            else if (u.status === 'quarantined') note = 'out of use';
            else if (event === 'return') { if (u.out_event_title) { note = `out on ${u.out_event_title}`; btn = `<button type="button" class="btn btn-secondary ks-btn-sm" data-pick="${u.id}" data-mode="return">Back in</button>`; } else note = 'in storage'; }
            else {
                if (u.status !== 'available') note = u.status_label.toLowerCase();
                else if (u.out_event_title) note = `out on ${u.out_event_title}`;
                else if (u.allocated_here) note = 'on the pick list';
                btn = `<button type="button" class="btn ${u.allocated_here ? 'btn-primary' : 'btn-secondary'} ks-btn-sm" data-pick="${u.id}" data-mode="out">Take out</button>`;
            }
            return `<li><div class="main"><code>${esc(u.asset_tag)}</code>${u.serial_number ? ` <span class="meta">S/N ${esc(u.serial_number)}</span>` : ''}
                ${note ? `<div class="meta">${esc(note)}</div>` : ''}</div>${btn}</li>`;
        }).join('');
        result('warn', `Which ${data.equipment.name}?`, 'That label is for the whole set. Tap the one in your hand, or scan its own label.', null,
            [{ label: 'Cancel', run: ready }], `<ul class="co-list co-pick ks-pick">${rows}</ul>`);
        $$('#ksResult [data-pick]').forEach((b) => b.addEventListener('click', () =>
            submit({ unit_id: parseInt(b.dataset.pick, 10), mode: b.dataset.mode })));
    }

    function chooseQuantity(data, force) {
        const eq = data.equipment;
        if (event === 'return') {
            return result('err', `${eq.name} is counted, not scanned`, 'Count-only gear is checked back in from the Scan gear page in ShowWise.');
        }
        let n = 1;
        const paint = () => { $('#ksQty').textContent = n; };
        result('warn', `How many ${eq.name}?`, `${data.available} of ${data.owned} should be in storage`, null, [
            { label: 'Take them out', cls: 'btn-primary', icon: 'arrow-right-from-bracket', run: async () => {
                const r = await api('POST', '/station/api/bulk', { event_id: eventId(), equipment_id: eq.id, quantity: n, force: !!force });
                if (r.ok) { beep('ok'); logRow('ok', r.data.message); result('ok', 'Going out', r.data.message); }
                else if (r.data.needs_confirm) {
                    beep('warn');
                    result('warn', 'Are you sure?', r.data.error, null, [
                        { label: `Take ${n} anyway`, cls: 'btn-primary', run: async () => {
                            const r2 = await api('POST', '/station/api/bulk', { event_id: eventId(), equipment_id: eq.id, quantity: n, force: true });
                            if (r2.ok) { beep('ok'); logRow('ok', r2.data.message); result('ok', 'Going out', r2.data.message); }
                            else { beep('err'); result('err', 'That didn’t work', r2.data.error); }
                        } },
                        { label: 'Cancel', run: ready }]);
                } else { beep('err'); result('err', 'That didn’t work', r.data.error); }
            } },
            { label: 'Cancel', run: ready },
        ], `<div class="ks-qty"><button type="button" class="btn btn-secondary" id="ksMinus" aria-label="Fewer">−</button>
              <span id="ksQty">1</span><button type="button" class="btn btn-secondary" id="ksPlus" aria-label="More">+</button></div>`);
        $('#ksMinus').addEventListener('click', () => { n = Math.max(1, n - 1); paint(); });
        $('#ksPlus').addEventListener('click', () => { n += 1; paint(); });
    }

    async function lookup(code) {
        if (busy) return;
        busy = true;
        const r = await api('POST', '/station/api/lookup', { code });
        busy = false;
        if (r.status === 401) return;
        if (!r.ok) { beep('err'); return result('err', r.status === 0 ? 'No connection' : 'Label not recognised', code, [r.data.error]); }
        beep('hi');
        const eq = r.data.equipment, u = r.data.unit, s = eq.summary || {}, co = u && u.checkout;
        const where = !u ? null : u.quarantine ? `Out of use: ${u.quarantine.reason}` : co ? `Out on ${co.event_title} since ${co.checked_out_at}` : 'In storage';
        result('info', eq.name, u ? `${u.asset_tag} · ${u.state_label || u.status}` : 'Label for the whole set',
            [where, `Lives in: ${eq.location || 'no location set'}`, s.owned != null ? `${s.available} of ${s.owned} available` : null].filter(Boolean));
    }

    /* ---------- every code, from camera, typing or a handheld scanner ---------- */
    function handleCode(raw) {
        const code = String(raw || '').trim();
        if (!code) return;
        activity();
        if (isBadge(code)) {
            if (person && screen !== 'who') { person = null; }
            return identify({ badge: code });
        }
        if (screen === 'who' || screen === 'pin') {
            beep('err');
            show('who');
            return msg($('#whoMsg'), 'err', 'Scan your badge first, then the gear.');
        }
        if (screen === 'event') { beep('err'); return; }
        if (what === 'look') return lookup(code);
        return submit({ code });
    }

    // Keyboard-wedge scanners type fast and press Enter. Catch that anywhere on the page
    // (except in a real text box, which handles its own Enter).
    let buf = '', lastKey = 0;
    document.addEventListener('keydown', (e) => {
        const t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
        activity();
        if (e.key === 'Enter') {
            if (buf.length >= 3) { e.preventDefault(); handleCode(buf); }
            else if (screen === 'pin' && !$('#pinPadWrap').hidden) pinKey('ok');
            buf = '';
            return;
        }
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            const now = performance.now();
            if (now - lastKey > 250) buf = '';
            buf += e.key; lastKey = now;
            if (screen === 'pin' && !$('#pinPadWrap').hidden && /^[0-9]$/.test(e.key) && buf.length === 1) pinKey(e.key);
        } else if (e.key === 'Backspace' && screen === 'pin') pinKey('del');
    });
    $('#ksTypeForm').addEventListener('submit', (e) => {
        e.preventDefault();
        const v = $('#ksType').value; $('#ksType').value = ''; $('#ksType').blur();
        handleCode(v);
    });

    /* ---------- camera ---------- */
    let scanner = null;
    function camState(live, text) {
        $('#camDot').classList.toggle('live', live); $('#camText').textContent = text;
        $('#ksCam').classList.toggle('live', live);
        $('#camToggle').textContent = scanner && scanner.scanning ? 'Stop camera' : 'Start camera';
    }
    function setupCamera() {
        if (!window.SWScanner) { camState(false, 'Camera scanner could not load. Use a handheld scanner or type the code'); $('#camToggle').hidden = true; return; }
        $('#ksCam').innerHTML = '<div class="sw-cam"><div class="sw-cam-idle"><i class="fas fa-camera"></i><span>Camera is off</span></div><div class="sw-cam-frame"></div></div>';
        const cam = $('#ksCam .sw-cam');
        scanner = window.SWScanner.create({ container: cam, continuous: true, repeatMs: 3000,
            onCode: handleCode, onState: (live, text) => { camState(live, text); $('.sw-cam-idle', cam).style.display = scanner && scanner.scanning ? 'none' : ''; } });
        $('#camToggle').addEventListener('click', () => {
            const on = !scanner.scanning;
            try { localStorage.setItem('showwise-station-camera', on ? '1' : '0'); } catch (e) {}
            on ? scanner.start() : scanner.stop();
        });
        let want = false;
        try { want = localStorage.getItem('showwise-station-camera') === '1'; } catch (e) {}
        if (want) scanner.start();
    }

    /* ---------- sign out after a quiet spell ---------- */
    let idleTick = null;
    function activity() {
        lastActive = Date.now();
        if (!$('#ksIdle').hidden) closeIdle();
        // Keep the server's timer in step when people are busy on screen without scanning
        if (person && Date.now() - lastApi > IDLE / 2) api('GET', '/station/api/events');
    }
    function closeIdle() { $('#ksIdle').hidden = true; }
    async function signOut(text) {
        await api('POST', '/station/api/logout');
        signedOut(text);
    }
    setInterval(() => {
        if (!person) return;
        const left = IDLE - (Date.now() - lastActive);
        if (left <= 0) { beep('warn'); signOut('Signed out after a quiet spell.'); return; }
        if (left <= WARN) { $('#ksIdle').hidden = false; $('#ksIdleN').textContent = Math.ceil(left / 1000); }
    }, 500);
    ['pointerdown', 'touchstart'].forEach((ev) => document.addEventListener(ev, () => activity(), { passive: true }));
    $('#ksStay').addEventListener('click', () => { closeIdle(); api('GET', '/station/api/events'); });
    $('#ksDone').addEventListener('click', () => { beep('back'); signOut('Signed out. Thanks!'); });

    $('#ksTheme').addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('showwise-theme', next); } catch (e) {}
    });

    /* ---------- start ---------- */
    (async function init() {
        setupCamera();
        const r = await api('GET', '/station/api/whoami');
        if (r.ok && r.data.person) {
            person = r.data.person;
            $('#ksPerson').textContent = person.name;
            const ev = await api('GET', '/station/api/events');
            if (ev.ok) { renderEvents(ev.data.events); show('event'); return; }
        }
        show('who');
    })();
})();
