"""Page-level tests: the real DOM, buttons, keyboard, timing and storage, as a player meets them.
Each of the prototype's defects reproduced in Phase 0 has a regression test here (D-numbers in names)."""
import json

import pytest

STORE = 'pathpatrol:v2'
LEGACY = 'color-divide-records-v1'


def state(page):
    return page.evaluate('__pp.state()')


def hearts(page):
    return page.locator('#lives .life:not(.lost)').count()


def start(page):
    page.click('#startButton')
    assert state(page)['phase'] == 'playing'


def reload_ready(page):
    page.reload()
    page.wait_for_function('window.__pp !== undefined')


# ---- boot ---------------------------------------------------------------------------------------
def test_boots_clean_and_shows_the_title(open_page):
    page = open_page()
    assert page.locator('#startOverlay').is_visible()
    for hidden in ('#pauseOverlay', '#endOverlay', '#crashOverlay'):
        assert page.locator(hidden).is_hidden()
    page.wait_for_function('__pp.state().frames > 3')
    assert state(page)['phase'] == 'title'
    assert page.locator('#levelLabel').inner_text() == '01'
    assert page.locator('#targetLabel').inner_text() == '65%'
    assert page.locator('#runnerLabel').inner_text() == '1 PLANE'
    assert page.locator('#pauseButton').is_disabled() and page.locator('#restartButton').is_disabled()


@pytest.mark.parametrize('dpr', [1, 2, 3])
def test_d8_canvas_backing_store_follows_the_screen(open_page, dpr):
    page = open_page(viewport={'width': 1280, 'height': 800}, dpr=dpr)
    got = page.evaluate("""() => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect(); return { w: c.width, h: c.height, cssW: r.width, cssH: r.height }; }""")
    ratio = min(dpr, 2)                                   # capped at 2x
    assert abs(got['w'] - got['cssW'] * ratio) <= 1 and abs(got['h'] - got['cssH'] * ratio) <= 1
    assert got['cssW'] > 600                              # and the board actually fills its frame


