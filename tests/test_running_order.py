"""Running order: acts with their songs, planned times from the order, actual times from the live clock.
Run: pytest tests/test_running_order.py"""
import io
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                  # noqa: E402
from models import CrewRunItem, Event                      # noqa: E402
from tests.test_events import app, admin, alice, client_for, mk   # noqa: E402,F401  (fixtures)


def add(c, eid, title, **kw):
    r = c.post(f'/events/{eid}/crew-run/add', json={'title': title, **kw})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['id']


def order(c, eid):
    return c.get(f'/events/{eid}/running-order').get_json()


def shape(p):
    return [(a['title'], [s['title'] for s in a['songs']]) for a in p['acts']]


def bill(c, eid):
    """Two bands with a changeover between them."""
    a = add(c, eid, 'The Openers', kind='Band')
    s1 = add(c, eid, 'Song A', duration='4:00', parent_id=a)
    s2 = add(c, eid, 'Song B', duration='6 min', parent_id=a)
    ch = add(c, eid, 'Changeover', duration='15 min', kind='Changeover')
    b = add(c, eid, 'Headliner', duration='60 min', kind='Band')
    s3 = add(c, eid, 'Hit', duration='5 min', parent_id=b)
    return a, s1, s2, ch, b, s3


def test_acts_songs_and_planned_times(app, admin, alice):
    eid = mk(admin)                                        # starts 18:00
    a, s1, s2, ch, b, s3 = bill(admin, eid)
    p = order(alice, eid)                                  # any crew member can read it
    assert shape(p) == [('The Openers', ['Song A', 'Song B']), ('Changeover', []), ('Headliner', ['Hit'])]
    acts = p['acts']
    # An act with no length of its own lasts as long as its songs (4 + 6 = 10 min)
    assert acts[0]['length'] == 10 and acts[0]['planned'].endswith('18:00:00')
    assert [s['planned'][11:16] for s in acts[0]['songs']] == ['18:00', '18:04']
    assert acts[1]['planned'][11:16] == '18:10' and acts[1]['quiet'] is True
    assert acts[2]['planned'][11:16] == '18:25' and acts[2]['songs'][0]['planned'][11:16] == '18:25'
    assert p['end'][11:16] == '19:25' and p['total'] == 85 and p['count'] == 3 and p['songs'] == 3
    assert [x['n'] for x in acts] == [1, 2, 3] and [s['n'] for s in acts[0]['songs']] == [1, 2]

    # Moving the start time moves everything
    admin.put(f'/events/{eid}/run-start', json={'time': '19:30'})
    assert order(admin, eid)['acts'][2]['planned'][11:16] == '19:55'

    # The page carries it, the tab says "Running order", and nothing talks about cues
    page = admin.get(f'/events/{eid}').data.decode()
    assert 'Running order' in page and '"running_order"' in page and 'Song B' in page
    assert 'Cue type' not in page and 'evCues' not in page


def test_permissions_and_bad_parent(app, admin, alice):
    eid = mk(admin)
    a = add(admin, eid, 'Band')
    assert alice.post(f'/events/{eid}/crew-run/add', json={'title': 'x'}).status_code == 403
    assert alice.post(f'/events/{eid}/running-order/go', json={}).status_code == 403
    other = mk(admin, title='Other')
    assert admin.post(f'/events/{other}/crew-run/add', json={'title': 'x', 'parent_id': a}).status_code == 404
    # Adding "into" a song puts it in that song's act (never three levels deep)
    s = add(admin, eid, 'Song', parent_id=a)
    s2 = add(admin, eid, 'Song 2', parent_id=s)
    assert db.session.get(CrewRunItem, s2).parent_id == a


