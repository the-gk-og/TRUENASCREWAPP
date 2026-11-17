"""
services/shift_swaps.py
=======================
Shift swaps: someone on a shift offers it up (to anyone eligible, or to chosen
people), another crew member claims it, and an admin approves or rejects.

    open ──claim──▶ claimed ──approve──▶ approved   (assignment moves to the claimer)
     ▲                 │    ──reject───▶ rejected   (the shift stays with the offerer)
     └──withdraw claim─┘
    open/claimed ──cancel (offerer/admin)──▶ cancelled
    open/claimed ──the shift starts────────▶ expired

The claim checks the claimer's availability and shift clashes; approval checks
again (an admin may override with ``force``).  On approval the assignment row
itself moves, so the reminder job (services/shift_reminders.py) follows the new
person: ``reminder_sent_at`` is cleared so they get their own reminder.
"""

from datetime import datetime

from extensions import db
from models import CrewAssignment, Shift, ShiftAssignment, ShiftSwap, User
from services.availability_service import find_conflicts

ACTIVE = ('open', 'claimed')


class SwapError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.message, self.status, self.extra = message, status, extra


# --- Helpers -----------------------------------------------------------------

def offered_to_ids(swap: ShiftSwap) -> set[int] | None:
    """The user ids it was offered to, or None when anyone eligible may take it."""
    ids = {int(x) for x in (swap.offered_to or '').split(',') if x.strip().isdigit()}
    return ids or None


def is_shift_admin(user) -> bool:
    return bool(user and user.is_authenticated and user.is_admin)


def _is_crew(user: User) -> bool:
    """Cast-only accounts can't hold crew shifts (same rule as adding someone to a team)."""
    return bool(user) and (not user.is_cast or user.is_admin)


def _started(shift: Shift, now: datetime) -> bool:
    return shift.shift_date <= now


def expire_started(now: datetime | None = None) -> int:
    """Mark open/claimed offers whose shift has started as expired.  Returns how many."""
    now = now or datetime.now()
    rows = (ShiftSwap.query.join(ShiftAssignment, ShiftSwap.assignment_id == ShiftAssignment.id)
            .join(Shift, ShiftAssignment.shift_id == Shift.id)
            .filter(ShiftSwap.status.in_(ACTIVE), Shift.shift_date <= now).all())
    for s in rows:
        s.status = 'expired'
    if rows:
        db.session.commit()
    return len(rows)


def active_swap_for(assignment: ShiftAssignment) -> ShiftSwap | None:
    return next((s for s in assignment.swaps if s.status in ACTIVE), None)


def eligible_people(assignment: ShiftAssignment) -> list[dict]:
    """Crew who could take this shift, with any clash they'd have (shown, not blocking, when offering)."""
    shift = assignment.shift
    on_shift = {a.user_id for a in shift.assignments}
    out = []
    for u in User.query.order_by(User.username).all():
        if u.id in on_shift or not _is_crew(u):
            continue
        out.append({'id': u.id, 'name': u.shown_name,
                    'clash': bool(find_conflicts(u.id, shift.shift_date, shift.shift_end_date))})
    return sorted(out, key=lambda p: p['name'].lower())


def claim_problem(swap: ShiftSwap, user: User, now: datetime | None = None) -> str | None:
    """Why ``user`` can't claim this offer right now (None if they can)."""
    now = now or datetime.now()
    shift = swap.assignment.shift
    if swap.status != 'open':
        return 'This shift is no longer up for grabs'
    if _started(shift, now):
        return 'This shift has already started'
    if user.id == swap.offered_by_id:
        return "You can't claim your own shift"
    if not _is_crew(user):
        return 'Only crew can take shifts'
    if any(a.user_id == user.id for a in shift.assignments):
        return 'You are already on this shift'
    allowed = offered_to_ids(swap)
    if allowed is not None and user.id not in allowed:
        return 'This shift was offered to someone else'
    return None


def open_offers_for(user: User, now: datetime | None = None) -> list[ShiftSwap]:
    """Open offers this user could claim, soonest shift first."""
    now = now or datetime.now()
    rows = (ShiftSwap.query.join(ShiftAssignment, ShiftSwap.assignment_id == ShiftAssignment.id)
            .join(Shift, ShiftAssignment.shift_id == Shift.id)
            .filter(ShiftSwap.status == 'open', Shift.shift_date > now)
            .order_by(Shift.shift_date).all())
    return [s for s in rows if claim_problem(s, user, now) is None]


def awaiting_approval() -> list[ShiftSwap]:
    return (ShiftSwap.query.join(ShiftAssignment, ShiftSwap.assignment_id == ShiftAssignment.id)
            .join(Shift, ShiftAssignment.shift_id == Shift.id)
            .filter(ShiftSwap.status == 'claimed').order_by(Shift.shift_date).all())


def serialize(swap: ShiftSwap) -> dict:
    a = swap.assignment
    shift = a.shift
    ev = shift.event
    return {
        'id': swap.id, 'status': swap.status, 'assignment_id': a.id, 'shift_id': shift.id,
        'event_id': ev.id if ev else None, 'event_title': ev.title if ev else '',
        'role': shift.role or '', 'start': shift.shift_date.isoformat(timespec='minutes'),
        'end': shift.shift_end_date.isoformat(timespec='minutes'),
        'offered_by': swap.offered_by.shown_name if swap.offered_by else '?',
        'offered_by_id': swap.offered_by_id,
        'offered_to': sorted(offered_to_ids(swap) or []),
        'claimed_by': swap.claimed_by.shown_name if swap.claimed_by else None,
        'claimed_by_id': swap.claimed_by_id, 'note': swap.note or '',
    }


