"""Gear double-booking: event windows and scan-out warnings for reserved units."""
import os, sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import Event, EventTime                                        # noqa: E402
from services.gear_bookings import event_window, overlaps                  # noqa: E402
from tests.test_events import app, admin, alice, client_for                # noqa: E402,F401
from tests.test_unit_tracking import mic, mk_line, scan                    # noqa: E402,F401


def _ev(title, start, hours=3):
    ev = Event(title=title, event_date=start, event_end_date=start + timedelta(hours=hours))
    db.session.add(ev)
    db.session.commit()
    return ev


def test_window_includes_labeled_times(app):
    start = datetime(2030, 5, 1, 19)
    ev = _ev('Show', start)
    db.session.add(EventTime(event_id=ev.id, label='Bump-in', start_time=start - timedelta(days=1),
                             end_time=start - timedelta(hours=20)))
    db.session.commit()
    s, e = event_window(ev)
    assert s == start - timedelta(days=1) and e == start + timedelta(hours=3)


def test_overlaps():
    a = (datetime(2030, 1, 1, 10), datetime(2030, 1, 1, 12))
    assert overlaps(a, (datetime(2030, 1, 1, 11), datetime(2030, 1, 1, 13)))
    assert not overlaps(a, (datetime(2030, 1, 1, 13), datetime(2030, 1, 1, 14)))


def test_scan_out_warns_when_reserved_for_overlapping_event(app, alice, mic):
    start = datetime.now() + timedelta(days=3)
    a, b = _ev('Concert A', start), _ev('Concert B', start + timedelta(hours=1))
    a_id, b_id = a.id, b.id
    line = mk_line(alice, mic, a_id, qty=1)
    assert alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-01'}).status_code == 200
    j = scan(alice, b_id, 'MIC-01').get_json()
    assert j['action'] == 'out'                       # a warning, not a block
    assert any(w['code'] == 'reserved_elsewhere' and 'Concert A' in w['message'] for w in j['warnings'])


def test_no_warning_when_reservation_does_not_overlap(app, alice, mic):
    start = datetime.now() + timedelta(days=3)
    a, b = _ev('Week one', start), _ev('Week two', start + timedelta(days=7))
    a_id, b_id = a.id, b.id
    line = mk_line(alice, mic, a_id, qty=1)
    alice.post(f'/picklist/{line}/units', json={'asset_tag': 'MIC-01'})
    j = scan(alice, b_id, 'MIC-01').get_json()
    assert not any(w['code'] == 'reserved_elsewhere' for w in j['warnings'])
