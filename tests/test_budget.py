"""Budgets: what the offline shell weighs, and what a frame costs on a busy late level. They are set with room to spare (the frame
budget is ten times what is measured here), so they never flicker; they exist to catch a change that adds a library's worth of weight
or an accidental quadratic, and to make raising a budget a decision that is written down (the progress file's Plan changes)."""
import gzip
import pathlib
import statistics
import time

import make_sw                                                  # tools/ is on the path (conftest)
import pytest

SITE = pathlib.Path(__file__).resolve().parents[1] / 'site'

RAW_BUDGET = 350_000        # bytes: the whole offline shell as it lies on disk, fonts, icons and code (327 KB at 1.0.0)
WIRE_BUDGET = 170_000       # bytes: the same as GitHub Pages sends it, text compressed and the rest as it is (150 KB at 1.0.0)
TEXT = {'.js', '.css', '.html', '.svg', '.webmanifest'}
FRAME_MS = 4                # script time per frame, update and draw, averaged over half a second (about 0.4 ms measured on a laptop, 1 ms on WebKit)
LONGEST_FRAME_MS = 50       # and no single frame may be a long task (about 6 ms measured)


def test_the_offline_shell_stays_within_its_weight():
    raw = wire = 0
    heaviest = []
    for rel in make_sw.shell_files(SITE):
        data = (SITE / rel).read_bytes()
        size = len(gzip.compress(data, 6)) if pathlib.Path(rel).suffix in TEXT else len(data)
        raw += len(data)
        wire += size
        heaviest.append((len(data), rel))
    top = ', '.join(f'{rel} {n}' for n, rel in sorted(heaviest, reverse=True)[:4])
    assert raw <= RAW_BUDGET, f'the shell is {raw} bytes, over {RAW_BUDGET}; heaviest: {top}'
    assert wire <= WIRE_BUDGET, f'the shell is {wire} bytes on the wire, over {WIRE_BUDGET}; heaviest: {top}'
    assert raw > 200_000                                          # (and it really did count the shell)


VIEWS = [('desktop', dict(viewport={'width': 1280, 'height': 800}, dpr=1)),
         ('phone', dict(viewport={'width': 390, 'height': 844}, dpr=3, has_touch=True, is_mobile=True))]


@pytest.mark.parametrize('name,options', VIEWS, ids=[v[0] for v in VIEWS])
def test_a_busy_late_level_stays_inside_the_frame_budget(open_page, name, options):
    """Level 12: six patrols, three tracers, obstacles, real time for eight seconds, on a big and a small dense screen."""
    page = open_page(**options)
    page.evaluate("__pp.game.newRun({ seed: 'busy' }); __pp.game.startLevel(12); 0")
    info = page.evaluate('({ patrols: __pp.state().patrols.length, tracers: __pp.game.tracers.list.length })')
    assert info == {'patrols': 6, 'tracers': 3}
    windows = []
    for _ in range(16):
        time.sleep(0.5)
        windows.append(page.evaluate('({ ...__pp.loop.stats })'))
    assert page.evaluate('__pp.state().phase') == 'playing'
    average = statistics.median(w['avgMs'] for w in windows)
    worst = max(w['maxMs'] for w in windows)
    assert all(w['avgMs'] > 0 for w in windows[2:])                # the loop's own timer was running
    assert average < FRAME_MS and worst < LONGEST_FRAME_MS, f'a frame costs {average:.2f} ms on average and {worst:.1f} ms at worst'