# --- Actions -----------------------------------------------------------------

def create_offer(assignment: ShiftAssignment, user: User, to_ids=None, note: str = '',
                 now: datetime | None = None) -> ShiftSwap:
    now = now or datetime.now()
    if assignment.user_id != user.id:
        raise SwapError('You can only offer up your own shifts', 403)
    if assignment.status == 'rejected':
        raise SwapError("You've declined this shift, so there's nothing to swap")
    if _started(assignment.shift, now):
        raise SwapError('This shift has already started')
    expire_started(now)
    if active_swap_for(assignment):
        raise SwapError('This shift is already up for swap')
    ids = []
    for x in to_ids or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            raise SwapError('Invalid person')
    ids = sorted(set(ids) - {user.id})
    if ids:
        found = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
        if len(found) != len(ids) or not all(_is_crew(u) for u in found.values()):
            raise SwapError('Some of the chosen people cannot take shifts')
    swap = ShiftSwap(assignment_id=assignment.id, offered_by_id=user.id,
                     offered_to=','.join(map(str, ids)) or None,
                     note=(note or '').strip()[:500] or None, status='open')
    db.session.add(swap)
    db.session.commit()
    return swap


def claim(swap: ShiftSwap, user: User, now: datetime | None = None) -> ShiftSwap:
    now = now or datetime.now()
    expire_started(now)
    problem = claim_problem(swap, user, now)
    if problem:
        raise SwapError(problem, 409 if swap.status != 'open' else 400)
    shift = swap.assignment.shift
    conflicts = find_conflicts(user.id, shift.shift_date, shift.shift_end_date)
    if conflicts:
        raise SwapError("You can't take this shift: it clashes with your schedule", 409, conflicts=conflicts)
    # Guard against two people claiming at the same moment
    won = (ShiftSwap.query.filter(ShiftSwap.id == swap.id, ShiftSwap.status == 'open')
           .update({'status': 'claimed', 'claimed_by_id': user.id, 'claimed_at': now},
                   synchronize_session=False))
    db.session.commit()
    db.session.refresh(swap)
    if not won:
        raise SwapError('Someone else has just claimed this shift', 409)
    return swap


def withdraw_claim(swap: ShiftSwap, user: User) -> ShiftSwap:
    if swap.status != 'claimed' or swap.claimed_by_id != user.id:
        raise SwapError('You have not claimed this shift', 403)
    swap.status, swap.claimed_by_id, swap.claimed_at = 'open', None, None
    db.session.commit()
    return swap


def cancel(swap: ShiftSwap, user: User) -> ShiftSwap:
    if user.id != swap.offered_by_id and not is_shift_admin(user):
        raise SwapError('Permission denied', 403)
    if swap.status not in ACTIVE:
        raise SwapError('This swap is already closed')
    swap.status = 'cancelled'
    swap.decided_by, swap.decided_at = user.username, datetime.now()
    db.session.commit()
    return swap


def reject(swap: ShiftSwap, admin: User, now: datetime | None = None) -> ShiftSwap:
    if not is_shift_admin(admin):
        raise SwapError('Admin access required', 403)
    if swap.status != 'claimed':
        raise SwapError('Only a claimed swap can be rejected')
    swap.status = 'rejected'
    swap.decided_by, swap.decided_at = admin.username, now or datetime.now()
    db.session.commit()
    return swap


def approve(swap: ShiftSwap, admin: User, force: bool = False, now: datetime | None = None) -> ShiftSwap:
    """Move the assignment to the claimer."""
    now = now or datetime.now()
    if not is_shift_admin(admin):
        raise SwapError('Admin access required', 403)
    expire_started(now)
    if swap.status != 'claimed':
        raise SwapError('Only a claimed swap can be approved' if swap.status != 'expired'
                        else 'This shift has already started', 409)
    a = swap.assignment
    shift = a.shift
    if a.user_id != swap.offered_by_id:
        raise SwapError('This shift has changed hands since it was offered', 409)
    claimer = swap.claimed_by
    if any(x.user_id == claimer.id for x in shift.assignments):
        raise SwapError(f'{claimer.shown_name} is already on this shift', 409)
    conflicts = find_conflicts(claimer.id, shift.shift_date, shift.shift_end_date)
    if conflicts and not force:
        raise SwapError(f'{claimer.shown_name} now has a clash', 409, conflicts=conflicts)

    old_user = a.user
    try:
        a.user_id = claimer.id
        a.status = 'accepted'                  # they asked for it
        a.responded_at = now
        a.decline_reason = None
        a.reminder_sent_at = None              # the new person gets their own reminder
        a.assigned_by = admin.username
        swap.status = 'approved'
        swap.decided_by, swap.decided_at = admin.username, now

        event_id = shift.event_id
        if not CrewAssignment.query.filter_by(event_id=event_id, crew_member=claimer.username).first():
            db.session.add(CrewAssignment(event_id=event_id, crew_member=claimer.username,
                                          role=shift.role or 'Crew Member', assigned_via='swap'))
        db.session.flush()
        still_on = (ShiftAssignment.query.join(Shift)
                    .filter(Shift.event_id == event_id, ShiftAssignment.user_id == old_user.id).count())
        if not still_on:
            CrewAssignment.query.filter_by(event_id=event_id, crew_member=old_user.username).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return swap
