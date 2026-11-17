"""routes/scan_station.py — scan station (kiosk) mode for a tablet or PC at the store-room door.

How it fits together
--------------------
* An admin registers a station and gets a one-time pairing code (valid 30 minutes).
  Entering it on the device swaps it for a long-lived device token, kept in an
  http-only cookie scoped to /station. Only the token's hash is stored, so revoking
  the station (or pairing another device) cuts the old one off on its next request.
* The device token is not a login. It never sets flask-login's session, so every
  normal page still sees an anonymous visitor. It can only reach /station/*.
* A person identifies at the station with their badge QR (from Settings > Scan badge)
  or their name and a short PIN. The person lives in the session next to the station
  id and is forgotten after the station's idle time.
* Scans run the existing check-out code in routes/unit_tracking.py as that person
  (current_user is swapped for the one call), so quarantine rules, pick-list checks
  and "who scanned it" all behave exactly as on the Scan gear page.
"""

import base64
import hashlib
import io
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, render_template, request, jsonify, redirect, url_for,
                   session, g, abort, make_response)
from flask_login import login_required, current_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash

from decorators import admin_required
from extensions import db
from models import ScanStation, StationBadge, User, UnitCheckout

scan_station_bp = Blueprint('scan_station', __name__)

COOKIE        = 'sw_station'
COOKIE_PATH   = '/station'
PERSON_KEY    = 'station_person'
PAIRING_TTL   = timedelta(minutes=30)
PIN_MAX_FAILS = 5
PIN_LOCK      = timedelta(minutes=5)
IDLE_MIN, IDLE_MAX, IDLE_DEFAULT = 30, 900, 90
BADGE_PREFIX  = 'SWB'
_PAIR_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'      # no 0/O, 1/I


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _utcnow():
    return datetime.utcnow()


def _clean_pair_code(code):
    return ''.join(ch for ch in (code or '').upper() if ch.isalnum())


def _new_pair_code():
    raw = ''.join(secrets.choice(_PAIR_ALPHABET) for _ in range(8))
    return f'{raw[:4]}-{raw[4:]}'


def _idle(value, default=IDLE_DEFAULT):
    try:
        return max(IDLE_MIN, min(IDLE_MAX, int(value)))
    except (TypeError, ValueError):
        return default


def may_use_station(user):
    """Crew can scan gear; cast-only accounts can't (same rule as crew_required)."""
    return bool(user) and not getattr(user, 'is_cast', False) and \
        (getattr(user, 'user_role', 'crew') or 'crew') != 'cast'


# ---------------------------------------------------------------------------
# Station + person resolution
# ---------------------------------------------------------------------------

_MISSING = object()


def current_station():
    """The paired, not revoked station this request comes from, or None."""
    cached = getattr(request, '_scan_station', _MISSING)        # per request, not per app context
    if cached is not _MISSING:
        return cached
    st = None
    tok = request.cookies.get(COOKIE)
    if tok and len(tok) <= 200:
        st = ScanStation.query.filter_by(token_hash=_hash(tok)).first()
        if st and st.revoked_at is not None:
            st = None
        if st and (st.last_seen_at is None or _utcnow() - st.last_seen_at > timedelta(minutes=1)):
            st.last_seen_at = _utcnow()
            db.session.commit()
    request._scan_station = st
    return st


def station_person(station):
    """The person signed in at this station, or None (also after the idle time)."""
    d = session.get(PERSON_KEY)
    if not d or d.get('station') != station.id:
        return None
    if time.time() - float(d.get('at', 0)) > (station.idle_seconds or IDLE_DEFAULT):
        session.pop(PERSON_KEY, None)
        return None
    user = db.session.get(User, int(d.get('uid', 0)))
    if not may_use_station(user):
        session.pop(PERSON_KEY, None)
        return None
    return user


def _sign_in(station, user):
    session[PERSON_KEY] = {'station': station.id, 'uid': user.id, 'at': time.time()}
    session.modified = True