def test_resizing_refits_the_canvas(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    before = state(page)['fit']
    page.set_viewport_size({'width': 900, 'height': 700})
    page.wait_for_function(f"__pp.state().fit.cssW < {before['cssW'] - 50}")
    after = state(page)['fit']
    style = page.evaluate("document.getElementById('gameCanvas').style.width")
    assert style == f"{after['cssW']}px" and after['pxW'] == round(after['cssW'] * page.evaluate('Math.min(devicePixelRatio, 2)'))


# ---- run flow -----------------------------------------------------------------------------------
def test_starting_a_run_shows_the_hud_and_patrols_move(open_page):
    page = open_page()
    start(page)
    st = state(page)
    assert st['lives'] == 3 and st['level'] == 1 and len(st['patrols']) == 1
    assert page.locator('#startOverlay').is_hidden()
    assert page.locator('#levelLabel').inner_text() == '01'
    assert hearts(page) == 3 and page.locator('#lives').get_attribute('aria-label') == '3 lives'
    assert page.locator('#pauseButton').is_enabled() and page.locator('#restartButton').is_enabled()
    assert page.locator('#pauseButton').inner_text().startswith('Pause')
    first = st['patrols'][0]
    page.wait_for_function(f"(() => {{ const p = __pp.state().patrols[0]; return p.x !== {first['x']} || p.y !== {first['y']}; }})()")
    assert page.locator('#runsPlayed').inner_text() == '1'


def test_d12_lives_label_follows_the_lives(open_page):
    page = open_page()
    start(page)
    page.evaluate('__pp.game.loseLife()')
    assert page.locator('#lives').get_attribute('aria-label') == '2 lives' and hearts(page) == 2
    page.evaluate('__pp.game.loseLife()')
    assert page.locator('#lives').get_attribute('aria-label') == '1 life' and hearts(page) == 1


def test_d4_game_over_offers_a_fresh_run_not_a_restart(open_page):
    page = open_page()
    start(page)
    for _ in range(3):
        page.evaluate('__pp.game.loseLife()')
    assert state(page)['phase'] == 'over'
    assert page.locator('#endOverlay').is_visible()
    assert 'level 01' in page.locator('#endSummary').inner_text()
    assert page.locator('#restartButton').is_disabled() and page.locator('#pauseButton').is_disabled()
    page.click('#againButton')
    st = state(page)
    assert st['phase'] == 'playing' and st['lives'] == 3 and st['level'] == 1
    assert hearts(page) == 3 and page.locator('#endOverlay').is_hidden()
    assert page.locator('#runsPlayed').inner_text() == '2'


def test_d5_win_banner_survives_pause_and_cannot_be_restarted(open_page):
    page = open_page()
    start(page)
    page.evaluate('__pp.forceWin()')
    st = state(page)
    assert st['phase'] == 'clear' and st['cleared'] == 100
    assert page.locator('#restartButton').is_disabled()
    page.click('#pauseButton')
    assert state(page)['phase'] == 'paused' and page.locator('#pauseOverlay').is_visible()
    page.wait_for_timeout(1700)                           # longer than the whole win delay
    st = state(page)
    assert st['phase'] == 'paused' and st['level'] == 1   # the prototype's timers would have moved on by now
    page.click('#resumeButton')
    assert state(page)['phase'] == 'clear'
    page.wait_for_function('__pp.state().level === 2', timeout=4000)
    assert state(page)['phase'] == 'playing'
    assert page.locator('#levelsWon').inner_text() == '1' and page.locator('#bestLevel').inner_text() == '01'


def test_restart_button_rebuilds_the_same_level(open_page):
    page = open_page()
    start(page)
    page.evaluate('__pp.freeze(true)')
    first = state(page)['patrols']
    page.evaluate('__pp.step(60)')
    assert state(page)['patrols'] != first
    page.click('#restartButton')
    st = state(page)
    assert st['patrols'] == first and st['phase'] == 'playing' and st['lives'] == 3


# ---- storage ------------------------------------------------------------------------------------
def test_d9_blocked_storage_does_not_stop_the_game(open_page):
    page = open_page(init=["Storage.prototype.setItem = function () { throw new DOMException('quota exceeded', 'QuotaExceededError'); };"])
    assert state(page)['persistent'] is False
    start(page)
    assert "won't be saved" in page.locator('#storageNote').inner_text()
    page.evaluate('__pp.forceWin()')                       # records are written on a win; must not throw
    assert state(page)['phase'] == 'clear'


def test_d15_reset_needs_two_taps_and_keeps_the_theme(open_page):
    page = open_page()
    seed = {'v': 2, 'settings': {'sound': False, 'theme': 'drive'}, 'records': {'bestClear': 61.5, 'bestLevel': 4, 'runs': 9, 'wins': 3}}
    page.evaluate(f"localStorage.setItem('{STORE}', JSON.stringify({json.dumps(seed)}))")
    reload_ready(page)
    assert page.locator('#bestClear').inner_text() == '61.5%' and page.locator('#bestLevel').inner_text() == '04'
    assert page.locator('#runsPlayed').inner_text() == '9' and page.locator('#levelsWon').inner_text() == '3'
    assert 'active' in page.locator('#driveButton').get_attribute('class')
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'false'

    page.click('#resetStatsButton')                        # first tap only arms it
    assert page.locator('#resetStatsButton').inner_text() == 'Tap again to reset'
    assert page.locator('#runsPlayed').inner_text() == '9'
    page.wait_for_timeout(3300)                            # ...and it disarms itself
    assert page.locator('#resetStatsButton').inner_text() == 'Reset local records'
    page.click('#resetStatsButton')
    assert page.locator('#runsPlayed').inner_text() == '9'

    page.click('#resetStatsButton')                        # second tap within the window resets
    assert page.locator('#runsPlayed').inner_text() == '0' and page.locator('#bestClear').inner_text() == '0.0%'
    stored = json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))
    assert stored['records'] == {'bestClear': 0, 'bestLevel': 0, 'runs': 0, 'wins': 0}
    assert stored['settings'] == {'sound': False, 'theme': 'drive'}


def test_d11_mute_is_remembered_across_reloads(open_page):
    page = open_page()
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'true'
    page.click('#soundButton')
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'false'
    reload_ready(page)
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'false'
    assert json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))['settings']['sound'] is False


def test_prototype_records_and_theme_are_migrated(open_page):
    page = open_page()
    legacy = json.dumps({'bestClear': 55.5, 'bestLevel': 4, 'runs': 9, 'wins': 3, 'theme': 'drive'})
    page.evaluate(f"localStorage.removeItem('{STORE}'); localStorage.setItem('{LEGACY}', {json.dumps(legacy)})")
    reload_ready(page)
    assert page.locator('#bestClear').inner_text() == '55.5%' and page.locator('#runsPlayed').inner_text() == '9'
    assert 'active' in page.locator('#driveButton').get_attribute('class')
    assert page.locator('#runnerLabel').inner_text() == '1 CAR'
    assert page.evaluate(f"localStorage.getItem('{LEGACY}')") == legacy         # the old key is left alone


def test_theme_button_switches_visuals_and_is_remembered(open_page):
    page = open_page()
    page.click('#driveButton')
    assert page.locator('#driveButton').get_attribute('aria-pressed') == 'true' and page.locator('#flightButton').get_attribute('aria-pressed') == 'false'
    assert page.locator('#runnerLabel').inner_text() == '1 CAR'
    assert page.evaluate('__pp.renderer.theme') == 'drive'
    reload_ready(page)
    assert page.evaluate('__pp.renderer.theme') == 'drive'


