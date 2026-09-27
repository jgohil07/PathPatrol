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

RAW_BUDGET = 420_000        # bytes: the whole offline shell as it lies on disk, fonts, icons and code (327 KB at 1.0.0; raised
                            # from 350 KB for round 2's art and mechanics, the user's decision: see the round 2 progress file)
WIRE_BUDGET = 190_000       # bytes: the same as GitHub Pages sends it, text compressed and the rest as it is (150 KB at 1.0.0; was 170 KB)
TEXT = {'.js', '.css', '.html', '.svg', '.webmanifest'}
FRAME_MS = 8                # script time per frame, update and draw, averaged over half a second: ten times what a laptop measures (0.4 ms; WebKit 1 ms), so
                            # that a slow shared CI machine passes and a change that makes frames ten times dearer does not (the plan's own goal is 4 ms)
LONGEST_FRAME_MS = 100      # and no single frame a long task (about 6 ms measured): this one is a stall, whatever the machine


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
    """Level 31, the hardest the curve gets: six patrols, three tracers, five obstacles, real time for eight seconds, on a big and a small dense screen."""
    page = open_page(**options)
    page.evaluate("__pp.game.newRun({ seed: 'busy' }); __pp.game.startLevel(31); 0")
    info = page.evaluate('({ patrols: __pp.state().patrols.length, tracers: __pp.game.tracers.list.length })')
    assert info == {'patrols': 6, 'tracers': 3}
    windows = []
    for _ in range(16):
        time.sleep(0.5)
        windows.append(page.evaluate('({ ...__pp.loop.stats })'))
    assert page.evaluate('__pp.state().phase') == 'playing'
    average = statistics.median(w['avgMs'] for w in windows)
    worst = max(w['maxMs'] for w in windows)
    # The loop ran in every window (it counted frames) and its timer measured work in some: WebKit's clock ticks in whole
    # milliseconds, so a half-second of frames costing ~0.07 ms each can round to exactly 0 (round 1 asked for > 0 in every window).
    assert all(w['fps'] > 0 for w in windows[2:]) and any(w['avgMs'] > 0 for w in windows[2:])
    assert average < FRAME_MS and worst < LONGEST_FRAME_MS, f'a frame costs {average:.2f} ms on average and {worst:.1f} ms at worst'


@pytest.mark.parametrize('name,options', VIEWS, ids=[v[0] for v in VIEWS])
def test_a_busy_late_level_holds_its_frames_on_a_slow_phones_cpu(open_page, engine, name, options):
    """The same level with the CPU slowed four times (a mid-range phone's stand-in; a DevTools call, so Chromium only), now
    with the round-2 scenery: ripples, cloud shadows, foam, the sprite cache and a capture's flood. The budgets are the
    same generous ones as above, so a slow CI machine passes and a change that makes frames ten times dearer does not.
    (Measured at 4x: 0.1 ms median, 1 ms worst; a level start with its new textures, 12 ms, once.)"""
    if engine != 'chromium':
        pytest.skip('CPU throttling is a Chromium DevTools call')
    page = open_page(**options)
    page.evaluate("__pp.game.newRun({ seed: 'busy' }); __pp.game.startLevel(31); 0")
    cdp = page.context.new_cdp_session(page)
    cdp.send('Emulation.setCPUThrottlingRate', {'rate': 4})
    try:
        # A small capture from the frame and back, so its flood runs too (unless a patrol happens to cut it: then a hit).
        page.evaluate('(() => { const r = __pp.game.route; r.begin(1, 20); r.move(8, 20); r.move(8, 24); r.move(1, 24); })()')
        windows = []
        for _ in range(12):
            time.sleep(0.5)
            windows.append(page.evaluate('({ ...__pp.loop.stats })'))
        assert page.evaluate('__pp.state().phase') == 'playing'
        # Steady play, as the average: the first two windows hold the level start and the capture, one-off costs that CI's
        # software-rendered, 4x-throttled runner stretched past 100 ms (13 ms here at 4x); the unthrottled test above keeps them.
        steady = windows[2:]
        average = statistics.median(w['avgMs'] for w in steady)
        worst = max(w['maxMs'] for w in steady)
        assert all(w['fps'] > 0 for w in steady) and any(w['avgMs'] > 0 for w in steady)      # (see above)
        assert average < FRAME_MS and worst < LONGEST_FRAME_MS, f'a throttled frame costs {average:.2f} ms on average and {worst:.1f} ms at worst'
    finally:
        cdp.send('Emulation.setCPUThrottlingRate', {'rate': 1})
