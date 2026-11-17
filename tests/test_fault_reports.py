"""Fault reports from a phone: report -> quarantine + photos + admin email -> resolve.
Run: pytest tests/test_fault_reports.py"""
import io
import os, sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                                  # noqa: E402
from models import (EquipmentUnit, Event, FaultReport, FaultPhoto,         # noqa: E402
                    UnitMaintenance, UnitQuarantine)
from tests.test_events import app, admin, alice, client_for, _outbox       # noqa: E402,F401  (fixtures)
from tests.test_quarantine_and_bulk import PNG, mic, tag                   # noqa: E402,F401


def photo(name='shot.png', data=PNG):
    return (io.BytesIO(data), name)


def report(c, unit_id, json=True, **fields):
    data = {'summary': 'Cuts out', 'category': 'electrical', 'severity': 'unsafe', **fields}
    headers = {'Accept': 'application/json'} if json else {}
    return c.post(f'/equipment/unit/{unit_id}/fault', data=data, headers=headers,
                  content_type='multipart/form-data')


@pytest.fixture(autouse=True)
def _cleanup_uploads(app):
    yield
    for p in FaultPhoto.query.all():
        try:
            os.remove(os.path.join('uploads', p.path))
        except OSError:
            pass


def test_form_page_renders_for_crew(app, alice, mic):
    u = tag('MIC-01')
    r = alice.get(f'/equipment/unit/{u.id}/fault')
    assert r.status_code == 200
    assert b'Report a fault' in r.data and b'MIC-01' in r.data and b'capture="environment"' in r.data


def test_report_quarantines_saves_photos_and_emails_admins(app, alice, mic):
    u = tag('MIC-01')
    with _outbox(app) as outbox:
        r = report(alice, u.id, photos=[photo('a.png'), photo('b.png')])
        assert r.status_code == 200, r.get_json()
        assert len(outbox) == 1
        m = outbox[0]
        assert m.recipients == ['boss@x.test'] and 'MIC-01' in m.subject and 'Unsafe' in m.subject
        assert 'Cuts out' in m.body and 'Photos: 2' in m.body
    d = r.get_json()
    assert d['report']['photo_count'] == 2 and d['report']['severity'] == 'unsafe'
    u = tag('MIC-01')
    assert u.status == 'quarantined'
    f = FaultReport.query.one()
    assert f.quarantine_id == u.open_quarantine.id and f.reported_by == 'alice'
    assert u.open_quarantine.reason == 'Electrical fault: Cuts out'
    for p in f.photos:
        assert os.path.exists(os.path.join('uploads', p.path))
    # Photos are served to crew
    assert alice.get(d['report']['photo_urls'][0]).status_code == 200
    # Shows on the item's history and in the attention panel
    h = alice.get(f'/equipment/unit/{u.id}/history').get_json()
    row = next(t for t in h['timeline'] if t['kind'] == 'fault')
    assert len(row['photos']) == 2 and row['severity'] == 'unsafe'
    assert not any(t['kind'] == 'quarantine' for t in h['timeline'])      # no duplicate row
    page = client_for(app, 'boss').get('/equipment')
    assert b'Unsafe' in page.data and b'2 photos' in page.data


def test_category_alone_is_enough_but_other_needs_words(app, alice, mic):
    u = tag('MIC-01')
    r = report(alice, u.id, summary='', category='damaged', severity='minor')
    assert r.status_code == 200 and r.get_json()['report']['summary'] == 'Broken or damaged'
    u2 = tag('MIC-02')
    r = report(alice, u2.id, summary='', category='other')
    assert r.status_code == 400 and 'what is wrong' in r.get_json()['error']
    assert report(alice, u2.id, severity='catastrophic').status_code == 400
    assert tag('MIC-02').status == 'available'


def test_bad_photo_is_rejected_and_nothing_saved(app, alice, mic):
    u = tag('MIC-01')
    files = lambda: set(os.listdir('uploads/faults')) if os.path.isdir('uploads/faults') else set()
    before = files()
    r = report(alice, u.id, photos=[photo('ok.png'), photo('evil.png', b'<?php echo 1; ?>')])
    assert r.status_code == 400 and 'not a valid image' in r.get_json()['error']
    r = report(alice, u.id, photos=[photo('x.exe', PNG)])
    assert r.status_code == 400
    assert FaultReport.query.count() == 0 and tag('MIC-01').status == 'available'
    assert files() == before                                                # the good photo was removed too


def test_plain_form_post_redirects_and_errors_render_the_form(app, alice, mic):
    u = tag('MIC-01')
    r = report(alice, u.id, json=False, summary='', category='')
    assert r.status_code == 400 and b'Say what is wrong with it' in r.data
    r = report(alice, u.id, json=False)
    assert r.status_code == 302 and f'unit={u.id}' in r.headers['Location']


