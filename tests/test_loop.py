"""The simulation runs on a fixed 1/120 s step fed by an accumulator, so the same stretch of time is the same game whatever the
display's refresh rate. The loop is driven by hand here: requestAnimationFrame is replaced by a queue the test empties with any
frame interval it likes, and the real loop code does the rest."""
DRIVER = """(() => { const queue = [];
  window.requestAnimationFrame = (callback) => { queue.push(callback); return queue.length; };
  window.__drive = (intervalMs, frames) => { let now = window.__driveNow || 5000; for (let i = 0; i < frames; i++) { now += intervalMs; for (const cb of queue.splice(0)) cb(now); } window.__driveNow = now; }; })();"""

RATES = [30, 60, 90, 120, 144]
SECONDS = 3
STEP_S = 1 / 120


def run_at(open_page, hz):
    page = open_page(init=[DRIVER])
    page.evaluate("__pp.game.newRun({ seed: 'hz' }); __pp.game.startLevel(5); 0")
    page.evaluate(f'__drive({1000 / hz}, {hz * SECONDS})')
    return page.evaluate('({ now: __pp.game.clock.now, phase: __pp.state().phase, frames: __pp.state().frames, patrols: __pp.state().patrols.map((p) => [p.x, p.y]) })')


def test_the_same_time_is_the_same_game_at_any_refresh_rate(open_page):
    runs = {hz: run_at(open_page, hz) for hz in RATES}
    for hz, run in runs.items():
        assert run['phase'] == 'playing' and run['frames'] == hz * SECONDS, (hz, run)          # every frame was really run, at its own interval
        assert run['now'] > SECONDS - 0.2, (hz, run['now'])
    reference = runs[120]
    for hz, run in runs.items():
        assert abs(run['now'] - reference['now']) <= 4 * STEP_S, (hz, run['now'], reference['now'])       # at most a few steps apart: the remainder a frame leaves over
        for (x, y), (rx, ry) in zip(run['patrols'], reference['patrols']):
            assert abs(x - rx) < 1.0 and abs(y - ry) < 1.0, (hz, run['patrols'], reference['patrols'])     # four steps at the fastest patrol are a unit
    for hz in (60, 90):                                                                       # where the frames divide the step evenly the game is the very same one
        assert runs[hz]['now'] == reference['now'] and runs[hz]['patrols'] == reference['patrols'], hz


def test_a_slow_frame_drops_time_instead_of_spiralling(open_page):
    """A stall (a backgrounded tab, a long task) is capped at 8 steps and the rest of the wait is dropped, so the game does not sprint
    to catch up, and the next frame is an ordinary one."""
    page = open_page(init=[DRIVER])
    page.evaluate("__pp.game.newRun({ seed: 'stall' }); __pp.game.startLevel(5); 0")
    page.evaluate('__drive(16.667, 5)')
    before = page.evaluate('__pp.game.clock.now')
    page.evaluate('__drive(5000, 1)')                                                         # one frame five seconds late
    stalled = page.evaluate('__pp.game.clock.now') - before
    assert 0 < stalled <= 8 * STEP_S + 1e-9, stalled                                          # eight steps, not six hundred
    page.evaluate('__drive(16.667, 60)')
    assert abs((page.evaluate('__pp.game.clock.now') - before - stalled) - 1.0) <= 2 * STEP_S      # and a second of ordinary frames is a second
