"""The tutorial: it plays on a fresh profile's first Start run, coaches three steps with a ghost finger, lets
nothing cost anything, never touches the score, the records or a saved run, and is skippable and replayable.

These tests use a fresh profile (tutorial=True); every other test starts with the tutorial already done."""
import json

import pytest

STORE = 'pathpatrol:v2'
RUN_KEY = 'pathpatrol:v2:run'
DESKTOP = {'width': 1280, 'height': 800}


def state(page):
    return page.evaluate('__pp.state()')


def coach(page):
    return page.locator('#toast').text_content()


def client(page, x, y):
    return page.evaluate('([x, y]) => __pp.toClient(x, y)', [x, y])


def press(page, x, y):
    c = client(page, x, y)
    page.mouse.move(c['x'], c['y'])
    page.mouse.down()


def move(page, x, y, steps=4):
    c = client(page, x, y)
    page.mouse.move(c['x'], c['y'], steps=steps)


def fresh_tutorial(open_page, **kwargs):
    """A fresh profile, the tutorial started through the real Start button, the simulation held still."""
    page = open_page(tutorial=True, viewport=kwargs.pop('viewport', DESKTOP), **kwargs)
    page.click('#startButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial'
    page.evaluate('__pp.freeze(true)')
    return page


def settings(page):
    return json.loads(page.evaluate(f"localStorage.getItem('{STORE}')"))['settings']


# ---- when it plays ---------------------------------------------------------------------------------------
def test_the_first_start_run_is_the_tutorial_and_skipping_it_goes_on_to_a_real_run(open_page):
    page = open_page(tutorial=True, viewport=DESKTOP)
    assert page.evaluate('__pp.storage.settings.tutorialDone') is False
    page.click('#startButton')
    st = state(page)
    assert st['phase'] == 'playing' and page.evaluate('__pp.game.run.mode') == 'tutorial'
    assert page.evaluate('__pp.storage.records.runs') == 0                         # practice is not a run
    assert len(st['patrols']) == 1 and st['level'] == 1
    speed = page.evaluate('Math.hypot(__pp.state().patrols[0].vx, __pp.state().patrols[0].vy)')
    assert speed == pytest.approx(14 * 0.45)                                     # one patrol, slow
    assert coach(page) == 'Start on the glowing edge' and page.locator('#toast').is_visible()
    assert page.locator('#pauseButton').get_attribute('data-state') == 'skip'
    assert page.locator('#pauseButton').get_attribute('aria-label') == 'Skip tutorial'
    assert page.locator('#restartButton').is_disabled()                            # nothing to restart in a tutorial

    page.click('#pauseButton')                                                     # the header button is Skip while coaching
    assert page.evaluate('__pp.game.run.mode') == 'normal' and page.evaluate('__pp.storage.records.runs') == 1
    assert settings(page)['tutorialDone'] is True
    assert coach(page) == 'Level 01 · clear 65%'                                   # the coach let go of the console line, so a real run's message shows
    assert page.locator('#pauseButton').get_attribute('aria-label') == 'Pause'

    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    page.click('#startButton')
    assert page.evaluate('__pp.game.run.mode') == 'normal'                        # the tutorial is offered once, not every time


def test_enter_on_the_title_also_starts_the_tutorial_for_a_new_player(open_page):
    page = open_page(tutorial=True, viewport=DESKTOP)
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial'


# ---- the three steps ----------------------------------------------------------------------------------------
def test_the_coach_moves_through_touch_drag_and_finish_and_then_offers_play(open_page):
    page = fresh_tutorial(open_page)
    assert page.evaluate('__pp.game.tutorial.step') == 1
    press(page, 34, 1)                                                              # a touch on the top edge
    assert coach(page) == 'Keep going into the field' and page.evaluate('__pp.game.tutorial.step') == 2
    move(page, 34, 6)
    page.evaluate('__pp.step(1)')
    assert page.evaluate('__pp.game.tutorial.step') == 2                            # a few cells are not "into the field" yet
    move(page, 34, 20)
    page.evaluate('__pp.step(1)')
    assert coach(page) == 'Now finish on any edge' and page.evaluate('__pp.game.tutorial.step') == 3
    move(page, 34, 71)
    page.mouse.up()
    assert state(page)['phase'] == 'clear' and page.locator('#clearOverlay').is_visible()
    assert page.locator('#clearEyebrow').text_content() == 'Tutorial complete' and page.locator('#clearTotal').text_content() == 'Nice work.'
    rows = page.evaluate("Object.fromEntries([...document.querySelectorAll('#tally dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent]))")
    assert rows['To clear a level'] == '65%' and 25 < float(rows['Claimed'].rstrip('%')) < 35
    assert page.locator('#nextLabel').text_content() == 'Play' and page.locator('#clearNote').is_visible()
    assert settings(page)['tutorialDone'] is True and not page.evaluate('__pp.game.tutorial.active')
    assert page.evaluate('({ ...__pp.storage.records, score: __pp.game.run.score, lives: __pp.game.run.lives })') == \
        {'bestScore': 0, 'bestClear': 0, 'bestLevel': 0, 'runs': 0, 'wins': 0, 'daily': {'streak': 0, 'best': 0, 'last': '', 'result': None}, 'score': 0, 'lives': 3}    # practice left no trace
    assert page.evaluate(f"localStorage.getItem('{RUN_KEY}')") is None                                    # and nothing to resume

    page.keyboard.press('Enter')                                                    # straight away: refused, like any win screen
    assert state(page)['phase'] == 'clear'
    page.evaluate('__pp.step(90)')
    page.keyboard.press('Enter')                                                    # Play: a real run
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.game.run.mode') == 'normal'
    assert page.evaluate('__pp.storage.records.runs') == 1 and page.locator('#clearOverlay').is_hidden()


def test_lifting_or_being_hit_sends_the_coach_back_to_the_start_at_no_cost(open_page):
    page = fresh_tutorial(open_page)
    press(page, 34, 1)
    move(page, 34, 20)
    page.evaluate('__pp.step(1)')
    assert page.evaluate('__pp.game.tutorial.step') == 3
    page.mouse.up()                                                                  # let go in the field
    assert coach(page) == 'Lifted early, no harm. Try again' and page.evaluate('__pp.game.tutorial.step') == 1
    assert page.evaluate('__pp.game.run.lives') == 3 and state(page)['phase'] == 'playing'

    press(page, 34, 1)                                                               # touch the edge, then let go before drawing anything
    assert page.evaluate('__pp.game.tutorial.step') == 2
    page.mouse.up()
    page.evaluate('__pp.step(1)')
    assert page.evaluate('__pp.game.tutorial.step') == 1 and coach(page) == 'Start on the glowing edge'

    page.evaluate('__pp.setPatrols([{ x: 34, y: 25 }])')                            # a patrol on the line to be drawn
    press(page, 34, 1)
    move(page, 34, 30, steps=10)
    assert coach(page) == 'A plane hit it: free here. Again' and page.evaluate('__pp.game.tutorial.step') == 1
    assert page.evaluate('__pp.game.run.lives') == 3 and page.evaluate('__pp.game.flash') > 0          # the flash, but nothing lost
    assert page.evaluate('__pp.route().gridRouteCells') == 0
    page.mouse.up()
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }])')
    press(page, 34, 1)                                                               # and it can be tried again at once
    assert page.evaluate('__pp.game.tutorial.step') == 2


