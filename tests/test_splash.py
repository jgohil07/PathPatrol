"""The splash and the extra board behind it: what opens it, what it does to the game underneath while it shows, how the
board plays and ends, and that the ordinary game (its levels, records, saved run and look) is untouched by a visit."""
import json
import time

import pytest

STORE = 'pathpatrol:v2'
RUN_KEY = 'pathpatrol:v2:run'
DESKTOP = {'width': 1280, 'height': 800}

# The board, written out here on purpose: a change to it is a decision, not a side effect.
BLOCKS = [(44, 22, 18, 4), (74, 24, 4, 16), (58, 46, 18, 4), (42, 32, 4, 16), (12, 10, 8, 5), (100, 10, 8, 5), (12, 57, 8, 5), (100, 57, 8, 5)]
PATROLS = [(30, 18), (90, 54), (90, 18), (30, 54)]


def taps(page, count=5, selector='.brand'):
    page.evaluate('([n, sel]) => { const el = document.querySelector(sel); for (let i = 0; i < n; i++) el.click(); }', [count, selector])


def showing(page):
    return page.evaluate('!!document.querySelector(".egg:not(.out)")')


def phase(page):
    return page.evaluate('__pp.state().phase')


def mode(page):
    return page.evaluate('__pp.game.run ? __pp.game.run.mode : null')


def open_extra(page):
    """Five taps, then a click on the splash: the extra board is running, the simulation held still."""
    taps(page)
    page.wait_for_selector('.egg')
    page.click('.egg')
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"')
    page.evaluate('__pp.freeze(true)')


def gone(page, timeout=3000):
    page.wait_for_function('!document.querySelector(".egg")', timeout=timeout)


def records(page):
    return json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))['records']


def settings(page):
    return json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))['settings']


def client(page, x, y):
    return page.evaluate('([x, y]) => __pp.toClient(x, y)', [x, y])


# ---- what opens it -------------------------------------------------------------------------------------------
def test_five_taps_on_the_name_show_it_and_it_says_who_made_the_game(open_page):
    page = open_page(viewport=DESKTOP)
    assert not showing(page)
    page.focus('#startButton')
    taps(page)
    page.wait_for_selector('.egg')
    node = page.locator('.egg')
    assert node.get_attribute('role') == 'dialog' and node.get_attribute('aria-modal') == 'true'
    assert node.get_attribute('aria-label') == 'Built by Jay'
    text = node.text_content().lower()
    assert 'jay' in text and 'indie dev' in text
    box = node.bounding_box()
    assert box['width'] >= DESKTOP['width'] - 1 and box['height'] >= DESKTOP['height'] - 1                   # it covers the page
    assert page.evaluate('document.querySelector("#app").inert') is True                                       # nothing behind it can be reached
    assert page.evaluate('document.activeElement === document.body')                                          # and nothing keeps the focus behind it


def test_four_taps_are_not_enough_and_neither_are_five_spread_over_more_than_the_window(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page, 4)
    time.sleep(0.15)
    assert not showing(page)
    page.evaluate("""() => { let now = Date.now() + 10000; Date.now = () => now; const brand = document.querySelector('.brand');
      for (let i = 0; i < 5; i++) { brand.click(); now += 1600; } }""")           # each pair is inside 3 s, five are not
    time.sleep(0.15)
    assert not showing(page)
    taps(page)                                                                    # five quick ones straight after still count
    page.wait_for_selector('.egg')


def test_taps_anywhere_else_do_nothing(open_page):
    page = open_page(viewport=DESKTOP)
    for selector in ('h1.title', '#levelLabel', '#scoreLabel', '#versionLabel', '.tagline'):
        taps(page, 8, selector)
    time.sleep(0.15)
    assert not showing(page) and phase(page) == 'title'


