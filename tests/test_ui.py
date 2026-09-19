"""The UI shell as a player meets it: which screen shows, the dialogs and who owns the keyboard, settings,
spoken announcements, the input mode and the title's records line. Board drawing is in test_drawing.py."""
import json
import re

import pytest

STORE = 'pathpatrol:v2'
SCREENS = ('#startOverlay', '#pauseOverlay', '#endOverlay', '#crashOverlay')


def state(page):
    return page.evaluate('__pp.state()')


def start(page):
    page.click('#startButton')
    assert state(page)['phase'] == 'playing'


def shown(page):
    """The full-board screens currently visible (exactly one, or none while playing)."""
    return [selector for selector in SCREENS if page.locator(selector).is_visible()]


def is_open(page, dialog):
    return page.evaluate(f"document.getElementById('{dialog}').open")


def focused(page):
    return page.evaluate('document.activeElement && document.activeElement.id')


def seed_and_reload(page, blob):
    page.evaluate(f"localStorage.setItem('{STORE}', JSON.stringify({json.dumps(blob)}))")
    page.reload()
    page.wait_for_function('window.__pp !== undefined')


# ---- screens ------------------------------------------------------------------------------------
def test_exactly_one_screen_shows_for_each_phase(open_page):
    page = open_page()
    assert page.locator('#app').get_attribute('data-phase') == 'title' and shown(page) == ['#startOverlay']
    start(page)
    assert page.locator('#app').get_attribute('data-phase') == 'playing' and shown(page) == []
    page.keyboard.press('p')
    assert page.locator('#app').get_attribute('data-phase') == 'paused' and shown(page) == ['#pauseOverlay']
    page.keyboard.press('p')
    assert shown(page) == []
    for _ in range(3):
        page.evaluate('__pp.game.loseLife()')
    assert page.locator('#app').get_attribute('data-phase') == 'over' and shown(page) == ['#endOverlay']
    page.evaluate("__pp.game.crash(new Error('deliberate'))")
    assert page.locator('#app').get_attribute('data-phase') == 'crashed' and shown(page) == ['#crashOverlay']


def test_every_control_has_a_name_and_every_id_is_unique(open_page):
    page = open_page()
    got = page.evaluate("""() => {
      const nameOf = (b) => { const by = b.getAttribute('aria-labelledby'); const ref = by && document.getElementById(by);
        return (b.getAttribute('aria-label') || (ref && ref.textContent) || b.textContent).trim(); };
      const unnamed = [...document.querySelectorAll('button')].filter((b) => !nameOf(b)).map((b) => b.id || b.outerHTML);
      const ids = [...document.querySelectorAll('[id]')].map((e) => e.id);
      const duplicate = ids.filter((id, i) => ids.indexOf(id) !== i);
      const dangling = [...document.querySelectorAll('[aria-labelledby]')].filter((e) => !document.getElementById(e.getAttribute('aria-labelledby'))).map((e) => e.id);
      const switches = [...document.querySelectorAll('[role=switch]')].filter((e) => !['true', 'false'].includes(e.getAttribute('aria-checked'))).map((e) => e.id);
      return { unnamed, duplicate, dangling, switches }; }""")
    assert got == {'unnamed': [], 'duplicate': [], 'dangling': [], 'switches': []}


# ---- dialogs and the keyboard ---------------------------------------------------------------------
def test_settings_pauses_the_game_and_owns_the_keyboard_until_it_closes(open_page):
    page = open_page()
    start(page)
    before = state(page)
    page.focus('#settingsButton')                                  # the way a keyboard user gets there; a click does not focus a button in Safari
    page.keyboard.press('Enter')
    assert is_open(page, 'settingsDialog') and state(page)['phase'] == 'paused'
    for key in ('p', 'r', 'r', 't', 'm', 'h', '?'):                # each of these acts on the game when no dialog is open
        page.keyboard.press(key)
    after = state(page)
    assert after['phase'] == 'paused'                              # P did not resume it behind the dialog
    assert after['clock']['epoch'] == before['clock']['epoch']     # R R did not restart the level
    assert page.evaluate('__pp.storage.settings') == {'sound': True, 'theme': 'flight', 'motion': 'auto', 'showFps': False, 'tutorialDone': True}
    assert not is_open(page, 'helpDialog')

    page.keyboard.press('Escape')
    page.wait_for_function("!document.getElementById('settingsDialog').open")
    assert state(page)['phase'] == 'paused'                        # closing settings does not resume by itself
    assert focused(page) == 'settingsButton'                       # and focus goes back to where it came from
    page.keyboard.press('p')
    assert state(page)['phase'] == 'playing'


def test_help_opens_from_the_keyboard_and_closes_on_the_backdrop(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.keyboard.press('?')
    assert is_open(page, 'helpDialog')
    page.keyboard.press('Escape')
    assert not is_open(page, 'helpDialog')
    page.keyboard.press('h')
    assert is_open(page, 'helpDialog')
    box = page.locator('#helpDialog').bounding_box()
    page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)      # inside: stays open
    assert is_open(page, 'helpDialog')
    page.mouse.click(4, 4)                                                            # the backdrop: closes
    assert not is_open(page, 'helpDialog')
    assert focused(page) != 'helpDialog'


