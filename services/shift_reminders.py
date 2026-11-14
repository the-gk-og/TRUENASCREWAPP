"""services/shift_reminders.py — email people before their shift.

Runs from the scheduler once an hour. Each shift starting in the next 24 hours gets one
email to each person on it (unless they declined). Admins can turn the whole thing off
in Admin console → Notifications.
"""
from datetime import datetime, timedelta

from flask import current_app

from extensions import db
from models import Shift, ShiftAssignment
from services.settings_service import get_setting

SETTING = 'notify.shift_reminders.enabled'
WINDOW = timedelta(hours=24)


def reminders_enabled() -> bool:
    return bool(get_setting(SETTING))


def _when(shift) -> str:
    start, end = shift.shift_date, shift.shift_end_date
    text = start.strftime('%a %d %b, %I:%M %p').replace(' 0', ' ')
    if end and end.date() == start.date():
        text += ' – ' + end.strftime('%I:%M %p').lstrip('0')
    return text


def due_reminders(now=None):
    """(assignment, shift) pairs that should be emailed now."""
    now = now or datetime.now()
    return (db.session.query(ShiftAssignment, Shift).join(Shift, ShiftAssignment.shift_id == Shift.id)
            .filter(Shift.shift_date > now, Shift.shift_date <= now + WINDOW,
                    ShiftAssignment.reminder_sent_at.is_(None),
                    db.or_(ShiftAssignment.status.is_(None), ShiftAssignment.status != 'rejected'))
            .order_by(Shift.shift_date).all())


def send_due_shift_reminders(now=None, send=None) -> int:
    """Send what is due and return how many emails went out. `send` is injectable for tests."""
    now = now or datetime.now()
    if not reminders_enabled():
        return 0
    if send is None:
        if not current_app.config.get('MAIL_USERNAME'):
            return 0                                   # email isn't set up: try again when it is
        from services.email_service import send_event_reminder_email as send
    sent = 0
    for a, shift in due_reminders(now):
        user, event = a.user, shift.event
        if not user or not user.email or not event:
            continue
        # Claim it first, so two server workers checking at the same moment can't both send it
        claimed = ShiftAssignment.query.filter(ShiftAssignment.id == a.id, ShiftAssignment.reminder_sent_at.is_(None)) \
            .update({'reminder_sent_at': now}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        try:
            ok = send(recipient_email=user.email, username=user.shown_name, event_title=event.title,
                      event_date=_when(shift), event_location=shift.location or event.location or 'TBD',
                      role=shift.role or 'Crew',
                      reminder_type='today' if shift.shift_date.date() == now.date() else 'tomorrow')
        except Exception as exc:                       # one bad address shouldn't stop the rest
            print(f'⚠️  Shift reminder to {user.username} failed: {exc}')
            ok = False
        if ok is False:                                # didn't go: let the next run try again
            ShiftAssignment.query.filter_by(id=a.id).update({'reminder_sent_at': None}, synchronize_session=False)
            db.session.commit()
        else:
            sent += 1
    return sent
