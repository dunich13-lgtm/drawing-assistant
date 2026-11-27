"""Tests for tools/facade.py (NIN-15). Run: python -m pytest tests/test_facade.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import facade  # noqa: E402


def wall_ring(view, x0, y0, x1, y1, t=0.25):
    return {'view': view, 'kind': 'cell', 'outline': [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]],
            'holes': [[[x0 + t, y0 + t], [x1 - t, y0 + t], [x1 - t, y1 - t], [x0 + t, y1 - t], [x0 + t, y0 + t]]]}


def test_footprint_fills_rooms():
    fp = facade.footprint([wall_ring('A', 0, 0, 10, 8)], 'A')
    assert abs(fp.area - 80) < 0.01


def test_footprint_ignores_slabs_and_facade_elements():
    els = [wall_ring('A', 0, 0, 10, 8), {**wall_ring('A', 0, 0, 30, 30), 'kind': 'slab'},
           {**wall_ring('A', 0, 0, 30, 30), 'kind': 'object:facade:roof'}]
    assert abs(facade.footprint(els, 'A').area - 80) < 0.01


def seg(x0, y, x1, scale=100):   # one horizontal line in drawing units (cm)
    return {'layer': 'L', 'type': 'LINE', 'paths': [[(x0 * scale, y * scale), (x1 * scale, y * scale)]]}


def test_eave_band_lowest_long_pair_above_top_floor():
    sec = [{'id': 'S1', 'title': 'Фасада Юг', 'drawing_bbox_m': [0, 0, 20, 16], 'zero_y_m': 1.0, 'scale': 1.0}]
    ents = [seg(0, 1.0 + 0.5, 20),            # window sill band: below the top floor, ignored
            seg(0, 1.0 + 11.39, 20), seg(0, 1.0 + 11.49, 20),   # eave band
            seg(5, 1.0 + 14.3, 10)]           # short ridge line: not long enough
    lo, hi, where, widths = facade.eave_band(sec, ents, 0.01, 11.2)
    assert (lo, hi, where) == (11.39, 11.49, ['S1'])
    assert abs(widths[0] - 20) < 1e-6


def test_eave_band_needs_a_facade_title():
    sec = [{'id': 'S1', 'title': 'РАЗРЕЗ А-А', 'drawing_bbox_m': [0, 0, 20, 16], 'zero_y_m': 1.0, 'scale': 1.0}]
    assert facade.eave_band(sec, [seg(0, 12.39, 20), seg(0, 12.49, 20)], 0.01, 11.2) is None
