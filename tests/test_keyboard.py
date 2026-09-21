"""Drawing with the keyboard: arrows or WASD move a cursor through the same route engine a pointer uses, at a fixed speed,
on the game clock. The tests press real keys, hold the simulation still, and step it by hand, so every number is exact.
They cover what a player relies on (each key goes the way it says on the screen, whichever way the board is turned; a
route that closes, is hit or is cancelled sends the cursor back and waits for a fresh press; Backspace; a pointer taking
over) and what must never happen (a stuck key, a hijacked page key, a cursor lost in the field)."""
import pytest

DESKTOP = {'width': 1280, 'height': 800}
PORTRAIT = {'width': 390, 'height': 844}


def play(page, patrols='[{ x: 110, y: 64 }]', level=1, seed='keys'):
    """A run on `level` with these patrols, the simulation held still: steps are taken by hand. Starting a run from a script
    leaves focus on the (now hidden) Start button until the browser's next-frame focus fix-up; a person cannot press a key
    that fast, a test can, so the button is let go of here."""
    page.evaluate(f'__pp.game.newRun({{ seed: "{seed}" }}); __pp.game.startLevel({level}); __pp.setPatrols({patrols}); __pp.freeze(true); document.activeElement && document.activeElement.blur()')


def step(page, n):
    page.evaluate(f'__pp.step({n})')


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


CURSOR = """(() => { const g = __pp.game, r = g.route, p = g.pilot;
  return { x: p.x, y: p.y, tipx: r.tip.x, tipy: r.tip.y, mode: r.mode, cells: r.cells.length, down: r.down, active: p.active, halted: p.halted,
           anchor: { cx: r.anchor.cx, cy: r.anchor.cy }, lives: g.run.lives, phase: g.phase, cleared: g.level.cleared, combo: g.run.combo, gridRoute: __pp.route().gridRouteCells }; })()"""


def cursor(page):
    return page.evaluate(CURSOR)


def claim_left_half(page):
    """Claim everything left of x = 60, so there is safe ground to move about on (the patrol is on the right)."""
    page.evaluate("""(() => { const g = __pp.game, x = 120, cells = [];
      for (let y = 0; y < g.grid.h; y++) if (g.grid.get(x, y) === 0) cells.push(g.grid.index(x, y)); g.commitCapture(cells); })()""")


def put_cursor(page, x, y):
    """Park the cursor on safe ground (stopping the pilot first so it engages afresh)."""
    page.evaluate(f'__pp.game.pilot.stop(); __pp.game.pilot.x = {x}; __pp.game.pilot.y = {y}')