def test_a_touch_in_the_middle_of_the_field_leaves_the_coach_message_alone(open_page):
    page = fresh_tutorial(open_page)
    press(page, 60, 36)                                                              # nowhere near an edge: normally this toasts a hint
    page.mouse.up()
    assert page.evaluate('__pp.game.tutorial.step') == 1 and coach(page) == 'Start on the glowing edge'
    assert 'Start on an edge' not in page.locator('#announcer').text_content()


def test_the_title_and_a_new_run_both_end_the_coaching(open_page):
    page = fresh_tutorial(open_page)
    assert page.evaluate('__pp.game.tutorial.active') is True
    page.evaluate('__pp.game.enterTitle()')
    assert page.evaluate('__pp.game.tutorial.active') is False
    assert 'visible' not in page.locator('#toast').get_attribute('class')              # the coach let go (it fades by opacity, which Playwright still calls visible)
    page.evaluate('__pp.game.startTutorial()')
    assert page.evaluate('__pp.game.tutorial.active') is True
    page.evaluate('__pp.game.newRun({ seed: "plain" })')                             # e.g. a debug call or a future entry point
    assert page.evaluate('__pp.game.tutorial.active') is False and page.locator('#pauseButton').get_attribute('data-state') == 'running'


def test_a_capture_too_small_to_count_asks_for_a_bigger_one_and_the_tutorial_goes_on(open_page):
    page = fresh_tutorial(open_page)
    press(page, 8, 1)                                                                # a cut across the top-left corner: about 0.2% of the board
    move(page, 8, 8)
    move(page, 1, 8)
    page.mouse.up()
    assert state(page)['phase'] == 'playing' and page.evaluate('__pp.game.tutorial.active') is True
    assert coach(page) == 'Too small. Cross the whole board' and page.evaluate('__pp.game.tutorial.step') == 1
    assert page.evaluate('__pp.storage.settings.tutorialDone') is False              # it is not done until the real thing