# ---- keyboard -----------------------------------------------------------------------------------
def test_d10_shortcuts_ignore_modifier_chords_and_work_plain(open_page):
    page = open_page()
    start(page)
    theme = lambda: page.evaluate('__pp.storage.settings.theme')     # noqa: E731
    for chord in ('Meta+p', 'Control+p', 'Alt+p', 'Meta+d', 'Control+f', 'Control+t', 'Meta+t', 'Alt+m', 'Control+r'):
        page.keyboard.press(chord)
    assert state(page)['phase'] == 'playing' and theme() == 'flight'
    assert page.evaluate('__pp.storage.settings.sound') is True

    page.keyboard.press('p')
    assert state(page)['phase'] == 'paused'
    page.keyboard.press('p')
    assert state(page)['phase'] == 'playing'
    page.keyboard.press('Escape')
    assert state(page)['phase'] == 'paused'
    page.keyboard.press('Escape')
    assert state(page)['phase'] == 'paused'                           # Escape only ever pauses
    page.keyboard.press('p')
    page.keyboard.press('t')
    assert theme() == 'drive'
    page.keyboard.press('m')
    assert page.evaluate('__pp.storage.settings.sound') is False


def test_r_twice_restarts_and_once_only_asks(open_page):
    page = open_page()
    start(page)
    page.evaluate('__pp.freeze(true)')
    initial = page.evaluate("""async () => { const { Grid } = await import('/js/grid.js'); const { buildLevel } = await import('/js/level.js');
      const lvl = buildLevel(1, __pp.game.run.seed, new Grid()); return lvl.patrols.map((p) => ({ x: p.x, y: p.y, vx: p.vx, vy: p.vy })); }""")
    page.evaluate('__pp.step(90)')
    assert state(page)['patrols'] != initial
    page.keyboard.press('r')
    assert page.locator('#toast').inner_text() == 'Press R again to restart the level'
    assert state(page)['patrols'] != initial                           # nothing happened yet
    page.keyboard.press('r')
    assert state(page)['patrols'] == initial


# ---- visibility and idling ----------------------------------------------------------------------
@pytest.mark.parametrize('how', ['blur', 'pagehide', 'hidden'])
def test_d13_leaving_the_page_pauses_and_returning_counts_down(open_page, how):
    page = open_page()
    start(page)
    page.evaluate({
        'blur': "window.dispatchEvent(new Event('blur'))",
        'pagehide': "window.dispatchEvent(new Event('pagehide'))",
        'hidden': "Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'));",
    }[how])
    st = state(page)
    assert st['phase'] == 'paused' and st['pauseReason'] == 'auto'
    assert page.locator('#pauseTitle').inner_text() == 'Paused while you were away.'
    if how == 'hidden':
        page.evaluate('delete document.hidden')
    page.click('#resumeButton')
    assert state(page)['phase'] == 'countdown'
    assert page.locator('#pauseEyebrow').text_content() == 'Resuming'      # raw text: the CSS upper-cases what inner_text() returns
    assert page.locator('#pauseTitle').text_content() in ('3', '2')
    page.wait_for_function("__pp.state().phase === 'playing'", timeout=5000)
    assert page.locator('#pauseOverlay').is_hidden()


def test_a_manual_pause_resumes_at_once(open_page):
    page = open_page()
    start(page)
    page.click('#pauseButton')
    assert page.locator('#pauseButton').inner_text().startswith('Resume')
    assert page.locator('#pauseTitle').inner_text() == 'Take a breath.'
    page.click('#resumeButton')
    assert state(page)['phase'] == 'playing'


def test_d13_idle_screens_stop_redrawing(open_page):
    page = open_page()
    start(page)
    a = state(page)['frames']
    page.wait_for_timeout(500)
    assert state(page)['frames'] - a >= 10                             # playing: drawing every frame
    page.click('#pauseButton')
    settled = state(page)['frames']
    page.wait_for_timeout(800)
    assert state(page)['frames'] - settled <= 1                        # paused: (almost) nothing


# ---- safety net ---------------------------------------------------------------------------------
def test_an_uncaught_error_stops_the_game_and_says_so(open_page):
    page = open_page()
    start(page)
    page.evaluate("setTimeout(() => { throw new Error('boom from the test'); }, 0)")
    page.wait_for_function("__pp.state().phase === 'crashed'")
    assert page.locator('#crashOverlay').is_visible()
    assert 'boom from the test' in page.locator('#crashDetail').inner_text()      # shown because ?debug=1
    frames = state(page)['frames']
    page.wait_for_timeout(300)
    assert state(page)['frames'] == frames                                        # the loop stopped drawing
    page.wait_for_timeout(200)
    page.problems.clear()                                                        # the error above was on purpose