def test_reorder_tree_moves_songs_between_acts(app, admin):
    eid = mk(admin)
    a, s1, s2, ch, b, s3 = bill(admin, eid)
    r = admin.post(f'/events/{eid}/crew-run/reorder',
                   json={'tree': [{'id': b, 'songs': [s3, s2]}, {'id': a, 'songs': [s1]}, {'id': ch, 'songs': []}]})
    assert r.status_code == 200
    assert shape(order(admin, eid)) == [('Headliner', ['Hit', 'Song B']), ('The Openers', ['Song A']), ('Changeover', [])]
    nums = {i.title: i.order_number for i in CrewRunItem.query.all()}
    assert (nums['Headliner'], nums['The Openers'], nums['Changeover'], nums['Hit'], nums['Song B'], nums['Song A']) == (1, 2, 3, 1, 2, 1)
    # The older flat list of acts still works and keeps each act's songs
    admin.post(f'/events/{eid}/crew-run/reorder', json={'item_ids': [ch, a, b]})
    assert shape(order(admin, eid)) == [('Changeover', []), ('The Openers', ['Song A']), ('Headliner', ['Hit', 'Song B'])]
    # An act that has songs can't be dropped inside another act
    admin.post(f'/events/{eid}/crew-run/reorder', json={'tree': [{'id': ch, 'songs': [a]}, {'id': b, 'songs': [s3, s2]}]})
    assert ('The Openers', ['Song A']) in shape(order(admin, eid))


def test_delete_act_takes_its_songs_and_renumbers(app, admin):
    eid = mk(admin)
    a, s1, s2, ch, b, s3 = bill(admin, eid)
    assert admin.delete(f'/events/crew-run/{s1}/delete').status_code == 200
    assert order(admin, eid)['acts'][0]['songs'][0]['n'] == 1
    assert admin.delete(f'/events/crew-run/{a}/delete').status_code == 200
    assert shape(order(admin, eid)) == [('Changeover', []), ('Headliner', ['Hit'])]
    assert CrewRunItem.query.count() == 3 and db.session.get(CrewRunItem, ch).order_number == 1
    assert admin.delete(f'/events/{eid}').status_code == 200          # the event takes the whole running order
    assert CrewRunItem.query.count() == 0


def test_old_flat_run_lists_still_show(app, admin):
    """Run lists from before running orders had no songs: every row is an act, cue types become types."""
    eid = mk(admin)
    for n, (t, d, cue) in enumerate((('Walk-in', '', 'Sound'), ('Speech', '5 min', 'Lighting')), start=1):
        db.session.add(CrewRunItem(event_id=eid, order_number=n, title=t, duration=d, cue_type=cue))
    db.session.commit()
    p = order(admin, eid)
    assert shape(p) == [('Walk-in', []), ('Speech', [])] and p['acts'][1]['kind'] == 'Lighting'
    assert p['missing'] == 1 and p['timed'] is True
    # The old "cue_type" field is still accepted when saving
    admin.put(f'/events/crew-run/{p["acts"][0]["id"]}/edit', json={'title': 'Walk-in', 'cue_type': 'Doors'})
    assert order(admin, eid)['acts'][0]['kind'] == 'Doors'
    assert admin.get(f'/events/{eid}').status_code == 200
    assert admin.get(f'/events/{eid}/export-pdf?parts=run').data[:4] == b'%PDF'


def test_live_clock_actual_vs_planned(app, admin, monkeypatch):
    from services import running_order
    eid = mk(admin)
    a, s1, s2, ch, b, s3 = bill(admin, eid)
    at = {'now': datetime(2026, 11, 10, 18, 5)}
    monkeypatch.setattr(running_order, 'now', lambda: at['now'])

    p = order(admin, eid)
    assert p['next_id'] == a and not p['started'] and p['drift'] is None

    # "Next" with nothing running starts the first act, 5 minutes late
    p = admin.post(f'/events/{eid}/running-order/go', json={}).get_json()
    assert p['current_id'] == a and round(p['drift']) == 5 and p['next_id'] == s1
    assert p['expected_end'][11:16] == '19:30'                     # planned 19:25 + 5

    at['now'] = datetime(2026, 11, 10, 18, 6)
    p = admin.post(f'/events/{eid}/running-order/go', json={}).get_json()
    assert p['current_id'] == s1 and p['acts'][0]['live'] and round(p['drift']) == 6
    at['now'] = datetime(2026, 11, 10, 18, 11)
    admin.post(f'/events/{eid}/running-order/go', json={})       # Song B; Song A ran 5 min
    at['now'] = datetime(2026, 11, 10, 18, 20)
    p = admin.post(f'/events/{eid}/running-order/go', json={'item_id': ch}).get_json()  # jump to the changeover
    acts = p['acts']
    assert acts[0]['ended_at'][11:16] == '18:20' and acts[0]['actual_length'] == 15
    assert acts[0]['songs'][0]['actual_length'] == 5 and acts[0]['songs'][1]['ended_at'][11:16] == '18:20'
    assert p['current_id'] == ch and round(p['drift']) == 10

    # Starting a song starts its act too, and ends the changeover
    at['now'] = datetime(2026, 11, 10, 18, 30)
    p = admin.post(f'/events/{eid}/running-order/go', json={'item_id': s3}).get_json()
    assert p['acts'][2]['live'] and p['acts'][2]['started_at'][11:16] == '18:30' and p['acts'][1]['ended_at']
    assert p['next_id'] is None

    at['now'] = datetime(2026, 11, 10, 19, 40)
    p = admin.post(f'/events/{eid}/running-order/stop', json={}).get_json()
    assert p['finished'] and not p['live'] and round(p['drift']) == 15       # planned end 19:25
    assert admin.post(f'/events/{eid}/running-order/go', json={}).status_code == 400   # nothing left

    # The PDF gets an "Actual" column once the show has run
    assert admin.get(f'/events/{eid}/export-pdf?parts=run').status_code == 200

    p = admin.post(f'/events/{eid}/running-order/reset', json={}).get_json()
    assert not p['started'] and all(x['started_at'] is None for x in p['acts'])