# ---- practice leaves nothing behind -----------------------------------------------------------------------------
def test_the_tutorial_never_touches_a_saved_run_the_score_or_the_records(open_page):
    page = open_page(viewport=DESKTOP)                                               # tutorial already done: this is the replay from Help
    page.evaluate('__pp.game.newRun({ seed: "keep" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40)')
    saved = page.evaluate(f"localStorage.getItem('{RUN_KEY}')")
    records = page.evaluate('__pp.storage.records')
    assert saved and records['bestScore'] == 3927 and records['runs'] == 1
    page.keyboard.press('h')                                                         # Help, opened mid-run (which pauses it)
    assert page.evaluate('__pp.state().phase') == 'paused'
    page.click('#tutorialButton')
    assert page.evaluate('document.getElementById("helpDialog").open') is False
    assert page.evaluate('__pp.game.run.mode') == 'tutorial' and page.evaluate('__pp.game.tutorial.origin') == 'help'
    assert page.evaluate(f"localStorage.getItem('{RUN_KEY}')") == saved              # starting the tutorial did not touch the saved run
    page.evaluate('__pp.freeze(true)')
    press(page, 34, 1)
    move(page, 34, 20)
    page.evaluate('__pp.step(1)')
    move(page, 34, 71)
    page.mouse.up()
    assert state(page)['phase'] == 'clear' and page.locator('#clearEyebrow').text_content() == 'Tutorial complete'
    assert page.evaluate('__pp.storage.records') == records                          # the same bests, the same run count
    assert page.evaluate(f"localStorage.getItem('{RUN_KEY}')") == saved              # and neither did playing it: not a byte
    assert page.evaluate('__pp.game.restartLevel()') is False                         # and a tutorial cannot be restarted

    page.evaluate('__pp.game.enterTitle()')                                          # back to the title: the real run is waiting
    assert page.locator('#resumeRunButton').is_visible() and '3,927 points' in page.locator('#savedLine').text_content()