def test_closing_settings_disarms_a_half_finished_reset(open_page):
    page = open_page()
    page.click('#settingsButton')
    page.click('#resetStatsButton')
    assert page.locator('#resetStatsButton').text_content() == 'Tap again to reset'
    page.keyboard.press('Escape')
    # Closing must disarm it; the button's own 3 s timer must not be what does it, hence the tight timeout.
    page.wait_for_function("document.getElementById('resetStatsButton').textContent === 'Reset local records'", timeout=1000)


def test_enter_and_space_do_the_obvious_thing_exactly_once(open_page):
    page = open_page()
    assert focused(page) == 'startButton'                          # a keyboard user can start straight away
    page.keyboard.press('Enter')
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.storage.records.runs') == 1      # once, not twice
    page.keyboard.press('p')
    assert focused(page) == 'resumeButton'
    page.keyboard.press('Space')
    assert state(page)['phase'] == 'playing'
    for _ in range(3):
        page.evaluate('__pp.game.loseLife()')
    assert focused(page) == 'againButton'
    page.keyboard.press('Enter')
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.storage.records.runs') == 2


def test_enter_on_a_focused_button_presses_that_button_not_the_screen_shortcut(open_page):
    """Enter and Space start, resume or restart the current screen only when no control has focus. With the Help
    button focused on the title, Enter must open Help, not start a run and swallow the press."""
    page = open_page()
    page.focus('#helpButton')
    page.keyboard.press('Enter')
    assert is_open(page, 'helpDialog') and state(page)['phase'] == 'title'
    page.keyboard.press('Escape')
    page.wait_for_function("!document.getElementById('helpDialog').open")
    start(page)
    page.keyboard.press('p')
    assert state(page)['phase'] == 'paused'
    page.focus('#pauseButton')                                      # the header's Pause/Resume button, focused
    page.keyboard.press('Enter')
    assert state(page)['phase'] == 'playing'                        # exactly one action: resumed, not resumed-then-paused
    page.focus('#settingsButton')
    page.keyboard.press('Space')
    assert is_open(page, 'settingsDialog')


def test_enter_and_space_work_with_nothing_focused(open_page):
    page = open_page()
    page.evaluate('document.activeElement.blur()')
    assert focused(page) in (None, '')
    page.keyboard.press('Space')
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.storage.records.runs') == 1
    page.keyboard.press('Escape')
    page.evaluate('document.activeElement.blur()')
    page.keyboard.press('Enter')
    assert state(page)['phase'] == 'playing'
    page.keyboard.press('Enter')                                   # while playing, Enter does nothing
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.storage.records.runs') == 1


# ---- settings -------------------------------------------------------------------------------------
def test_the_sound_switch_and_the_header_button_stay_in_step(open_page):
    page = open_page()
    page.click('#settingsButton')
    assert page.locator('#soundSwitch').get_attribute('aria-checked') == 'true'
    page.click('#soundSwitch')
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'false'
    page.keyboard.press('Escape')
    page.click('#soundButton')
    page.click('#settingsButton')
    assert page.locator('#soundSwitch').get_attribute('aria-checked') == 'true'


def test_motion_follows_the_choice_and_the_operating_system(open_page):
    page = open_page()
    animated = "getComputedStyle(document.querySelector('#startOverlay .caret')).animationName !== 'none'"
    assert page.evaluate('__pp.renderer.reducedMotion') is False and page.evaluate(animated) is True

    page.emulate_media(reduced_motion='reduce')                    # "Auto" listens to the system, live
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    assert page.evaluate(animated) is False

    page.click('#settingsButton')
    page.click('[data-motion="full"]')                             # an explicit choice overrides the system
    assert page.evaluate('__pp.renderer.reducedMotion') is False and page.evaluate(animated) is True
    assert page.evaluate('document.documentElement.dataset.motion') == 'full'

    page.emulate_media(reduced_motion='no-preference')
    page.click('[data-motion="reduced"]')
    assert page.evaluate('__pp.renderer.reducedMotion') is True and page.evaluate(animated) is False
    assert page.locator('button[data-motion="reduced"]').get_attribute('aria-checked') == 'true'
    assert json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))['settings']['motion'] == 'reduced'
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert page.evaluate('__pp.renderer.reducedMotion') is True


def test_frame_stats_can_be_switched_on_and_off(open_page):
    page = open_page()
    assert page.locator('#fpsMeter').is_hidden() and page.evaluate('__pp.loop.onStats') is None
    page.click('#settingsButton')
    page.click('#fpsSwitch')
    page.keyboard.press('Escape')
    page.wait_for_function(r"/^\d+ fps · [\d.]+ ms · max [\d.]+$/.test(document.getElementById('fpsMeter').textContent)", timeout=4000)
    assert page.locator('#fpsMeter').is_visible()
    fps = int(re.match(r'(\d+) fps', page.locator('#fpsMeter').text_content()).group(1))
    assert 5 <= fps <= 250                                         # a real measurement, not a placeholder
    page.click('#settingsButton')
    page.click('#fpsSwitch')
    page.keyboard.press('Escape')
    assert page.locator('#fpsMeter').is_hidden() and page.evaluate('__pp.loop.onStats') is None