# ---- the basics ------------------------------------------------------------------------------------------------
def test_nothing_shows_until_a_key_is_pressed_and_the_first_one_arms_the_cursor_on_the_top_edge(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    got = cursor(page)
    assert got['active'] is False and got['down'] is False and got['mode'] == 'idle'
    page.keyboard.down('ArrowDown')
    got = cursor(page)
    assert got['active'] is True and got['down'] is True and got['mode'] == 'armed'
    assert (got['tipx'], got['tipy']) == (60, 1)                                        # the middle of the top edge
    page.keyboard.up('ArrowDown')


def test_a_held_arrow_draws_straight_down_at_thirty_units_a_second(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.keyboard.down('ArrowDown')
    step(page, 120)                                                                     # one second
    got = cursor(page)
    assert got['mode'] == 'drawing' and got['tipx'] == 60 and got['tipy'] == pytest.approx(31, abs=1e-6)     # 30 units from y = 1
    assert got['cells'] > 50 and got['gridRoute'] == got['cells']
    step(page, 120)
    assert cursor(page)['tipy'] == pytest.approx(61, abs=1e-6)                           # and the same again: a steady 30 u/s
    page.keyboard.up('ArrowDown')


def test_reaching_the_far_edge_closes_the_route_and_the_cursor_waits_for_a_fresh_press(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.keyboard.down('ArrowDown')
    step(page, 300)                                                                     # 70 units at 30 u/s is 2.3 s: the edge is reached and passed
    got = cursor(page)
    assert got['cleared'] > 25 and got['mode'] == 'armed' and got['cells'] == 0 and got['gridRoute'] == 0     # captured: the left or right side is claimed
    assert got['halted'] is True and got['tipy'] < 72                                    # and the cursor stopped at the edge rather than running on
    here = (got['tipx'], got['tipy'])
    step(page, 120)
    assert (cursor(page)['tipx'], cursor(page)['tipy']) == here                          # the key is still down, and nothing moves
    page.keyboard.up('ArrowDown')
    page.keyboard.down('ArrowUp')                                                       # a fresh press goes on from there
    step(page, 20)
    assert cursor(page)['tipy'] < here[1]
    page.keyboard.up('ArrowUp')


# ---- which way is which -------------------------------------------------------------------------------------------
@pytest.mark.parametrize('label,viewport,touch', [('landscape', DESKTOP, False), ('portrait', PORTRAIT, True)])
def test_each_key_moves_the_cursor_that_way_on_the_screen_whichever_way_the_board_is_turned(open_page, label, viewport, touch):
    page = open_page(viewport=viewport, has_touch=touch, is_mobile=touch)
    assert page.evaluate('__pp.state().fit.rotated') == (label == 'portrait')
    play(page)
    claim_left_half(page)
    wanted = {'ArrowRight': (1, 0), 'd': (1, 0), 'ArrowLeft': (-1, 0), 'a': (-1, 0), 'ArrowDown': (0, 1), 's': (0, 1), 'ArrowUp': (0, -1), 'w': (0, -1)}
    for key, (dx, dy) in wanted.items():
        put_cursor(page, 30, 36)
        before = page.evaluate('__pp.toClient(30, 36)')
        page.keyboard.down(key)
        step(page, 40)
        page.keyboard.up(key)
        got = cursor(page)
        after = page.evaluate(f'__pp.toClient({got["tipx"]}, {got["tipy"]})')
        moved = (after['x'] - before['x'], after['y'] - before['y'])
        length = (moved[0] ** 2 + moved[1] ** 2) ** 0.5
        assert length > 30, (label, key, moved)
        assert moved[0] / length == pytest.approx(dx, abs=1e-6) and moved[1] / length == pytest.approx(dy, abs=1e-6), (label, key, moved)
        assert got['mode'] == 'armed' and got['lives'] == 3                             # safe ground: sliding, no route


def test_the_last_key_steers_and_letting_go_falls_back_to_the_one_still_held(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    claim_left_half(page)
    put_cursor(page, 30, 36)
    page.keyboard.down('ArrowDown')
    step(page, 20)
    assert (cursor(page)['x'], cursor(page)['y']) == pytest.approx((30, 41), abs=1e-6)          # 20 steps of 0.25
    page.keyboard.down('ArrowRight')                                                    # both held: the newer one steers
    step(page, 20)
    assert (cursor(page)['x'], cursor(page)['y']) == pytest.approx((35, 41), abs=1e-6)
    page.keyboard.up('ArrowRight')                                                      # the older one takes over again
    step(page, 20)
    assert (cursor(page)['x'], cursor(page)['y']) == pytest.approx((35, 46), abs=1e-6)
    page.keyboard.up('ArrowDown')
    step(page, 20)
    assert (cursor(page)['x'], cursor(page)['y']) == pytest.approx((35, 46), abs=1e-6)          # nothing held: nothing moves


def test_auto_repeat_neither_speeds_the_cursor_up_nor_restarts_it(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    claim_left_half(page)
    put_cursor(page, 30, 36)
    page.keyboard.down('ArrowDown')
    for _ in range(5):
        page.keyboard.down('ArrowDown')                                                 # the operating system's repeats
    step(page, 40)
    assert cursor(page)['y'] == pytest.approx(46, abs=1e-6)                             # 40 steps of 0.25, as with no repeats
    page.keyboard.up('ArrowDown')
    step(page, 10)
    assert cursor(page)['y'] == pytest.approx(46, abs=1e-6)                             # and the first release is enough


# ---- the route and the rules of Xonix --------------------------------------------------------------------------------
def test_stopping_in_the_field_leaves_the_route_live_and_a_patrol_can_still_hit_it(open_page):
    page = open_page(viewport=DESKTOP)
    play(page, patrols='[{ x: 75, y: 8, vx: -9, vy: 0 }]')                              # crossing the route's column after a while
    page.keyboard.down('ArrowDown')
    step(page, 60)                                                                      # 15 units down
    page.keyboard.up('ArrowDown')
    got = cursor(page)
    assert got['mode'] == 'drawing' and got['cells'] > 20 and got['lives'] == 3
    still = (got['tipx'], got['tipy'])
    step(page, 60)
    assert (cursor(page)['tipx'], cursor(page)['tipy']) == still and cursor(page)['mode'] == 'drawing'     # let go: it stays where it is, live
    step(page, 240)                                                                     # the patrol arrives
    got = cursor(page)
    assert got['lives'] == 2                                                            # and the standing route costs a life


def test_a_hit_sends_the_cursor_back_to_where_the_route_began_and_it_waits_for_a_fresh_press(open_page):
    page = open_page(viewport=DESKTOP)
    play(page, patrols='[{ x: 60, y: 30 }]')                                            # parked in the way
    page.keyboard.down('ArrowDown')
    step(page, 130)
    got = cursor(page)
    assert got['lives'] == 2 and got['mode'] == 'armed' and got['cells'] == 0 and got['gridRoute'] == 0
    assert (got['tipx'], got['tipy']) == pytest.approx((got['anchor']['cx'] * 0.5 + 0.25, got['anchor']['cy'] * 0.5 + 0.25), abs=1e-9)      # on the cell it began from
    assert got['tipy'] < 3 and got['halted'] is True
    step(page, 60)                                                                      # the key is still down: nothing moves
    assert cursor(page)['tipy'] == got['tipy'] and cursor(page)['lives'] == 2
    page.keyboard.up('ArrowDown')
    page.keyboard.down('ArrowDown')                                                     # a fresh press: off it goes again
    step(page, 20)
    assert cursor(page)['mode'] == 'drawing' and cursor(page)['tipy'] > got['tipy']
    page.keyboard.up('ArrowDown')


def test_a_key_pressed_right_after_a_hit_is_not_lost(open_page):
    """The hit happens inside a step; the cursor goes back to where the route began the next time it is looked at. A press
    that arrives in between must be honoured, not swallowed by that going back."""
    page = open_page(viewport=DESKTOP)
    play(page, patrols='[{ x: 60, y: 30 }]')
    page.keyboard.down('ArrowDown')
    got = page.evaluate("""(() => { const g = __pp.game; let n = 0; while (g.run.lives === 3 && n++ < 400) __pp.step(1);       // stop on the step of the hit
      const r = g.route; return { lives: g.run.lives, mode: r.mode, steps: n }; })()""")
    assert got['lives'] == 2 and got['mode'] == 'spent'                                 # hit, and not yet looked at by the cursor
    page.keyboard.down('ArrowRight')                                                    # a new key before the next step
    step(page, 20)
    after = cursor(page)
    assert after['x'] == pytest.approx(60.25 + 5, abs=1e-6) and after['y'] < 3 and after['mode'] == 'armed'    # back on the edge, then 20 steps of 0.25 along it: the press counted
    page.keyboard.up('ArrowRight'); page.keyboard.up('ArrowDown')


def test_backspace_drops_the_route_breaks_the_combo_and_puts_the_cursor_back(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.evaluate('__pp.game.run.combo = 1.75')
    page.keyboard.down('ArrowDown')
    step(page, 80)
    page.keyboard.up('ArrowDown')
    began = cursor(page)['anchor']
    assert cursor(page)['mode'] == 'drawing' and cursor(page)['cells'] > 30
    page.keyboard.press('Backspace')
    got = cursor(page)
    assert got['mode'] == 'armed' and got['cells'] == 0 and got['gridRoute'] == 0 and got['lives'] == 3          # erased, free
    assert got['combo'] == 1                                                            # but not for nothing
    assert got['anchor'] == began and got['tipy'] < 3                                    # back on the cell it began from
    page.keyboard.down('ArrowDown')                                                     # and the next key starts a new route from there
    step(page, 20)
    assert cursor(page)['mode'] == 'drawing'
    page.keyboard.up('ArrowDown')


def test_backspace_with_no_route_to_drop_does_nothing(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.evaluate('__pp.game.run.combo = 1.75')
    page.keyboard.press('Backspace')                                                    # no cursor yet
    assert cursor(page)['active'] is False and cursor(page)['combo'] == 1.75
    page.keyboard.down('ArrowRight'); step(page, 10); page.keyboard.up('ArrowRight')   # sliding along the edge, not drawing
    page.keyboard.press('Backspace')
    got = cursor(page)
    assert got['active'] is True and got['mode'] == 'armed' and got['combo'] == 1.75


@pytest.mark.parametrize('label,viewport,touch,across', [('landscape', DESKTOP, False, 'ArrowDown'), ('portrait', PORTRAIT, True, 'ArrowLeft')])
def test_a_route_drawn_by_keyboard_across_the_board_captures_whichever_way_the_board_is_turned(open_page, label, viewport, touch, across):
    """From the middle of the top edge to the bottom one: straight down the screen on the wide board, straight left on the
    turned one (where the board's top edge is at the screen's right)."""
    page = open_page(viewport=viewport, has_touch=touch, is_mobile=touch)
    assert page.evaluate('__pp.state().fit.rotated') == (label == 'portrait')
    play(page)
    page.keyboard.down(across)
    step(page, 300)
    page.keyboard.up(across)
    got = cursor(page)
    assert got['cleared'] > 25 and got['mode'] == 'armed' and got['cells'] == 0 and got['lives'] == 3
    assert page.evaluate('__pp.game.level.routes.length') == 1


def test_a_capture_by_keyboard_scores_like_any_other(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.keyboard.down('ArrowDown')
    step(page, 300)
    page.keyboard.up('ArrowDown')
    got = page.evaluate('({ score: __pp.game.run.score, captures: __pp.game.run.stats.captures, routes: __pp.game.level.routes.length })')
    assert got['score'] > 1000 and got['captures'] == 1 and got['routes'] == 1          # points, the tally and the drawn line, as for a swipe


def test_a_pickup_is_taken_by_drawing_through_it_with_the_keyboard_too(open_page):
    page = open_page(viewport=DESKTOP)
    play(page, level=3)
    page.evaluate('__pp.game.powerups.place("shield", 60, 20)')
    page.keyboard.down('ArrowDown')
    step(page, 100)
    page.keyboard.up('ArrowDown')
    assert page.evaluate('__pp.game.powerups.active("shield")') is True and page.evaluate('__pp.game.powerups.pickup') is None


def test_a_tracer_catches_a_route_the_cursor_has_stopped_on_and_sends_it_back_but_cannot_catch_one_being_drawn(open_page):
    page = open_page(viewport=DESKTOP)
    watch = 'window.__ev = []; __pp.game.on("tracer", (e) => window.__ev.push(e.type)); 0'       # (ends in 0: evaluate calls a function it is handed, and on() returns one that unsubscribes)
    play(page, level=4)
    page.evaluate(f'__pp.game.tracers.place([{{ x: 55, y: 2, dir: 1 }}]); {watch}')           # a tracer crawling towards where the route begins
    page.keyboard.down('ArrowDown'); step(page, 20); page.keyboard.up('ArrowDown')            # five units down, then stop
    step(page, 240)
    got = cursor(page)
    assert page.evaluate('window.__ev') == ['chase', 'caught'] and got['lives'] == 2          # it noticed the standing route and ran the tip down
    assert got['mode'] == 'armed' and got['halted'] is True and got['tipy'] < 3               # and the cursor is back where the route began, waiting
    play(page, level=4, seed='keys-2')                                                        # the same again, but the key stays down: 30 u/s beats its 26.4
    page.evaluate(f'__pp.game.tracers.place([{{ x: 55, y: 2, dir: 1 }}]); {watch}')
    page.keyboard.down('ArrowDown'); step(page, 300); page.keyboard.up('ArrowDown')
    got = cursor(page)
    assert 'caught' not in page.evaluate('window.__ev') and got['lives'] == 3 and got['cleared'] > 25       # it never caught up, and the route closed


# ---- who owns the route engine ------------------------------------------------------------------------------------------
def test_a_pointer_taking_over_puts_the_cursor_away_and_the_keys_stop_steering(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.keyboard.down('ArrowDown')
    step(page, 40)
    assert cursor(page)['active'] is True
    at = page.evaluate('__pp.toClient(20, 1)')
    page.mouse.move(at['x'], at['y'])
    page.mouse.down()                                                                   # a real press on the frame
    got = cursor(page)
    assert got['active'] is False and got['down'] is True and got['mode'] == 'armed' and got['tipx'] == pytest.approx(20, abs=0.3)
    step(page, 40)                                                                      # the arrow key is still down: it must not move the pointer's route
    assert cursor(page)['tipx'] == pytest.approx(20, abs=0.3) and cursor(page)['tipy'] == pytest.approx(1, abs=0.3) and cursor(page)['mode'] == 'armed'
    page.mouse.up()
    page.keyboard.up('ArrowDown')


def test_keys_do_nothing_while_a_pointer_holds_the_route(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    at = page.evaluate('__pp.toClient(20, 1)')
    page.mouse.move(at['x'], at['y'])
    page.mouse.down()
    page.keyboard.down('ArrowDown')
    step(page, 40)
    got = cursor(page)
    assert got['active'] is False and got['tipx'] == pytest.approx(20, abs=0.3) and got['mode'] == 'armed'
    page.mouse.up()
    page.keyboard.up('ArrowDown')


def test_a_pointer_that_was_down_when_play_stopped_does_not_lock_the_keyboard_out(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    at = page.evaluate('__pp.toClient(20, 1)'); into = page.evaluate('__pp.toClient(20, 20)')
    page.mouse.move(at['x'], at['y']); page.mouse.down(); page.mouse.move(into['x'], into['y'])
    assert cursor(page)['mode'] == 'drawing'
    page.evaluate('__pp.game.pause("manual")')                                          # the pointer is let go of when play stops
    assert cursor(page)['down'] is False
    page.evaluate('__pp.game.resume(); __pp.game.tick(3.1)')
    frame(page)                                                                         # (the hidden Resume button gives up its focus at the next frame)
    page.mouse.up()
    page.keyboard.down('ArrowDown')
    step(page, 10)
    assert cursor(page)['active'] is True and cursor(page)['down'] is True
    page.keyboard.up('ArrowDown')


def test_a_pause_lets_go_of_every_key_and_the_cursor_goes_back_to_safe_ground(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.keyboard.down('ArrowDown')
    step(page, 60)
    assert cursor(page)['mode'] == 'drawing'
    page.evaluate('__pp.game.pause("manual")')
    got = cursor(page)
    assert got['active'] is False and got['down'] is False and got['cells'] == 0 and got['gridRoute'] == 0    # the route is erased, as for a pointer
    assert got['y'] < 3                                                                 # and the cursor is back on the edge, not out in the field
    page.evaluate('__pp.game.resume(); __pp.game.tick(3.1)')
    step(page, 60)                                                                      # the key is still physically down, but its press belonged to before
    assert cursor(page)['active'] is False and cursor(page)['y'] < 3 and cursor(page)['cells'] == 0
    page.keyboard.down('ArrowRight')                                                    # a different key, while the old one is physically still down
    step(page, 20)
    assert cursor(page)['active'] is True and cursor(page)['x'] > 64 and cursor(page)['mode'] == 'armed'
    page.keyboard.up('ArrowRight')
    step(page, 20)
    assert cursor(page)['mode'] == 'armed' and cursor(page)['y'] < 3                    # letting go does not fall back to the key from before the pause
    page.keyboard.up('ArrowDown')
    page.keyboard.down('ArrowDown')
    step(page, 20)
    assert cursor(page)['mode'] == 'drawing'                                            # a fresh press is fine
    page.keyboard.up('ArrowDown')


def test_losing_the_window_or_pressing_cmd_lets_go_of_the_keys(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    claim_left_half(page)
    put_cursor(page, 30, 36)
    page.keyboard.down('ArrowDown')
    step(page, 20)
    page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Meta', metaKey: true, bubbles: true }))")     # macOS sends no key-ups while Cmd is down
    step(page, 20)
    assert cursor(page)['y'] == pytest.approx(41, abs=1e-6)                             # stopped where it was: the key was forgotten
    page.keyboard.up('ArrowDown')
    page.keyboard.down('ArrowUp')
    step(page, 20)
    assert cursor(page)['y'] == pytest.approx(36, abs=1e-6)
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    assert cursor(page)['phase'] == 'paused' and cursor(page)['active'] is False        # the window went away: paused, and the key is forgotten
    page.keyboard.up('ArrowUp')


def test_a_new_level_puts_the_cursor_back_at_the_middle_of_the_top_edge(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    claim_left_half(page)
    put_cursor(page, 30, 36)
    page.keyboard.down('ArrowDown'); step(page, 20); page.keyboard.up('ArrowDown')
    page.evaluate('__pp.game.startLevel(2); __pp.setPatrols([{ x: 110, y: 64 }]); __pp.freeze(true)')
    got = cursor(page)
    assert got['active'] is False and (got['x'], got['y']) == (60, 1) and got['down'] is False


# ---- keys that belong to the page ---------------------------------------------------------------------------------------
SEND = """([where, init]) => { const target = where === 'body' ? document.body : document.querySelector(where);
  const event = new KeyboardEvent('keydown', Object.assign({ bubbles: true, cancelable: true }, init)); target.dispatchEvent(event);
  return { prevented: event.defaultPrevented, active: __pp.game.pilot.active }; }"""


def send(page, where, **init):
    got = page.evaluate(SEND, [where, init])
    page.evaluate('__pp.game.pilot.stop()')                                             # (a synthetic press has no key-up)
    return got


def test_arrow_keys_are_taken_only_when_nothing_else_needs_them(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    assert send(page, 'body', key='ArrowDown') == {'prevented': True, 'active': True}                 # nothing focused: the board's
    assert send(page, '#gameCanvas', key='ArrowDown') == {'prevented': True, 'active': True}         # the board focused: the board's
    assert send(page, '#gameCanvas', key='w') == {'prevented': True, 'active': True}
    assert send(page, '#soundButton', key='ArrowDown') == {'prevented': False, 'active': False}      # a control being used keeps its keys
    assert send(page, '#pauseButton', key='d') == {'prevented': False, 'active': False}
    for chord in ({'ctrlKey': True}, {'metaKey': True}, {'altKey': True}):
        assert send(page, 'body', key='ArrowDown', **chord) == {'prevented': False, 'active': False}   # browser and system chords are not ours
    assert send(page, 'body', key='x') == {'prevented': False, 'active': False}                       # and other keys are not affected at all
    assert send(page, 'body', key='Backspace')['prevented'] is True                                   # with no route to cancel yet, the page still must not go back
    assert send(page, '#soundButton', key='Backspace')['prevented'] is False
    assert send(page, 'body', key='ArrowDown', repeat=True) == {'prevented': False, 'active': False}  # a repeat cannot start anything
    page.evaluate('__pp.game.pause("manual")')
    assert send(page, 'body', key='ArrowDown') == {'prevented': False, 'active': False}               # not while paused
    assert send(page, 'body', key='Backspace')['prevented'] is False


def test_a_repeat_of_a_key_the_cursor_is_using_is_kept_from_scrolling_the_page(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.evaluate("document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }))")
    got = page.evaluate(SEND, ['body', {'key': 'ArrowDown', 'repeat': True}])
    assert got == {'prevented': True, 'active': True}
    page.evaluate('__pp.game.pilot.stop()')


def test_arrow_keys_do_nothing_behind_an_open_dialog(open_page):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.evaluate('__pp.ui.openHelp()')
    assert page.evaluate('__pp.ui.isModalOpen()') is True and cursor(page)['phase'] == 'paused'
    page.keyboard.down('ArrowDown')
    assert cursor(page)['active'] is False
    page.keyboard.up('ArrowDown')
    page.keyboard.press('Escape')
    assert page.evaluate('__pp.ui.isModalOpen()') is False


# ---- the board is a keyboard target ---------------------------------------------------------------------------------------
def test_the_board_can_be_reached_with_tab_and_shows_a_focus_ring(open_page, engine):
    page = open_page(viewport=DESKTOP)
    play(page)
    page.evaluate('document.getElementById("pauseButton").focus()')                     # the last control before the board
    page.keyboard.press('Tab' if engine != 'webkit' else 'Alt+Tab')                     # (Safari's Tab skips buttons unless Option is held)
    assert page.evaluate('document.activeElement.id') == 'gameCanvas'
    assert page.evaluate('__pp.state().phase') == 'playing'
    ring = page.evaluate("(() => { const s = getComputedStyle(document.getElementById('gameCanvas')); return [s.outlineStyle, parseFloat(s.outlineWidth), parseFloat(s.outlineOffset)]; })()")
    assert ring[0] != 'none' and ring[1] >= 2 and ring[2] < 0                            # a visible ring, drawn inside the board's edge
    page.keyboard.down('ArrowRight')
    step(page, 10)
    assert cursor(page)['active'] is True and cursor(page)['x'] > 60
    page.keyboard.up('ArrowRight')


def test_a_keyboard_player_starting_a_run_is_left_with_the_board_focused_but_a_mouse_player_is_not(open_page):
    page = open_page(viewport=DESKTOP)
    page.wait_for_function('__pp.state().frames > 3')
    assert page.evaluate('document.activeElement.id') == 'startButton'                  # the title focuses Start for a keyboard
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('document.activeElement.id') == 'gameCanvas'
    page = open_page(viewport=DESKTOP)
    page.wait_for_function('__pp.state().frames > 3')
    page.click('#startButton')                                                          # a real mouse click
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('document.activeElement.id') != 'gameCanvas'


def test_the_board_keeps_or_gets_the_focus_through_a_keyboard_pause_and_resume_but_a_mouse_click_after_keys_takes_it_away(open_page):
    page = open_page(viewport=DESKTOP)
    page.wait_for_function('__pp.state().frames > 3')
    page.keyboard.press('Space')                                                        # Space starts it, as Enter does
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('document.activeElement.id') == 'gameCanvas'
    page.keyboard.press('p')
    assert page.evaluate('__pp.state().phase') == 'paused' and page.evaluate('document.activeElement.id') == 'resumeButton'
    page.keyboard.press('p')                                                            # resumed from the keyboard: the board again
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('document.activeElement.id') == 'gameCanvas'
    page.keyboard.press('Escape')                                                       # paused again, and this time the mouse resumes it
    page.click('#resumeButton')
    assert page.evaluate('__pp.state().phase') == 'playing'
    frame(page)
    assert page.evaluate('document.activeElement.id') != 'gameCanvas'                   # keys were used before, but the last input was the mouse's


# ---- what it looks like ---------------------------------------------------------------------------------------------------
PIXEL = """([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
  const s = document.createElement('canvas'); s.width = s.height = 1; const g = s.getContext('2d', { willReadFrequently: true });
  g.drawImage(c, Math.round((x - r.left) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1); return Array.from(g.getImageData(0, 0, 1, 1).data); }"""


@pytest.mark.parametrize('label,viewport,touch', [('landscape', DESKTOP, False), ('portrait', PORTRAIT, True)])
def test_the_cursor_ring_appears_with_the_first_key_and_follows_the_route(open_page, label, viewport, touch):
    page = open_page(viewport=viewport, has_touch=touch, is_mobile=touch)
    play(page)
    scale = page.evaluate('__pp.view.fit.scale')
    ring = 13 / scale                                                                   # the fine-pointer ring is 13 css px

    def on_ring(x, y):                                                                  # a point on the ring, left of the cursor on the screen (inside the canvas on either board)
        page.evaluate('__pp.renderer.invalidate()'); frame(page)
        c = page.evaluate(f'__pp.toClient({x}, {y})')
        return page.evaluate(PIXEL, [c['x'] - 13, c['y']])

    along = 'ArrowRight' if label == 'landscape' else 'ArrowDown'                     # along the top edge: it runs across the screen, or down it once the board is turned
    before = on_ring(60, 1)
    page.keyboard.down(along)
    step(page, 1)
    after_arm = on_ring(page.evaluate('__pp.game.pilot.x'), 1)
    step(page, 40)
    page.keyboard.up(along)
    assert sum(after_arm[:3]) > sum(before[:3]) + 60, (before, after_arm)             # a light ring where there was only the dark frame
    at = cursor(page)
    assert at['x'] > 60 and at['mode'] == 'armed'


def test_the_focus_ring_and_a_live_route_look_right(open_page):
    page = open_page(viewport=DESKTOP)
    play(page, patrols='[{ x: 110, y: 64 }]')
    page.evaluate('document.getElementById("gameCanvas").focus()')
    page.keyboard.down('ArrowDown')
    step(page, 70)
    page.keyboard.up('ArrowDown')
    page.evaluate('__pp.renderer.invalidate()'); frame(page)
    import pathlib
    out = pathlib.Path(__file__).resolve().parents[1] / 'test-results' / 'layout'
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / 'keyboard-drawing.png'))
    assert page.evaluate('document.activeElement.id') == 'gameCanvas'
    assert page.evaluate('getComputedStyle(document.getElementById("gameCanvas")).outlineStyle') != 'none'


# ---- the tutorial by keyboard ---------------------------------------------------------------------------------------------------
def coach(page):
    return page.locator('#toast').text_content().strip()


def test_the_tutorial_can_be_finished_with_the_keyboard_alone(open_page):
    page = open_page(viewport=DESKTOP, tutorial=True)
    page.wait_for_function('__pp.state().frames > 3')
    page.keyboard.press('Enter')                                                        # Start, from the keyboard
    assert page.evaluate('__pp.game.run.mode') == 'tutorial'
    page.evaluate('__pp.setPatrols([{ x: 110, y: 60 }]); __pp.freeze(true)')
    assert page.evaluate('__pp.game.pilot.x') == 34                                      # the cursor starts where the ghost finger does
    assert coach(page) == 'Start on the glowing edge'
    page.keyboard.down('ArrowDown')
    step(page, 2)
    assert coach(page) == 'Keep going into the field' and page.evaluate('__pp.game.tutorial.step') == 2
    step(page, 60)
    assert coach(page) == 'Now finish on any edge' and page.evaluate('__pp.game.tutorial.step') == 3
    step(page, 300)
    page.keyboard.up('ArrowDown')
    assert page.evaluate('__pp.state().phase') == 'clear' and page.locator('#clearOverlay').is_visible()      # the finish screen


def test_in_the_tutorial_a_hit_keeps_its_message_until_the_next_key_and_backspace_has_its_own(open_page):
    page = open_page(viewport=DESKTOP, tutorial=True)
    page.wait_for_function('__pp.state().frames > 3')
    page.keyboard.press('Enter')
    page.evaluate('__pp.setPatrols([{ x: 34, y: 30 }]); __pp.freeze(true)')             # parked on the route's line
    page.keyboard.down('ArrowDown')
    step(page, 130)
    assert coach(page) == 'A plane hit it: free here. Again' and page.evaluate('__pp.game.tutorial.step') == 1
    step(page, 60)
    assert coach(page) == 'A plane hit it: free here. Again'                            # still there: the cursor waits, and does not say "armed" by itself
    page.keyboard.up('ArrowDown')
    page.evaluate('__pp.setPatrols([{ x: 110, y: 60 }])')
    page.keyboard.down('ArrowDown')                                                     # a fresh press is the "touch"
    step(page, 2)
    assert coach(page) == 'Keep going into the field'
    step(page, 40)
    page.keyboard.up('ArrowDown')
    page.keyboard.press('Backspace')
    assert coach(page) == 'Cancelled, no harm. Try again' and page.evaluate('__pp.game.tutorial.step') == 1
    assert page.evaluate('__pp.game.run.lives') == 3                                    # the tutorial cannot cost anything


# ---- a bot at the keys -----------------------------------------------------------------------------------------------------------
FUZZ = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { FIELD, ROUTE } = await import('/js/grid.js');
  const { STEP, BOARD_W, BOARD_H } = await import('/js/config.js');
  const { screenDirToBoard } = await import('/js/view.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const rngOf = (seed) => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const out = { games: 0, steps: 0, presses: 0, backspaces: 0, captures: 0, hits: 0, pauses: 0, yields: 0, saves: 0, problems: [] };
  const note = (m) => { if (out.problems.length < 6) out.problems.push(m); };
  const KEYS = [['ArrowUp', 0, -1], ['ArrowDown', 0, 1], ['ArrowLeft', -1, 0], ['ArrowRight', 1, 0], ['w', 0, -1], ['a', -1, 0], ['s', 0, 1], ['d', 1, 0]];
  for (const seed of arg.seeds) {
    const rnd = rngOf(seed * 104729 + 7);
    const game = new Game({ storage: createStorage(memoryBackend()) });
    game.enterTitle(); game.newRun({ seed: 'keys-' + seed }); game.startLevel(1 + (seed % 7) * 4);
    out.games++;
    const { route, pilot, grid } = game;
    const save = game.persist.bind(game);
    game.persist = () => { save(); const raw = game.storage.loadSnapshot(); if (raw) { out.saves++; if (validateSnapshot(raw) === null) note(`seed ${seed}: an unreadable save`); } };
    game.on('capture', () => { out.captures++; });
    game.on('route', (e) => { if (e.type === 'hit') out.hits++; });
    const down = new Set();
    let rotated = seed % 2 === 1;
    for (let i = 0; i < 3000; i++) {
      game.step(STEP); out.steps++;
      if (game.phase === 'over') { game.newRun({ seed: 'keys-' + seed + '-' + i }); game.startLevel(1 + Math.floor(rnd() * 6) * 5); down.clear(); continue; }
      if (game.phase === 'clear' && rnd() < 0.05) game.skipClear();
      const roll = rnd();
      if (roll < 0.03) { const [key, dx, dy] = KEYS[Math.floor(rnd() * KEYS.length)]; const b = screenDirToBoard(rotated, dx, dy); if (pilot.press(key, b.x, b.y, false) || true) { down.add(key); out.presses++; } }
      else if (roll < 0.05 && down.size) { const key = [...down][Math.floor(rnd() * down.size)]; down.delete(key); pilot.lift(key); }
      else if (roll < 0.058) { pilot.backspace(); out.backspaces++; }
      else if (roll < 0.061 && game.isPlaying()) { game.pause('manual'); out.pauses++; game.resume(); if (game.phase === 'countdown') game.resume(); down.clear(); }
      else if (roll < 0.064) { pilot.yield(); route.begin(2 + rnd() * 116, 1, 0); route.move(2 + rnd() * 116, 1 + rnd() * 20); route.end('lift'); out.yields++; down.clear(); pilot.releaseAll(); }
      else if (roll < 0.0655 && game.restartLevel()) { down.clear(); }
      else if (roll < 0.067) { rotated = !rotated; }
      // invariants, every step
      const g = grid;
      if (g.count(ROUTE) !== route.cells.length) note(`seed ${seed} step ${i}: ${g.count(ROUTE)} ROUTE cells, engine has ${route.cells.length}`);
      if (!(pilot.x >= 0 && pilot.x <= BOARD_W && pilot.y >= 0 && pilot.y <= BOARD_H)) note(`seed ${seed} step ${i}: the cursor left the board: ${pilot.x}, ${pilot.y}`);
      if (pilot.active && game.isPlaying() && route.mode !== 'drawing' && route.mode !== 'spent' && !g.isSolid(Math.floor(pilot.x * 2), Math.floor(pilot.y * 2))) note(`seed ${seed} step ${i}: an armed cursor is not on safe ground (${route.mode})`);
      if (pilot.active && !route.down) note(`seed ${seed} step ${i}: the cursor is out but no pointer is down on the route engine (${route.mode}, ${game.phase})`);
      if (!game.isPlaying() && (pilot.active || route.down)) note(`seed ${seed} step ${i}: a cursor or pointer survived play stopping (${game.phase})`);
      if (route.mode === 'drawing' && route.cells.length === 0) note(`seed ${seed} step ${i}: drawing with no cells`);
      if (!Number.isFinite(pilot.x + pilot.y)) note(`seed ${seed} step ${i}: a cursor that is not finite`);
    }
  }
  return out;
"""


def test_a_bot_at_the_keys_breaks_no_invariant(open_page):
    page = open_page()
    got = page.evaluate("async (arg) => {" + FUZZ + "}", {'seeds': list(range(1, 15))})
    assert got['problems'] == [], got['problems']
    assert got['games'] == 14 and got['steps'] > 40000 and got['presses'] > 800
    assert got['backspaces'] > 50 and got['captures'] > 30 and got['hits'] > 5 and got['pauses'] > 5 and got['yields'] > 5
    assert got['saves'] > 30                                                            # and every save the games made was read back