def test_duplicate_copies_acts_and_songs_not_actual_times(app, admin, monkeypatch):
    eid = mk(admin)
    a, *_ = bill(admin, eid)
    admin.post(f'/events/{eid}/running-order/go', json={'item_id': a})
    new = admin.post(f'/events/{eid}/duplicate', json={}).get_json()['id']
    p = order(admin, new)
    assert shape(p) == shape(order(admin, eid)) and not p['started']


def test_running_order_pdf_has_acts_and_songs(app, admin):
    from services import report_service
    eid = mk(admin, title='Gig Night')
    bill(admin, eid)
    event = db.session.get(Event, eid)
    flow = report_service._run(event)
    table = flow[0]
    cells = [str(c) for row in table._cellvalues for c in row]
    text = ' '.join(cells)
    assert 'Act / song' in text and 'The Openers' in text and 'Song B' in text and 'Changeover' in text
    assert 'Cue' not in text and 'Actual' not in text
    assert 'finishing about 7:25 pm' in str(flow[-1].text)
    r = admin.get(f'/events/{eid}/export-pdf?parts=run')
    assert r.data[:4] == b'%PDF' and 'Gig_Night_running_order_20261110.pdf' in r.headers['Content-Disposition']


def test_spreadsheet_songs_round_trip(app, admin):
    eid = mk(admin)
    text = ('Title,Length,Type,Description,Notes\n'
            'Band One,30 min,Band,,\nIntro,3:00,Song,,\nOutro,4:00,song,,quiet\n'
            'Interval,20 min,Interval,,\nBand Two,,Band,,\nOnly song,5 min,Song,,\n')
    r = admin.post(f'/events/{eid}/io/import/run', data={'file': (io.BytesIO(text.encode()), 'ro.csv'), 'mode': 'append'},
                   content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['imported'] == 6
    before = shape(order(admin, eid))
    assert before == [('Band One', ['Intro', 'Outro']), ('Interval', []), ('Band Two', ['Only song'])]
    for fmt in ('csv', 'xlsx'):
        data = admin.get(f'/events/{eid}/io/export/run.{fmt}').data
        r = admin.post(f'/events/{eid}/io/import/run', data={'file': (io.BytesIO(data), f'back.{fmt}'), 'mode': 'replace'},
                       content_type='multipart/form-data')
        assert r.status_code == 200, r.get_json()
        assert shape(order(admin, eid)) == before
    # Appending more acts goes after the existing ones
    admin.post(f'/events/{eid}/io/import/run', data={'file': (io.BytesIO(b'Title\nEncore\n'), 'e.csv'), 'mode': 'append'},
               content_type='multipart/form-data')
    assert [t for t, _ in shape(order(admin, eid))][-1] == 'Encore'


def test_cast_page_shows_running_order(app, admin):
    eid = mk(admin)
    bill(admin, eid)
    r = admin.get(f'/cast-events/{eid}')
    assert r.status_code == 200
    body = r.data.decode()
    assert 'Running order' in body and 'The Openers' in body and 'Song B' in body