def test_skipping_a_replayed_tutorial_returns_to_the_title_not_to_a_new_run(open_page):
    page = open_page(viewport=DESKTOP)
    page.keyboard.press('h')
    page.click('#tutorialButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial'
    page.click('#pauseButton')
    assert page.evaluate('__pp.state().phase') == 'title' and page.evaluate('__pp.storage.records.runs') == 0


def test_a_tutorial_in_progress_cannot_be_restarted_by_api_or_keys(open_page):
    page = fresh_tutorial(open_page)
    epoch = page.evaluate('__pp.state().clock.epoch')                                # restarting rebuilds the level, which bumps this
    patrol = page.evaluate('__pp.state().patrols')
    assert page.evaluate('__pp.game.restartLevel()') is False
    page.keyboard.press('r')
    page.keyboard.press('r')                                                          # R R restarts a real level; here it must do nothing
    st = state(page)
    assert st['clock']['epoch'] == epoch and st['patrols'] == patrol and page.evaluate('__pp.game.tutorial.active') is True


def test_pausing_the_tutorial_offers_resume_but_no_restart(open_page):
    page = fresh_tutorial(open_page)
    page.keyboard.press('p')
    assert state(page)['phase'] == 'paused' and page.locator('#pauseOverlay').is_visible()
    assert page.locator('#pauseRestartButton').is_hidden()
    assert page.locator('#pauseButton').get_attribute('aria-label') == 'Resume'      # the header button is Resume now, not Skip
    page.keyboard.press('p')
    assert page.locator('#pauseButton').get_attribute('aria-label') == 'Skip tutorial' and page.evaluate('__pp.game.tutorial.active')


# ---- the ghost finger ----------------------------------------------------------------------------------------------
def test_the_ghost_finger_script_sweeps_each_step_on_the_board(open_page):
    page = open_page(viewport=DESKTOP)
    got = page.evaluate("""async () => { const { Tutorial } = await import('/js/tutorial.js'); const { BOARD_H } = await import('/js/config.js');
      const t = new Tutorial({ on() {}, emit() {} }); const out = {};
      t.step = 1; out.edge = [0, 130, 260 * Math.PI, 1000].map((ms) => t.ghostAt(ms));
      t.step = 2; out.drag = [0, 750, 1500, 1800, 2199, 2200, 2950].map((ms) => t.ghostAt(ms).y);
      t.step = 3; out.finish = [0, 750, 1500, 2199, 2200].map((ms) => t.ghostAt(ms).y);
      out.inBoard = [1, 2, 3].every((s) => { t.step = s; for (let ms = 0; ms < 5000; ms += 37) { const g = t.ghostAt(ms); if (!(g.y >= 0 && g.y <= BOARD_H && g.x > 0 && g.x < 120)) return false; } return true; });
      return out; }""")
    assert all(g['x'] == 34 and g['y'] == 1 and g['moving'] is False and 0 <= g['pulse'] <= 1 for g in got['edge'])      # step 1: pulsing on the top edge
    assert got['drag'][0] == 1 and got['drag'][1] == pytest.approx(1 + 35 * 0.5) and got['drag'][2] == pytest.approx(36)  # sweeps to the middle...
    assert got['drag'][3] == pytest.approx(36) and got['drag'][4] == pytest.approx(36)                                   # ...waits there...
    assert got['drag'][5] == 1 and got['drag'][6] == pytest.approx(1 + 35 * 0.5, abs=0.05)                                # ...and starts over
    assert got['finish'][0] == 36 and got['finish'][2] == pytest.approx(71) and got['finish'][3] == pytest.approx(71) and got['finish'][4] == 36
    assert got['inBoard'] is True


def test_the_ghost_finger_is_drawn_in_the_right_place_on_the_board_in_both_orientations(open_page):
    for kwargs in ({'viewport': DESKTOP}, {'device': 'Pixel 7'}):
        page = open_page(tutorial=True, **kwargs)
        (page.tap if 'device' in kwargs else page.click)('#startButton')
        assert page.evaluate('__pp.game.run.mode') == 'tutorial'
        page.wait_for_function('__pp.renderer.ghost !== null')
        g = page.evaluate('__pp.renderer.ghost')
        assert g['x'] == 34 and g['y'] == 1                                          # step 1: waiting on the top edge
        rect = page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()")
        at = client(page, g['x'], g['y'])
        assert rect[0] < at['x'] < rect[2] and rect[1] < at['y'] < rect[3]           # on the canvas, whichever way the board is turned
        pixel = page.evaluate("""([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
          const s = document.createElement('canvas'); s.width = s.height = 1; const g = s.getContext('2d', { willReadFrequently: true });
          g.drawImage(c, Math.round((x - r.left) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1);
          return Array.from(g.getImageData(0, 0, 1, 1).data); }""", [at['x'], at['y']])
        assert pixel[0] > 120 and pixel[1] > 180                                      # the fingertip dot is light against the frame and the field


def test_the_ghost_is_only_ever_drawn_while_a_tutorial_is_playing(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.newRun({ seed: "plain" })')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('__pp.renderer.ghost') is None                              # a normal run never shows it
    page.keyboard.press('h')
    page.click('#tutorialButton')
    page.wait_for_function('__pp.renderer.ghost !== null')
    page.evaluate('__pp.game.enterTitle()')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('__pp.renderer.ghost') is None                              # and it stops with the tutorial


def test_reduced_motion_holds_the_ghost_at_the_end_of_the_gesture(open_page):
    page = open_page(tutorial=True, viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')
    page.click('#startButton')
    page.evaluate('__pp.freeze(true)')
    press(page, 34, 1)                                                                # step 2: the sweep would go from y = 1 to the middle
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    ys = []
    for _ in range(4):
        page.wait_for_timeout(250)
        ys.append(page.evaluate('__pp.renderer.ghost.y'))
    assert set(ys) == {36.0}                                                          # still, at the end of the path, whatever the time


# ---- the words ------------------------------------------------------------------------------------------------------
def test_every_coach_message_fits_the_console_line_of_the_smallest_phone(open_page):
    page = open_page(tutorial=True, viewport={'width': 320, 'height': 568}, dpr=2, has_touch=True, is_mobile=True)
    messages = page.evaluate("async () => { const { COACH } = await import('/js/tutorial.js'); return Object.values(COACH); }")
    assert len(messages) == 7 and max(len(m) for m in messages) <= 36
    page.tap('#startButton')
    fits = []
    for text in messages:
        page.evaluate("(text) => { const t = document.getElementById('toast'); t.textContent = text; t.classList.add('visible'); }", text)
        fits.append(page.evaluate("(() => { const t = document.getElementById('toast'); return t.scrollWidth <= t.clientWidth; })()"))
    assert all(fits), dict(zip(messages, fits))                                       # none is cut off with an ellipsis


def test_the_coach_is_announced_once_per_step_and_the_skip_button_has_a_name(open_page):
    page = fresh_tutorial(open_page)
    heard = lambda: page.locator('#announcer').text_content().replace('\xa0', '')      # noqa: E731
    assert 'Start on the glowing edge' in heard()
    press(page, 34, 1)
    assert heard() == 'Keep going into the field'                               # one message per change, not a pile
    assert page.locator('#pauseButton').get_attribute('aria-label') == 'Skip tutorial'
    page.mouse.up()


def test_the_help_dialog_offers_the_tutorial_from_the_title(open_page):
    page = open_page(viewport=DESKTOP)
    page.keyboard.press('?')
    assert page.locator('#tutorialButton').is_visible()
    page.click('#tutorialButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial' and page.evaluate('__pp.state().phase') == 'playing'
