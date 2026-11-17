"""services/shift_reminders.py — remind people before their shift (email and Web Push).

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


def send_due_shift_reminders(now=None, send=None, push=None) -> int:
    """Send what is due (email and/or Web Push) and return how many people were reminded.
    `send` (email) and `push` are injectable for tests."""
    now = now or datetime.now()
    if not reminders_enabled():
        return 0
    if send is None and current_app.config.get('MAIL_USERNAME'):
        from services.email_service import send_event_reminder_email as send
    if push is None:
        from services.push_service import send_to_user as push, wants
    else:
        wants = lambda user_id, kind: True
    sent = 0
    for a, shift in due_reminders(now):
        user, event = a.user, shift.event
        if not user or not event:
            continue
        can_email = bool(send and user.email)
        can_push = wants(user.id, 'shift_reminder')
        if not can_email and not can_push:
            continue                                   # nothing to send it with yet: try again later
        # Claim it first, so two server workers checking at the same moment can't both send it
        claimed = ShiftAssignment.query.filter(ShiftAssignment.id == a.id, ShiftAssignment.reminder_sent_at.is_(None)) \
            .update({'reminder_sent_at': now}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue
        when = 'today' if shift.shift_date.date() == now.date() else 'tomorrow'
        ok = False
        if can_push:
            ok = bool(push(user.id, 'shift_reminder', f"Shift {when}: {event.title}",
                           f"{shift.role or 'Crew'} · {_when(shift)}", '/crew/my-schedule'))
        if can_email:
            try:
                ok = send(recipient_email=user.email, username=user.shown_name, event_title=event.title,
                          event_date=_when(shift), event_location=shift.location or event.location or 'TBD',
                          role=shift.role or 'Crew', reminder_type=when) is not False or ok
            except Exception as exc:                   # one bad address shouldn't stop the rest
                print(f'⚠️  Shift reminder to {user.username} failed: {exc}')
        if not ok:                                     # didn't go: let the next run try again
            ShiftAssignment.query.filter_by(id=a.id).update({'reminder_sent_at': None}, synchronize_session=False)
            db.session.commit()
        else:
            sent += 1
    return sent
