"""QR tag PDF generator: long text must wrap/shrink and stay inside each tag.
Run: pytest tests/test_equipment_tags.py"""
import os, sys

import pytest
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db                                   # noqa: E402
from models import Equipment                                # noqa: E402
from tests.test_events import app, admin                    # noqa: E402,F401  (fixtures)

LONG_NAMES = [
    'Chauvet Professional Rogue R2X Wash Moving Head Fixture with Road Case',
    'Supercalifragilisticexpialidociousmegafixturename',      # one unbreakable word
    'DMX 5-pin XLR cable 10m',
    'Mic',
]


@pytest.fixture()
def items(app):
    ids = []
    for i, name in enumerate(LONG_NAMES):
        e = Equipment(name=name, barcode=f'ASSET-{i:03d}-' + 'X' * (30 if i == 0 else 3))
        db.session.add(e)
        db.session.flush()
        ids.append(e.id)
    db.session.commit()
    return ids


@pytest.mark.parametrize('layout,w,h', [
    ('portrait', 60, 80), ('portrait', 75, 100),
    ('landscape', 90, 55), ('landscape', 110, 65),
])
def test_tag_text_stays_inside_card(app, admin, items, monkeypatch, layout, w, h):
    drawn = []
    orig = Canvas.drawString

    def spy(self, x, y, text, *a, **k):
        drawn.append((x, y, self.stringWidth(text, self._fontname, self._fontsize), text))
        return orig(self, x, y, text, *a, **k)
    monkeypatch.setattr(Canvas, 'drawString', spy)

    r = admin.post('/equipment/generate-qrcodes', json={
        'equipment_ids': items, 'layout': layout,
        'card_width_mm': w, 'card_height_mm': h, 'base_url': 'http://x.test'})
    assert r.status_code == 200, r.get_json()
    assert r.data[:4] == b'%PDF'

    # Cards are laid out from x = 8mm with a 4mm gap; every string must sit
    # entirely inside one card's horizontal span.
    margin, gap, cw = 8 * mm, 4 * mm, w * mm
    for x, y, tw, text in drawn:
        col = int((x - margin) // (cw + gap))
        left = margin + col * (cw + gap)
        assert x >= left - 0.01 and x + tw <= left + cw + 0.01, \
            f'{text!r} overflows its {layout} {w}x{h} tag'

    # Nothing was silently dropped: every word of a normal long name appears.
    joined = ' '.join(t for *_, t in drawn)
    for word in ('Chauvet', 'Professional', 'Rogue'):
        assert word in joined