# ---- speaking --------------------------------------------------------------------------------------
def test_changes_are_announced_once_through_one_live_region(open_page):
    page = open_page()
    assert page.locator('#announcer').get_attribute('aria-live') == 'polite'
    assert page.locator('#toast').get_attribute('aria-hidden') == 'true'          # the console line is not read a second time
    page.evaluate('__pp.game.newRun({ seed: "announce" }); __pp.setPatrols([{ x: 100, y: 60 }])')     # a fixed board: the cut below claims 33%, not a win
    heard = lambda: page.locator('#announcer').text_content().replace('\xa0', '')  # noqa: E731
    page.wait_for_function("document.getElementById('announcer').textContent.includes('3 lives')")
    assert 'Level 01' in heard()
    page.evaluate('__pp.game.loseLife()')
    assert heard() == '2 lives left. Route intercepted — try again'                # raised in one tick, read as one sentence
    page.evaluate('__pp.cutLine("v", 40)')
    assert re.fullmatch(r'\d+\.\d percent cleared, [\d,]+ points', heard())
    for _ in range(2):
        page.evaluate('__pp.game.loseLife()')
    # one sentence, not three reads; a fresh profile's first score is always a new best
    assert re.fullmatch(r'0 lives left\. Run over\. [\d,]+ points, level 1, a new best score', heard())


def test_the_same_announcement_twice_in_a_row_is_still_spoken(open_page):
    page = open_page()
    read = "async () => { __pp.ui.announce('same'); await Promise.resolve(); return document.getElementById('announcer').textContent; }"
    first, second, third = (page.evaluate(read) for _ in range(3))
    assert first.replace('\xa0', '') == second.replace('\xa0', '') == 'same'
    assert first != second and second != third                     # the text really changes, so a screen reader re-reads it


# ---- input mode -------------------------------------------------------------------------------------
def test_the_input_mode_follows_the_pointer_and_never_moves_the_board(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    mode = "document.documentElement.dataset.input"
    geometry = "(() => { const r = (s) => { const b = document.querySelector(s).getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; }; return [r('#gameCanvas'), r('.bar'), r('.hud')]; })()"
    assert page.evaluate(mode) is None                             # nothing moved yet: the media queries decide
    page.mouse.move(300, 300)
    assert page.evaluate(mode) == 'mouse' and page.locator('#restartButton').is_visible()
    board = page.evaluate(geometry)
    page.evaluate("document.body.dispatchEvent(new PointerEvent('pointerdown', { pointerType: 'touch', isPrimary: true, bubbles: true }))")
    assert page.evaluate(mode) == 'touch' and page.locator('#restartButton').is_hidden()
    assert page.evaluate(geometry) == board                        # a touch must never land on a board that then shifts
    page.evaluate("document.body.dispatchEvent(new PointerEvent('pointermove', { pointerType: 'pen', isPrimary: true, bubbles: true }))")
    assert page.evaluate(mode) == 'mouse'                          # a pen is precise: it counts as a mouse
    assert page.evaluate(geometry) == board


def test_a_narrow_window_with_a_mouse_never_overflows_the_top_bar(open_page):
    """A phone-sized window can still have a mouse in use; the labels and key hints then have no room."""
    page = open_page(viewport={'width': 320, 'height': 568})
    page.mouse.move(100, 300)
    assert page.evaluate('document.documentElement.dataset.input') == 'mouse'
    got = page.evaluate("""() => { const bar = document.querySelector('.bar').getBoundingClientRect();
      const last = [...document.querySelectorAll('.actions > *')].filter((e) => e.offsetParent).pop().getBoundingClientRect();
      return { barRight: bar.right, lastRight: last.right, vw: innerWidth }; }""")
    assert got['lastRight'] <= got['vw'] and got['barRight'] <= got['vw']


# ---- the title's records line ---------------------------------------------------------------------
def test_the_title_reports_records_and_says_so_when_there_are_none(open_page):
    page = open_page()
    assert page.locator('#titleRecords').text_content() == '> no runs yet'
    seed_and_reload(page, {'v': 2, 'settings': {}, 'records': {'bestScore': 12480, 'bestClear': 61.5, 'bestLevel': 4, 'runs': 9, 'wins': 3}})
    assert page.locator('#titleRecords').text_content() == '> best 12,480 · clear 61.5% · top level 04 · 9 runs'
    seed_and_reload(page, {'v': 2, 'settings': {}, 'records': {'bestClear': 12, 'bestLevel': 0, 'runs': 1, 'wins': 0}})
    assert page.locator('#titleRecords').text_content() == '> clear 12.0% · 1 run'                    # only what exists is listed


def test_blocked_storage_is_said_on_the_title_for_every_device(open_page):
    page = open_page(init=["Storage.prototype.setItem = function () { throw new DOMException('quota exceeded', 'QuotaExceededError'); };"])
    assert page.locator('#titleRecords').text_content() == "Storage is blocked here, so records won't be saved."
    assert page.locator('#titleRecords').is_visible()