def test_it_opens_from_the_title_and_nowhere_else(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    assert phase(page) == 'playing'
    page.evaluate('__pp.freeze(true)')
    taps(page, 10)
    time.sleep(0.15)
    assert not showing(page) and mode(page) == 'normal'                        # during a run
    page.evaluate('__pp.game.pause("manual")')
    taps(page, 10)
    time.sleep(0.15)
    assert not showing(page)                                                     # while paused
    page.evaluate('__pp.game.resume()')
    page.evaluate('__pp.step(200)')
    page.evaluate('for (let i = 0; i < 3; i++) __pp.game.loseLife()')
    assert phase(page) == 'over'
    taps(page, 10)
    time.sleep(0.15)
    assert not showing(page)                                                     # on the game-over card
    page.evaluate('__pp.game.enterTitle()')
    page.evaluate('__pp.ui.openHelp()')
    taps(page, 10)
    time.sleep(0.15)
    assert not showing(page)                                                     # under a dialog
    page.keyboard.press('Escape')
    taps(page)
    page.wait_for_selector('.egg')                                              # ...and from the title again


def test_the_taps_are_used_up_once_they_have_opened_it(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    page.wait_for_selector('.egg')
    page.click('.egg')
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"')
    page.evaluate('__pp.game.enterTitle()')
    gone(page)
    taps(page, 1)
    time.sleep(0.15)
    assert not showing(page)                                                     # one tap does not borrow the five before it
    taps(page, 3)
    time.sleep(0.15)
    assert not showing(page)                                                     # four in all is still not enough
    taps(page, 1)
    page.wait_for_selector('.egg')


def test_nothing_opens_it_twice_at_once(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    taps(page)
    taps(page, 20)
    page.wait_for_selector('.egg')
    assert page.locator('.egg').count() == 1


# ---- the splash itself ---------------------------------------------------------------------------------------
def test_a_click_closes_it_at_once_and_the_extra_board_begins(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    page.wait_for_selector('.egg')
    assert phase(page) == 'title'                                                # still the title while it shows
    page.click('.egg')
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"')
    st = page.evaluate('__pp.state()')
    assert st['phase'] == 'playing' and st['level'] == 1 and st['target'] == 60 and len(st['patrols']) == 4 and len(st['obstacles']) == 8
    assert page.evaluate('document.documentElement.hasAttribute("data-extra")')
    assert page.evaluate('document.querySelector("#app").inert') is False
    assert 'Sector 0' in page.locator('#toast').text_content()
    gone(page)


def test_escape_does_the_same_and_does_not_also_pause(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    page.wait_for_selector('.egg')
    page.keyboard.press('Escape')
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"', timeout=1500)         # at once, not after its three seconds
    time.sleep(0.2)
    assert phase(page) == 'playing'                                              # the key that closed it did not pause the board
    gone(page)


def test_left_alone_it_fades_by_itself_after_three_seconds_and_leaves_nothing_behind(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    page.wait_for_selector('.egg')
    time.sleep(2.3)
    assert showing(page) and phase(page) == 'title'                              # still showing just before the time
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"', timeout=2500)
    gone(page)
    assert page.locator('.egg').count() == 0


def test_while_it_shows_nothing_behind_it_reacts(open_page):
    page = open_page(viewport=DESKTOP)
    before = page.evaluate('[__pp.storage.settings.sound, __pp.storage.settings.theme, __pp.storage.records.runs]')
    page.focus('#startButton')
    taps(page)
    page.wait_for_selector('.egg')
    for key in ('Enter', ' ', 'r', 'r', 'p', 'm', 't', 'ArrowRight', 'ArrowUp', 'w'):
        page.keyboard.press(key)
    page.keyboard.press('Tab')
    page.keyboard.press('Enter')
    time.sleep(0.3)
    assert phase(page) == 'title' and showing(page)
    assert page.evaluate('[__pp.storage.settings.sound, __pp.storage.settings.theme, __pp.storage.records.runs]') == before


def test_closing_it_early_leaves_no_timer_behind_to_cut_the_next_one_short(open_page):
    page = open_page(viewport=DESKTOP)
    opened = time.monotonic()
    taps(page)
    page.wait_for_selector('.egg')
    page.click('.egg')                                                            # early: the first one's three seconds are still running
    page.wait_for_function('__pp.game.run && __pp.game.run.mode === "extra"')
    page.evaluate('__pp.game.enterTitle()')
    time.sleep(1.1)
    taps(page)
    page.wait_for_selector('.egg')
    time.sleep(max(0, opened + 3.45 - time.monotonic()))                          # just after the first one's three seconds would have run out
    assert showing(page) and phase(page) == 'title'


# ---- the board -------------------------------------------------------------------------------------------------
def test_the_board_is_the_one_written_down_and_every_open_cell_can_be_reached(open_page):
    page = open_page(viewport=DESKTOP)
    open_extra(page)
    st = page.evaluate('__pp.state()')
    assert [(o['x'], o['y'], o['w'], o['h']) for o in st['obstacles']] == BLOCKS
    assert page.locator('#levelLabel').text_content() == '00'
    assert [(round(p['x']), round(p['y'])) for p in st['patrols']] == PATROLS
    for p in st['patrols']:
        assert (p['vx'] ** 2 + p['vy'] ** 2) ** 0.5 == pytest.approx(20)
        assert abs(p['vx']) > 0.2 * 20 and abs(p['vy']) > 0.2 * 20               # never running along an axis
    border = page.evaluate("import('/js/grid.js').then((g) => g.BORDER)")
    for x, y, w, h in BLOCKS:
        assert page.evaluate('([a, b]) => __pp.cell(a, b)', [(x + w / 2) * 2, (y + h / 2) * 2]) == border
    assert page.evaluate('__pp.game.grid.claimUnreachable(__pp.game._patrolSeeds())') == 0        # every open cell is somewhere a patrol can go
    assert page.evaluate('[__pp.game.tracers.list.length, __pp.game.powerups.enabled]') == [0, False]          # no tracers and no pickups on it
    # corridors: every gap between two blocks, and between a block and the frame (2 units), is at least 6 wide
    def gap(a, b):
        dx = max(0, a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))
        dy = max(0, a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))
        return max(dx, dy)
    for i, a in enumerate(BLOCKS):
        assert min(a[0] - 2, a[1] - 2, 118 - (a[0] + a[2]), 70 - (a[1] + a[3])) >= 6
        for b in BLOCKS[i + 1:]:
            assert gap(a, b) >= 6, (a, b)
    for px, py in PATROLS:
        assert all(gap((px - 1.35, py - 1.35, 2.7, 2.7), b) >= 3 for b in BLOCKS)


def test_it_cannot_begin_anywhere_but_the_title(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    assert page.evaluate('__pp.game.startExtra()') is False and mode(page) == 'normal'


def test_it_is_practice_no_life_is_lost_nothing_scores_and_the_records_and_saved_run_are_left_alone(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')                                                    # a real run first, so there is a saved run to protect
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 20)')
    saved = page.evaluate(f"localStorage.getItem('{RUN_KEY}')")
    assert saved
    page.evaluate('__pp.game.enterTitle()')
    before = page.evaluate(f"localStorage.getItem('{STORE}')")
    open_extra(page)
    page.evaluate('for (let i = 0; i < 5; i++) __pp.game.loseLife()')
    st = page.evaluate('__pp.state()')
    assert st['lives'] == 3 and st['phase'] == 'playing' and st['flash'] > 0        # the red flash, nothing lost
    page.evaluate('__pp.setPatrols([{ x: 60, y: 30 }]); __pp.cutLine("v", 6)')
    st = page.evaluate('__pp.state()')
    assert st['cleared'] > 1 and page.evaluate('__pp.game.run.score') == 0
    assert page.evaluate(f"localStorage.getItem('{STORE}')") == before               # records and settings, byte for byte
    assert page.evaluate(f"localStorage.getItem('{RUN_KEY}')") == saved              # and the run that was waiting
    page.evaluate('__pp.game.enterTitle()')
    assert page.evaluate('__pp.game.saved !== null')                                 # still offered on the title
    assert page.locator('#resumeRunButton').is_visible()


def test_claiming_enough_shows_its_own_finish_screen_and_goes_back_to_the_title(open_page):
    page = open_page(viewport=DESKTOP)
    before = page.evaluate(f"localStorage.getItem('{STORE}')")
    open_extra(page)
    page.evaluate('__pp.setPatrols([{ x: 60, y: 6 }]); __pp.cutLine("h", 14)')
    assert phase(page) == 'clear' and page.evaluate('__pp.game.tally.extra') is True
    assert page.locator('#clearEyebrow').text_content() == 'Sector 0 cleared'
    assert page.locator('#clearTotal').text_content() == 'Well played.'
    assert page.locator('#nextLabel').text_content() == 'Back to title'
    rows = page.locator('#tally').text_content()
    assert 'Claimed' in rows and 'Time' in rows
    page.click('#clearOverlay')                                                       # too soon: the tap that won must not skip it
    assert phase(page) == 'clear'
    page.evaluate('__pp.step(90)')
    page.click('#nextButton')
    assert phase(page) == 'title' and mode(page) is None
    assert not page.evaluate('document.documentElement.hasAttribute("data-extra")')
    assert page.evaluate(f"localStorage.getItem('{STORE}')") == before                # no win, no best level, no run counted


def test_its_pause_screen_has_a_way_out_and_no_restart(open_page):
    page = open_page(viewport=DESKTOP)
    open_extra(page)
    assert page.evaluate('__pp.state().phase') == 'playing'
    page.click('#pauseButton')
    assert phase(page) == 'paused'
    assert page.locator('#leaveButton').is_visible() and not page.locator('#pauseRestartButton').is_visible()
    assert page.locator('#restartButton').is_disabled()
    level = page.evaluate('__pp.game.level.cleared + ":" + __pp.game.clock.epoch')
    page.keyboard.press('r')
    page.keyboard.press('r')
    assert page.evaluate('__pp.game.level.cleared + ":" + __pp.game.clock.epoch') == level and phase(page) == 'paused'
    page.click('#leaveButton')
    assert phase(page) == 'title' and mode(page) is None
    assert not page.evaluate('document.documentElement.hasAttribute("data-extra")')


def test_an_ordinary_run_has_no_leave_button_and_can_be_restarted(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    page.click('#pauseButton')
    assert phase(page) == 'paused'
    assert not page.locator('#leaveButton').is_visible() and page.locator('#pauseRestartButton').is_visible()


def test_nothing_of_it_is_saved_so_a_reload_lands_on_the_title(open_page):
    page = open_page(viewport=DESKTOP)
    open_extra(page)
    page.evaluate('__pp.setPatrols([{ x: 60, y: 30 }]); __pp.cutLine("v", 6)')
    page.evaluate('document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("pagehide"))')
    assert page.evaluate(f"localStorage.getItem('{RUN_KEY}')") is None
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert phase(page) == 'title' and page.evaluate('__pp.game.saved') is None
    assert not page.locator('#resumeRunButton').is_visible()


def test_you_can_draw_on_it_with_the_pointer_and_a_capture_counts_towards_its_target(open_page):
    page = open_page(viewport=DESKTOP)
    open_extra(page)
    page.evaluate('__pp.setPatrols([{ x: 100, y: 62 }])')
    start, end = client(page, 30, 1), client(page, 30, 71)
    page.mouse.move(start['x'], start['y'])
    page.mouse.down()
    page.mouse.move(end['x'], end['y'], steps=12)
    page.mouse.up()
    st = page.evaluate('__pp.state()')
    assert 15 < st['cleared'] < 40 and st['phase'] == 'playing' and page.evaluate('__pp.game.run.score') == 0


# ---- its look --------------------------------------------------------------------------------------------------
def pixel(page, x, y):
    c = client(page, x, y)
    return page.evaluate("""([cx, cy]) => { const canvas = document.querySelector('#gameCanvas'); const r = canvas.getBoundingClientRect();
      const one = document.createElement('canvas'); one.width = one.height = 1; const g = one.getContext('2d', { willReadFrequently: true });
      g.drawImage(canvas, Math.round((cx - r.left) * canvas.width / r.width), Math.round((cy - r.top) * canvas.height / r.height), 1, 1, 0, 0, 1, 1);
      const d = g.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; }""", [c['x'], c['y']])


def test_its_colours_are_its_own_on_the_board_and_in_the_page_and_go_back_afterwards(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }])')
    time.sleep(0.15)
    ordinary = pixel(page, 30, 36)
    aqua = page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--aqua").trim()')
    assert aqua == '#72f4d1' and ordinary[1] > ordinary[0] + 20                        # a teal field
    page.evaluate('__pp.game.enterTitle()')
    open_extra(page)
    time.sleep(0.15)
    purple = pixel(page, 30, 36)
    assert purple[0] > purple[1] + 20 and purple[2] > purple[1] + 40                   # a violet field, whatever the shading
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--aqua").trim()') == '#ff7bf0'
    rim = pixel(page, 41.75, 40)                                                       # open ground against the left bar: its rim is magenta, not the ordinary aqua
    assert rim[1] < 65, rim
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 20)')
    time.sleep(0.15)
    ink = pixel(page, 8.3, 40)                                                         # claimed ground: a violet-black, not the ordinary blue-black
    assert ink[1] < 13 and ink[2] > ink[1], ink
    page.evaluate('__pp.game.enterTitle()')
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }])')
    time.sleep(0.15)
    assert pixel(page, 30, 36) == ordinary                                             # exactly as before
    assert page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--aqua").trim()') == aqua