def _touch():
    d = session.get(PERSON_KEY)
    if d:
        d['at'] = time.time()
        session[PERSON_KEY] = d
        session.modified = True


def station_required(f):
    """A paired station; JSON 401 for the API, otherwise the pairing page."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        st = current_station()
        if st is None:
            if request.path.startswith('/station/api/'):
                return jsonify({'error': 'This device is not set up as a scan station',
                                'code': 'no_station'}), 401
            return redirect(url_for('scan_station.pair_page'))
        return f(st, *args, **kwargs)
    return wrapper


def person_required(f):
    """A paired station AND someone identified on it (refreshes the idle timer)."""
    @wraps(f)
    @station_required
    def wrapper(st, *args, **kwargs):
        user = station_person(st)
        if user is None:
            return jsonify({'error': 'Scan your badge first', 'code': 'no_person'}), 401
        _touch()
        return f(st, user, *args, **kwargs)
    return wrapper



def run_as(user, view, *args, **kwargs):
    """Call an existing (login_required) view with current_user set to *user* for just
    this call. The browser session is never logged in."""
    saved = g.get('_login_user', _MISSING)
    g._login_user = user
    try:
        return view(*args, **kwargs)
    finally:
        if saved is _MISSING:
            g.pop('_login_user', None)
        else:
            g._login_user = saved


def _no_store(resp):
    resp = make_response(resp)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ---------------------------------------------------------------------------
# Device: pairing and the kiosk page
# ---------------------------------------------------------------------------

@scan_station_bp.route('/station')
@station_required
def kiosk(st):
    # A shared device must not stay signed in to the full app.
    if current_user.is_authenticated:
        logout_user()
    return _no_store(render_template('station/kiosk.html', station=st,
                                     idle_seconds=st.idle_seconds or IDLE_DEFAULT))


@scan_station_bp.route('/station/pair', methods=['GET', 'POST'])
def pair_page():
    error = None
    code = request.values.get('code', '')
    if request.method == 'POST':
        clean = _clean_pair_code(code)
        st = ScanStation.query.filter_by(pairing_hash=_hash(clean)).first() if len(clean) == 8 else None
        if st is None or st.revoked_at is not None or not st.pairing_expires_at \
                or st.pairing_expires_at < _utcnow():
            error = 'That code is wrong or has expired. Ask an admin for a new one.'
        else:
            token = secrets.token_urlsafe(32)
            st.token_hash = _hash(token)
            st.pairing_hash = None
            st.pairing_expires_at = None
            st.paired_at = st.last_seen_at = _utcnow()
            db.session.commit()
            if current_user.is_authenticated:
                logout_user()
            session.pop(PERSON_KEY, None)
            resp = redirect(url_for('scan_station.kiosk'))
            resp.set_cookie(COOKIE, token, max_age=5 * 365 * 24 * 3600, path=COOKIE_PATH,
                            httponly=True, samesite='Lax', secure=request.is_secure)
            return resp
    st = current_station()
    return _no_store(render_template('station/pair.html', error=error, code=code,
                                     paired=st)), (400 if error else 200)


@scan_station_bp.route('/station/forget', methods=['POST'])
def forget_device():
    """Unpair this device (the station record stays; an admin can pair it again)."""
    session.pop(PERSON_KEY, None)
    resp = redirect(url_for('scan_station.pair_page'))
    resp.delete_cookie(COOKIE, path=COOKIE_PATH)
    return resp


# ---------------------------------------------------------------------------
# Device API: who is scanning
# ---------------------------------------------------------------------------

@scan_station_bp.route('/station/api/whoami')
@station_required
def api_whoami(st):
    user = station_person(st)
    return _no_store(jsonify({'station': {'id': st.id, 'name': st.name,
                                          'idle_seconds': st.idle_seconds or IDLE_DEFAULT},
                              'person': {'name': user.shown_name} if user else None}))


@scan_station_bp.route('/station/api/people')
@station_required
def api_people(st):
    """People who can sign in with a PIN at this station."""
    rows = StationBadge.query.filter(StationBadge.pin_hash.isnot(None)).all()
    people = sorted(({'id': b.user.id, 'name': b.user.shown_name} for b in rows
                     if b.user and may_use_station(b.user)), key=lambda p: p['name'].lower())
    return _no_store(jsonify({'people': people}))


def _identified(st, user):
    _sign_in(st, user)
    from utils import log_security_event
    log_security_event('SCAN_STATION_SIGN_IN', username=user.username,
                       description=f'Signed in at scan station "{st.name}"')
    return _no_store(jsonify({'success': True, 'person': {'name': user.shown_name},
                              'events': _kiosk_events()}))


@scan_station_bp.route('/station/api/identify', methods=['POST'])
@station_required
def api_identify(st):
    """Body: {badge} (the scanned badge QR) or {user_id, pin}."""
    data = request.get_json(silent=True) or {}
    session.pop(PERSON_KEY, None)
    if data.get('badge'):
        code = str(data['badge']).strip().upper()
        badge = StationBadge.query.filter_by(badge_code=code).first() \
            if code.startswith(BADGE_PREFIX) and len(code) <= 64 else None
        if not badge or not may_use_station(badge.user):
            return jsonify({'error': 'Badge not recognised', 'code': 'bad_badge'}), 401
        return _identified(st, badge.user)

    try:
        uid = int(data.get('user_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Pick your name'}), 400
    pin = str(data.get('pin') or '')
    badge = StationBadge.query.filter_by(user_id=uid).first()
    if not badge or not badge.pin_hash or not may_use_station(badge.user):
        return jsonify({'error': 'That person has no PIN set', 'code': 'bad_pin'}), 401
    now = _utcnow()
    if badge.locked_until and badge.locked_until > now:
        mins = max(1, int((badge.locked_until - now).total_seconds() // 60) + 1)
        return jsonify({'error': f'Too many wrong PINs. Try again in {mins} min or scan your badge',
                        'code': 'locked'}), 423
    if not check_password_hash(badge.pin_hash, pin):
        badge.pin_failures = (badge.pin_failures or 0) + 1
        if badge.pin_failures >= PIN_MAX_FAILS:
            badge.pin_failures = 0
            badge.locked_until = now + PIN_LOCK
        db.session.commit()
        return jsonify({'error': 'Wrong PIN', 'code': 'bad_pin'}), 401
    badge.pin_failures = 0
    badge.locked_until = None
    db.session.commit()
    return _identified(st, badge.user)


@scan_station_bp.route('/station/api/logout', methods=['POST'])
@station_required
def api_logout(st):
    session.pop(PERSON_KEY, None)
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Device API: events and scanning (all as the identified person)
# ---------------------------------------------------------------------------

def _kiosk_events():
    from routes.picklist import _split_events
    from routes.unit_tracking import _event_brief, _open_counts
    current, archived = _split_events()
    counts = _open_counts()
    today = datetime.now().date()
    stale = [e for e in archived if counts.get(e.id)]
    out = []
    for e in current[:12] + stale[:6]:
        d = _event_brief(e)
        d['out'] = counts.get(e.id, 0)
        d['today'] = bool(e.event_date and e.event_date.date() == today)
        out.append(d)
    return out


@scan_station_bp.route('/station/api/events')
@person_required
def api_events(st, user):
    return _no_store(jsonify({'events': _kiosk_events()}))


@scan_station_bp.route('/station/api/scan', methods=['POST'])
@person_required
def api_scan(st, user):
    """Same body and answers as /equipment/checkout/scan."""
    from routes.unit_tracking import checkout_scan
    return run_as(user, checkout_scan)


@scan_station_bp.route('/station/api/bulk', methods=['POST'])
@person_required
def api_bulk(st, user):
    """Same body and answers as /equipment/checkout/bulk."""
    from routes.unit_tracking import bulk_checkout
    return run_as(user, bulk_checkout)


@scan_station_bp.route('/station/api/undo/<int:cid>', methods=['POST'])
@person_required
def api_undo(st, user, cid):
    from routes.unit_tracking import undo_scan
    return run_as(user, undo_scan, cid)


@scan_station_bp.route('/station/api/problem/<int:uid>', methods=['POST'])
@person_required
def api_problem(st, user, uid):
    """Report a problem: takes the item out of use (body: {reason, event_id?}).
    If it is still checked out it is returned first."""
    from routes.unit_tracking import quarantine
    from models import EquipmentUnit
    unit = db.session.get(EquipmentUnit, uid)
    if unit and unit.open_checkout and unit.status not in ('quarantined', 'retired', 'lost') \
            and (request.get_json(silent=True) or {}).get('reason', '').strip():
        from routes.unit_tracking import return_checkout
        run_as(user, return_checkout, unit.open_checkout.id)
    return run_as(user, quarantine, uid)


@scan_station_bp.route('/station/api/lookup', methods=['POST'])
@person_required
def api_lookup(st, user):
    """Look a label up without recording anything."""
    from routes.unit_tracking import scan_lookup
    return run_as(user, scan_lookup)


# ---------------------------------------------------------------------------
# Admin: register, pair and revoke stations
# ---------------------------------------------------------------------------

def _station_dict(st):
    status = 'revoked' if st.revoked_at else 'paired' if st.token_hash else \
        'waiting' if st.pairing_expires_at and st.pairing_expires_at > _utcnow() else 'not_paired'
    fmt = lambda d: d.strftime('%d %b %Y, %H:%M') + ' UTC' if d else None
    return {'id': st.id, 'name': st.name, 'idle_seconds': st.idle_seconds or IDLE_DEFAULT,
            'status': status, 'created_by': st.created_by, 'created_at': fmt(st.created_at),
            'paired_at': fmt(st.paired_at), 'last_seen_at': fmt(st.last_seen_at),
            'revoked_at': fmt(st.revoked_at)}


def _issue_pairing(st):
    code = _new_pair_code()
    st.pairing_hash = _hash(_clean_pair_code(code))
    st.pairing_expires_at = _utcnow() + PAIRING_TTL
    return {'code': code, 'url': url_for('scan_station.pair_page', code=code, _external=True),
            'expires_minutes': int(PAIRING_TTL.total_seconds() // 60)}


@scan_station_bp.route('/admin/stations')
@login_required
@admin_required
def admin_page():
    return render_template('admin/stations.html')


@scan_station_bp.route('/admin/stations/api')
@login_required
@admin_required
def admin_list():
    rows = ScanStation.query.order_by(ScanStation.revoked_at.isnot(None), ScanStation.name).all()
    return _no_store(jsonify({'stations': [_station_dict(s) for s in rows]}))


@scan_station_bp.route('/admin/stations', methods=['POST'])
@login_required
@admin_required
def admin_create():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:100]
    if not name:
        return jsonify({'error': 'Give the station a name, e.g. "Store room door"'}), 400
    st = ScanStation(name=name, idle_seconds=_idle(data.get('idle_seconds')),
                     created_by=current_user.username)
    db.session.add(st)
    pairing = _issue_pairing(st)
    db.session.commit()
    from utils import log_security_event
    log_security_event('SCAN_STATION_CREATED', username=current_user.username,
                       description=f'Registered scan station "{name}"')
    return jsonify({'success': True, 'station': _station_dict(st), 'pairing': pairing})


@scan_station_bp.route('/admin/stations/<int:sid>', methods=['PUT'])
@login_required
@admin_required
def admin_update(sid):
    st = ScanStation.query.get_or_404(sid)
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()[:100]
        if not name:
            return jsonify({'error': 'Name can’t be empty'}), 400
        st.name = name
    if 'idle_seconds' in data:
        st.idle_seconds = _idle(data.get('idle_seconds'), st.idle_seconds or IDLE_DEFAULT)
    db.session.commit()
    return jsonify({'success': True, 'station': _station_dict(st)})


@scan_station_bp.route('/admin/stations/<int:sid>/pair', methods=['POST'])
@login_required
@admin_required
def admin_pair(sid):
    """A fresh pairing code. The device that uses it replaces any device paired before."""
    st = ScanStation.query.get_or_404(sid)
    if st.revoked_at:
        return jsonify({'error': 'This station was revoked. Register a new one'}), 409
    pairing = _issue_pairing(st)
    db.session.commit()
    return jsonify({'success': True, 'station': _station_dict(st), 'pairing': pairing})


@scan_station_bp.route('/admin/stations/<int:sid>/revoke', methods=['POST'])
@login_required
@admin_required
def admin_revoke(sid):
    st = ScanStation.query.get_or_404(sid)
    st.revoked_at = st.revoked_at or _utcnow()
    st.token_hash = None
    st.pairing_hash = None
    st.pairing_expires_at = None
    db.session.commit()
    from utils import log_security_event
    log_security_event('SCAN_STATION_REVOKED', username=current_user.username,
                       description=f'Revoked scan station "{st.name}"')
    return jsonify({'success': True, 'station': _station_dict(st)})


@scan_station_bp.route('/admin/stations/<int:sid>', methods=['DELETE'])
@login_required
@admin_required
def admin_delete(sid):
    st = ScanStation.query.get_or_404(sid)
    db.session.delete(st)
    db.session.commit()
    return jsonify({'success': True})


# ---------------------------------------------------------------------------
# Personal badge: QR + PIN (Settings > Scan badge)
# ---------------------------------------------------------------------------

def _my_badge(create=True):
    b = StationBadge.query.filter_by(user_id=current_user.id).first()
    if b is None and create:
        b = StationBadge(user_id=current_user.id)
        db.session.add(b)
    if b is not None and not b.badge_code and create:
        b.badge_code = BADGE_PREFIX + base64.b32encode(secrets.token_bytes(15)).decode().rstrip('=')
        db.session.commit()
    return b


def _qr_png(data):
    import qrcode
    qr = qrcode.QRCode(version=None, box_size=10, border=3,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


@scan_station_bp.route('/settings/scan-badge')
@login_required
def badge_page():
    if not may_use_station(current_user):
        abort(403)
    b = _my_badge()
    return _no_store(render_template('crew/scan_badge.html', badge=b, qr=_qr_png(b.badge_code)))


@scan_station_bp.route('/settings/scan-badge/new', methods=['POST'])
@login_required
def badge_new():
    """A new badge code: the old badge (printout, screenshot) stops working."""
    if not may_use_station(current_user):
        abort(403)
    b = _my_badge()
    b.badge_code = None
    db.session.flush()
    _my_badge()
    return jsonify({'success': True})


@scan_station_bp.route('/settings/scan-badge/pin', methods=['POST', 'DELETE'])
@login_required
def badge_pin():
    if not may_use_station(current_user):
        abort(403)
    b = _my_badge()
    if request.method == 'DELETE':
        b.pin_hash = None
    else:
        pin = str((request.get_json(silent=True) or {}).get('pin') or '').strip()
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            return jsonify({'error': 'Your PIN must be 4 to 8 digits'}), 400
        if len(set(pin)) == 1 or pin in '0123456789' or pin in '9876543210':
            return jsonify({'error': 'Pick a PIN that is harder to guess'}), 400
        b.pin_hash = generate_password_hash(pin)
    b.pin_failures = 0
    b.locked_until = None
    db.session.commit()
    return jsonify({'success': True, 'has_pin': b.pin_hash is not None})
