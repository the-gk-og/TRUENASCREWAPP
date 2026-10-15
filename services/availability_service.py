"""
services/availability_service.py
================================
Unavailability expansion and shift-conflict detection.

All datetimes in ShowWise are naive wall-clock values (the venue's local
time), so everything here is naive too.
"""

import re
from datetime import datetime, timedelta

from models import (
    Shift, ShiftAssignment, UserUnavailability, RecurringUnavailability,
)


def expand_unavailability(user_ids, start: datetime, end: datetime) -> list[dict]:
    """
    Return every unavailability window overlapping [start, end) for the given
    users, with recurring patterns expanded into concrete windows.
    """
    out: list[dict] = []
    if not user_ids:
        return out

    for u in UserUnavailability.query.filter(
        UserUnavailability.user_id.in_(user_ids),
        UserUnavailability.start_date < end,
        UserUnavailability.end_date > start,
    ).all():
        out.append({
            'id': f'u-{u.id}', 'user_id': u.user_id, 'title': u.title,
            'start': u.start_date, 'end': u.end_date,
            'all_day': bool(u.is_all_day), 'recurring': False,
        })

    recs = RecurringUnavailability.query.filter(
        RecurringUnavailability.user_id.in_(user_ids),
        RecurringUnavailability.is_active.is_(True),
        RecurringUnavailability.start_date < end,
    ).all()
    for rec in recs:
        if rec.end_date is not None and rec.end_date.date() < start.date():
            continue
        try:
            sh, sm = map(int, rec.start_time.split(':'))
            eh, em = map(int, rec.end_time.split(':'))
        except (ValueError, AttributeError):
            continue
        # '1,3' (current) or '["1","3"]' (written by the old UI): pull out the digits
        days = {int(d) for d in re.findall(r'[0-6]', rec.days_of_week or '')}

        day = datetime.combine(max(start.date(), rec.start_date.date()), datetime.min.time())
        last = end.date()
        while day.date() <= last:
            if rec.end_date is not None and day.date() > rec.end_date.date():
                break
            hit = False
            if rec.pattern_type == 'daily':
                hit = True
            elif rec.pattern_type == 'weekly':
                # stored as Sunday=0 … Saturday=6
                hit = ((day.weekday() + 1) % 7) in days
            elif rec.pattern_type == 'monthly':
                hit = day.day == rec.day_of_month
            if hit:
                w_start = day.replace(hour=sh, minute=sm)
                w_end = day.replace(hour=eh, minute=em)
                if w_end <= w_start:          # overnight window
                    w_end += timedelta(days=1)
                if w_start < end and w_end > start:
                    out.append({
                        'id': f'r-{rec.id}-{day.date()}', 'user_id': rec.user_id,
                        'title': rec.title, 'start': w_start, 'end': w_end,
                        'all_day': False, 'recurring': True,
                    })
            day += timedelta(days=1)
    return out


def find_conflicts(user_id: int, start: datetime, end: datetime,
                   exclude_assignment_id: int | None = None) -> list[dict]:
    """Shift overlaps and unavailability windows for one user."""
    conflicts: list[dict] = []

    q = (ShiftAssignment.query.join(Shift)
         .filter(ShiftAssignment.user_id == user_id,
                 ShiftAssignment.status != 'rejected',
                 Shift.shift_date < end,
                 Shift.shift_end_date > start))
    if exclude_assignment_id:
        q = q.filter(ShiftAssignment.id != exclude_assignment_id)
    for a in q.all():
        ev = a.shift.event
        conflicts.append({
            'type': 'shift',
            'title': f"Already on shift for “{ev.title if ev else 'another event'}”",
            'start': a.shift.shift_date.isoformat(),
            'end': a.shift.shift_end_date.isoformat(),
        })

    for w in expand_unavailability([user_id], start, end):
        conflicts.append({
            'type': 'unavailable',
            'title': f"Marked unavailable: {w['title']}",
            'start': w['start'].isoformat(), 'end': w['end'].isoformat(),
        })
    return conflicts