def test_a_visit_leaves_the_ordinary_game_exactly_as_it_was(open_page):
    fresh = open_page(viewport=DESKTOP)
    fresh.click('#startButton')
    expected = fresh.evaluate('({ ...__pp.state(), clock: 0, frames: 0, fit: 0 })')
    page = open_page(viewport=DESKTOP)
    open_extra(page)
    page.evaluate('__pp.game.enterTitle()')
    page.click('#startButton')
    got = page.evaluate('({ ...__pp.state(), clock: 0, frames: 0, fit: 0 })')
    assert got == expected                                                            # the same level 1 as ever: same patrol, same everything
    assert mode(page) == 'normal' and got['level'] == 1 and len(got['patrols']) == 1
    assert not page.locator('#leaveButton').is_visible()
    assert page.locator('#levelLabel').text_content() == '01'
    assert records(page)['runs'] == 1                                                  # the run counted, the visit did not


def test_the_extra_board_can_be_visited_again_and_again(open_page):
    page = open_page(viewport=DESKTOP)
    for _ in range(3):
        open_extra(page)
        assert page.evaluate('__pp.state().obstacles.length') == 8
        page.evaluate('__pp.game.enterTitle()')
        gone(page)
        assert phase(page) == 'title'


# ---- layout, motion and the page's policy ---------------------------------------------------------------------------
@pytest.mark.parametrize('size', [(320, 568), (360, 640), (390, 844), (844, 390), (768, 1024), (1920, 1080)], ids=lambda s: f'{s[0]}x{s[1]}')
def test_it_is_legible_and_centred_at_every_size(open_page, size):
    page = open_page(viewport={'width': size[0], 'height': size[1]})
    taps(page)
    page.wait_for_selector('.egg')
    time.sleep(0.9)                                                                   # the entrance is done
    box = page.locator('.egg-stage').bounding_box()
    assert box['x'] >= 0 and box['y'] >= 0 and box['x'] + box['width'] <= size[0] and box['y'] + box['height'] <= size[1]
    assert abs(box['x'] + box['width'] / 2 - size[0] / 2) < 2 and abs(box['y'] + box['height'] / 2 - size[1] / 2) < 2