def test_second_report_joins_the_open_quarantine(app, alice, mic):
    u = tag('MIC-01')
    assert report(alice, u.id).status_code == 200
    assert report(alice, u.id, summary='Grille dented', category='damaged').status_code == 200
    assert UnitQuarantine.query.count() == 1
    q = tag('MIC-01').open_quarantine
    assert len(q.fault_reports) == 2 and q.to_dict()['faults'][0]['severity'] == 'unsafe'


def test_retired_items_cannot_be_reported(app, admin, alice, mic):
    u = tag('MIC-01')
    admin.put(f'/equipment/unit/{u.id}', json={'status': 'retired'})
    assert report(alice, u.id).status_code == 409


def test_admin_resolves_report_links_maintenance_and_releases(app, admin, alice, mic):
    u = tag('MIC-01')
    fid = report(alice, u.id, photos=[photo()]).get_json()['report']['id']
    assert report(alice, u.id, summary='Also scratched').status_code == 200
    # Crew can't resolve
    assert alice.post(f'/equipment/fault/{fid}/resolve', json={'note': 'x'}).status_code == 403
    # A note is needed to put it back in use
    assert admin.post(f'/equipment/fault/{fid}/resolve', json={'outcome': 'available'}).status_code == 400
    r = admin.post(f'/equipment/fault/{fid}/resolve',
                   json={'outcome': 'available', 'kind': 'repair', 'note': 'Resoldered XLR'})
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d['unit']['status'] == 'available' and d['record']['kind'] == 'repair'
    rec = db.session.get(UnitMaintenance, d['record']['id'])
    assert 'Resoldered XLR' in rec.notes
    # Every report on that quarantine is resolved and linked
    for f in FaultReport.query.all():
        assert f.resolved_at and f.resolved_by == 'boss' and f.maintenance_id == rec.id
    assert tag('MIC-01').open_quarantine is None
    assert admin.post(f'/equipment/fault/{fid}/resolve', json={'note': 'x'}).status_code == 409
    # Gone from the attention panel
    assert b'out of use, waiting' not in admin.get('/equipment').data


def test_release_from_attention_panel_also_resolves_reports(app, admin, alice, mic):
    u = tag('MIC-01')
    report(alice, u.id)
    r = admin.post(f'/equipment/unit/{u.id}/release', json={'outcome': 'repair', 'note': 'Off to the shop'})
    assert r.status_code == 200
    f = FaultReport.query.one()
    assert f.resolved_at and f.maintenance_id is None and f.resolution_note == 'Off to the shop'
    assert tag('MIC-01').status == 'repair'


def test_resolve_can_link_an_existing_maintenance_record(app, admin, alice, mic):
    u = tag('MIC-01')
    fid = report(alice, u.id).get_json()['report']['id']
    rid = admin.post(f'/equipment/unit/{u.id}/maintenance',
                     json={'kind': 'pat', 'result': 'pass'}).get_json()['record']['id']
    other = admin.post(f'/equipment/unit/{tag("MIC-02").id}/maintenance',
                       json={'kind': 'pat', 'result': 'pass'}).get_json()['record']['id']
    assert admin.post(f'/equipment/fault/{fid}/resolve', json={'maintenance_id': other}).status_code == 400
    r = admin.post(f'/equipment/fault/{fid}/resolve', json={'maintenance_id': rid, 'note': 'PAT passed'})
    assert r.status_code == 200 and db.session.get(FaultReport, fid).maintenance_id == rid
    assert UnitMaintenance.query.count() == 2                              # no extra record made


def test_scan_and_public_page_offer_report(app, alice, mic):
    u = tag('MIC-01')
    d = alice.post('/api/scan', json={'code': 'MIC-01'}).get_json()
    assert d['fault_url'] == f'/equipment/unit/{u.id}/fault'
    # Signed in and coming from the label's "Report a fault": straight to the form
    r = alice.get(f'/equipment/unit/{u.id}/view?report=1')
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/equipment/unit/{u.id}/fault')
    # Not signed in: the public page has the button, which goes via sign-in
    anon = app.test_client()
    r = anon.get(f'/equipment/unit/{u.id}/view')
    assert r.status_code == 200 and b'Report a fault with MIC-01' in r.data
    assert b'fault' in r.data and b'login' in r.data


def test_deleting_an_item_removes_its_reports(app, admin, alice, mic):
    u = tag('MIC-01')
    report(alice, u.id, photos=[photo()])
    assert admin.delete(f'/equipment/unit/{u.id}').status_code == 200
    assert FaultReport.query.count() == 0
