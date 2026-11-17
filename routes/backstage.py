"""
routes/backstage.py
===================
Backstage calls for an event: the stage manager's call desk and a full-screen display
for a backstage TV or tablet.

* Call desk  (/events/<id>/calls)          - buttons for the standard calls plus custom text,
                                             and the event's call log.  Only people who can
                                             manage the event (admins, the event's creator).
* Display    (/events/<id>/calls/display)  - the current call, large, with a clock and a
                                             countdown to the event's next time.  Any logged-in
                                             crew account, so a kiosk login works.
* State      (/events/<id>/calls/state)    - JSON the display polls every couple of seconds.

The app runs on a couple of synchronous gunicorn workers, so the display polls a small JSON
endpoint instead of holding a server-sent-events connection open per screen.
"""

from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, url_for
from flask_login import current_user, login_required

from decorators import crew_required
from extensions import db
from models import BackstageCall, Event
from routes.events import ApiError, body, can_edit_event, clean_text
from services.event_times import times_for
from services.user_names import name_for

backstage_bp = Blueprint('backstage', __name__)

# key -> (button label, text shown on the display)
STANDARD_CALLS = {
    'half':         ('Half',                 'Half an hour, please'),
    'quarter':      ('Quarter',              'Quarter of an hour, please'),
    'five':         ('Five minutes',         'Five minutes, please'),
    'beginners':    ('Beginners',            'Beginners to the stage, please'),
    'interval_5':   ('Interval – 5 minutes', 'Five minutes until the end of the interval'),
    'act2_beginners': ('Act 2 beginners',    'Act 2 beginners to the stage, please'),
}
MAX_MESSAGE = 200
LOG_LIMIT = 50


def next_time(event: Event, now: datetime) -> dict | None:
    """The event's next scheduled start after ``now``: its own start or one of its labeled times."""
    starts = [('Start', event.event_date)] + [(t.label, t.start_time) for t in times_for(event)]
    upcoming = sorted((s for s in starts if s[1] > now), key=lambda s: s[1])
    if not upcoming:
        return None
    label, start = upcoming[0]
    return {'label': label, 'start': start.isoformat(timespec='seconds')}


def serialize_call(c: BackstageCall) -> dict:
    return {'id': c.id, 'kind': c.kind, 'message': c.message,
            'sent_by': name_for(c.sent_by), 'sent_at': c.sent_at.isoformat(timespec='seconds')}


def current_call(event: Event) -> BackstageCall | None:
    return (BackstageCall.query.filter_by(event_id=event.id)
            .order_by(BackstageCall.id.desc()).first())


def state_for(event: Event, with_log: bool = False) -> dict:
    now = datetime.now()
    latest = current_call(event)
    state = {
        'event': {'id': event.id, 'title': event.title},
        'now': now.isoformat(timespec='seconds'),
        'next': next_time(event, now),
        # The display only cares about the newest row; 'clear' blanks it.
        'last_id': latest.id if latest else 0,
        'call': serialize_call(latest) if latest and latest.kind != 'clear' else None,
    }
    if with_log:
        rows = (BackstageCall.query.filter_by(event_id=event.id)
                .order_by(BackstageCall.id.desc()).limit(LOG_LIMIT).all())
        state['log'] = [serialize_call(c) for c in rows]
    return state


def _no_store(resp):
    resp.headers['Cache-Control'] = 'no-store'
    return resp


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@backstage_bp.route('/events/<int:event_id>/calls')
@login_required
@crew_required
def call_desk(event_id):
    event = Event.query.get_or_404(event_id)
    if not can_edit_event(event):
        # Not allowed to give calls: show them what the backstage display shows.
        return redirect(url_for('backstage.display', event_id=event.id))
    presets = [{'key': k, 'label': v[0], 'text': v[1]} for k, v in STANDARD_CALLS.items()]
    return render_template('crew/backstage_calls.html', event=event, presets=presets,
                           state=state_for(event, with_log=True))


@backstage_bp.route('/events/<int:event_id>/calls/display')
@login_required
@crew_required
def display(event_id):
    event = Event.query.get_or_404(event_id)
    return render_template('crew/backstage_display.html', event=event, state=state_for(event))


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@backstage_bp.route('/events/<int:event_id>/calls/state')
@login_required
@crew_required
def call_state(event_id):
    event = Event.query.get_or_404(event_id)
    return _no_store(jsonify(state_for(event, with_log=can_edit_event(event))))


@backstage_bp.route('/events/<int:event_id>/calls', methods=['POST'])
@login_required
@crew_required
def send_call(event_id):
    event = Event.query.get_or_404(event_id)
    if not can_edit_event(event):
        raise ApiError('Only admins and the event creator can give backstage calls', 403)
    data = body()
    kind = str(data.get('kind') or 'custom').strip().lower()
    if kind == 'clear':
        message = ''
    elif kind == 'custom':
        message = clean_text(data.get('message'), 'Call', MAX_MESSAGE, required=True)
    elif kind in STANDARD_CALLS:
        message = STANDARD_CALLS[kind][1]
    else:
        raise ApiError('Unknown call')
    call = BackstageCall(event_id=event.id, kind=kind, message=message,
                         sent_by=current_user.username, sent_at=datetime.now())
    db.session.add(call)
    db.session.commit()
    return _no_store(jsonify({'success': True, 'call': serialize_call(call),
                              'state': state_for(event, with_log=True)}))