def test_with_reduced_motion_it_does_not_animate_and_still_disappears(open_page):
    page = open_page(viewport=DESKTOP, reduced_motion='reduce')
    taps(page)
    page.wait_for_selector('.egg')
    assert page.evaluate('getComputedStyle(document.querySelector(".egg-key")).animationName') == 'none'
    assert page.evaluate('getComputedStyle(document.querySelector(".egg")).opacity') == '1'
    page.click('.egg')
    page.wait_for_function('getComputedStyle(document.querySelector(".egg")).opacity === "0"', timeout=1000)      # (a transition of 0.01 ms, so a moment)
    gone(page)


def test_it_needs_no_inline_style_and_sits_above_everything(open_page):
    page = open_page(viewport=DESKTOP)
    taps(page)
    page.wait_for_selector('.egg')
    assert page.evaluate('document.querySelector(".egg").hasAttribute("style")') is False
    assert page.evaluate('[...document.querySelectorAll(".egg *")].every((n) => !n.hasAttribute("style"))')
    css = page.evaluate('({ p: getComputedStyle(document.querySelector(".egg")).position, z: getComputedStyle(document.querySelector(".egg")).zIndex })')
    assert css == {'p': 'fixed', 'z': '50'}
    assert page.evaluate('document.elementFromPoint(640, 400).closest(".egg") !== null')
