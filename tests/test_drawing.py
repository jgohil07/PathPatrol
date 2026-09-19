"""Drawing through real input: the mouse, real touch (Chromium, over CDP so the browser's own gesture
handling is involved), synthetic pointer events (both engines) and the rotated portrait board.

Board coordinates are 120 x 72 units; page.evaluate('__pp.toClient(x, y)') turns them into the viewport
pixels to press, whatever the layout or rotation."""
import time

import pytest

RIGHT = [{'x': 100, 'y': 60}]        # a parked patrol on the right, out of the way of a cut at x = 40
LEFT_CUT_PERCENT = 33.19             # a cut at x = 40 with the patrol on the right: 77 of 232 columns


def start(page, patrols=RIGHT):
    page.click('#startButton') if page.locator('#startButton').is_visible() else None
    page.evaluate('([patrols]) => { __pp.game.newRun({ seed: "drawing" }); __pp.freeze(true); __pp.setPatrols(patrols); }', [patrols])
    assert page.evaluate('__pp.state().phase') == 'playing'


def client(page, x, y):
    return page.evaluate('([x, y]) => __pp.toClient(x, y)', [x, y])


def route(page):
    return page.evaluate('__pp.route()')


def state(page):
    return page.evaluate('__pp.state()')


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def pixel(page, x, y):
    """The RGB of the game canvas under the viewport point (x, y)."""
    return page.evaluate("""([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
      const scratch = document.createElement('canvas'); scratch.width = scratch.height = 1;
      const s = scratch.getContext('2d', { willReadFrequently: true });       // reading the game canvas directly makes Chrome warn
      s.drawImage(c, Math.round((x - r.left) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1);
      const d = s.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; }""", [x, y])


def press(page, x, y):
    c = client(page, x, y)
    page.mouse.move(c['x'], c['y'])
    page.mouse.down()


def move(page, x, y, steps=1):
    c = client(page, x, y)
    page.mouse.move(c['x'], c['y'], steps=steps)


# ---- the mouse ----------------------------------------------------------------------------------
def test_d1_the_route_is_under_the_pointer_the_moment_it_moves(open_page):
    """The prototype drew a preview line, waited for release, then grew the route at 39 cells/s."""
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    tip = client(page, 40, 30)
    before = pixel(page, tip['x'], tip['y'])
    press(page, 40, 1)
    assert route(page)['mode'] == 'armed' and route(page)['cells'] == 0
    counts = []
    for y in (6, 12, 20, 30):
        move(page, 40, y)
        r = route(page)                                              # read straight after the move, before any frame
        counts.append(r['cells'])
        assert r['gridRouteCells'] == r['cells'] > 0
        assert r['tip']['y'] == pytest.approx(y, abs=0.3)
    assert counts == sorted(counts) and counts[-1] == pytest.approx(57, abs=2) and len(set(counts)) == len(counts)
    frame(page)                                                      # one frame later the picture agrees
    assert pixel(page, tip['x'], tip['y']) != before
    page.mouse.up()
    assert route(page)['cells'] == 0 and route(page)['gridRouteCells'] == 0


def test_a_single_huge_swipe_is_captured_completely(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 40, 1)
    move(page, 40, 71)                                               # one pointer event from edge to edge
    page.mouse.up()
    st = state(page)
    assert st['phase'] == 'playing' and st['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.0)
    assert route(page)['gridRouteCells'] == 0 and route(page)['polylines'] == 1
    assert page.evaluate('__pp.cell(160, 70)') == 0 and page.evaluate('__pp.cell(40, 70)') == 1     # right open, left claimed: no leak


def test_a_freehand_route_of_any_shape_captures_the_side_without_a_patrol(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    curve = [(30, 1), (38, 14), (26, 26), (42, 40), (28, 55), (36, 71)]
    press(page, *curve[0])
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        for t in range(1, 9):
            move(page, x0 + (x1 - x0) * t / 8, y0 + (y1 - y0) * t / 8)
        assert route(page)['gridRouteCells'] == route(page)['cells']
    page.mouse.up()
    st = state(page)
    assert 20 < st['cleared'] < 40 and st['phase'] == 'playing' and st['lives'] == 3
    assert route(page)['mode'] == 'idle' and route(page)['gridRouteCells'] == 0
    assert page.evaluate('__pp.cell(160, 70)') == 0                  # the patrol's side is intact


def test_lifting_mid_field_cancels_without_costing_a_life(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 40, 1)
    move(page, 40, 30, steps=6)
    assert route(page)['cells'] > 40
    page.mouse.up()
    assert route(page)['cells'] == 0 and route(page)['gridRouteCells'] == 0 and route(page)['mode'] == 'idle'
    st = state(page)
    assert st['lives'] == 3 and st['cleared'] == 0 and st['phase'] == 'playing'


def test_drawing_into_a_patrol_costs_one_life_and_the_rest_of_the_drag_is_ignored(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page, [{'x': 40, 'y': 20}])
    press(page, 40, 1)
    move(page, 40, 40, steps=10)
    assert state(page)['lives'] == 2 and route(page)['mode'] == 'spent' and route(page)['gridRouteCells'] == 0
    move(page, 40, 71, steps=5)                                      # keeps dragging to the far edge: nothing happens
    st = state(page)
    assert st['lives'] == 2 and st['cleared'] == 0 and route(page)['gridRouteCells'] == 0
    assert page.locator('#toast').inner_text() == 'Route intercepted — try again'
    page.mouse.up()
    assert route(page)['mode'] == 'idle'
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }])')
    press(page, 40, 1)                                               # the next attempt is fresh
    move(page, 40, 71, steps=10)
    page.mouse.up()
    assert state(page)['cleared'] > 25


def test_only_the_primary_mouse_button_draws(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    c = client(page, 40, 1)
    page.mouse.move(c['x'], c['y'])
    page.mouse.down(button='right')
    assert route(page)['down'] is False
    page.mouse.up(button='right')
    page.mouse.down(button='middle')
    assert route(page)['down'] is False
    page.mouse.up(button='middle')


def test_blur_mid_route_pauses_and_erases_the_route(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 40, 1)
    move(page, 40, 30, steps=4)
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    st = state(page)
    assert st['phase'] == 'paused' and route(page)['gridRouteCells'] == 0 and route(page)['mode'] == 'idle'
    move(page, 40, 60)                                               # the finger is still down and moving: no phantom route
    assert route(page)['gridRouteCells'] == 0
    page.mouse.up()
    page.click('#resumeButton')
    page.wait_for_function("__pp.state().phase === 'playing'", timeout=5000)
    press(page, 40, 1)
    move(page, 40, 71, steps=8)
    page.mouse.up()
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.0)


def test_the_layout_is_held_still_while_a_pointer_is_down(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 40, 1)
    move(page, 40, 20, steps=3)
    held = state(page)['fit']                                        # the layout the route is being drawn in
    page.set_viewport_size({'width': 900, 'height': 700})
    page.wait_for_timeout(400)
    assert state(page)['fit'] == held                                # a resize cannot make the route jump
    page.mouse.up()
    page.wait_for_function(f"__pp.state().fit.cssW !== {held['cssW']}")


def test_starting_in_the_middle_draws_nothing_and_says_why_but_starting_near_an_edge_snaps(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 60, 36)                                              # far from any edge
    assert route(page)['mode'] == 'idle'
    move(page, 60, 50)
    assert route(page)['gridRouteCells'] == 0
    assert page.locator('#toast').inner_text() == 'Start on an edge or on claimed ground'
    page.mouse.up()
    page.evaluate('__pp.ui._lastHint = -Infinity')
    scale = state(page)['fit']['cssW'] / 120
    press(page, 40, 2 + 7 / scale)                                   # 7 CSS px inside the field: within the mouse's 10 px snap
    assert route(page)['mode'] == 'drawing' and route(page)['cells'] > 0     # snapped to the edge, joined to the pointer by a segment
    move(page, 40, 30, steps=4)
    assert route(page)['mode'] == 'drawing' and route(page)['cells'] > 40
    page.mouse.up()
    press(page, 40, 2 + 25 / scale)                                  # 25 px away: too far
    assert route(page)['mode'] == 'idle'
    page.mouse.up()


def test_a_long_route_is_drawn_without_slowing_the_page(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    press(page, 30, 1)
    t0 = time.time()
    for i in range(200):                                             # a scribble of 200 events
        move(page, 30 + (i % 20), 5 + i * 0.3)
    elapsed = time.time() - t0
    assert route(page)['mode'] in ('drawing', 'armed')
    assert route(page)['gridRouteCells'] == route(page)['cells']
    assert elapsed < 6                                               # mostly Playwright's own round trips
    page.mouse.up()


# ---- the rotated (portrait) board ----------------------------------------------------------------
def test_drawing_works_on_the_rotated_board(open_page):
    """A stage taller than wide turns the board 90 degrees; the pointer must still land where it looks."""
    page = open_page(viewport={'width': 412, 'height': 1100})
    page.wait_for_function('__pp.state().fit.rotated === true')
    start(page)
    top, bottom = client(page, 40, 1), client(page, 40, 71)
    assert top['x'] > bottom['x'] and abs(top['y'] - bottom['y']) < 2      # board top edge is the screen's right side
    tip = client(page, 40, 30)
    before = pixel(page, tip['x'], tip['y'])
    press(page, 40, 1)
    move(page, 40, 30, steps=6)
    r = route(page)
    assert r['mode'] == 'drawing' and r['tip']['x'] == pytest.approx(40, abs=0.6) and r['tip']['y'] == pytest.approx(30, abs=0.6)
    frame(page)
    assert pixel(page, tip['x'], tip['y']) != before
    move(page, 40, 71, steps=8)
    page.mouse.up()
    st = state(page)
    assert st['fit']['rotated'] and st['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.2) and st['phase'] == 'playing'
    assert page.evaluate('__pp.cell(160, 70)') == 0 and page.evaluate('__pp.cell(40, 70)') == 1


# ---- real touch (Chromium, over CDP) --------------------------------------------------------------
class Touch:
    """Input.dispatchTouchEvent. touchEnd with a list releases exactly those fingers; touchEnd [] releases all."""
    def __init__(self, page):
        self.page = page
        self.cdp = page.context.new_cdp_session(page)

    def send(self, kind, fingers):
        self.cdp.send('Input.dispatchTouchEvent', {'type': kind, 'touchPoints': fingers})

    def at(self, finger, x, y):
        c = client(self.page, x, y)
        return {'id': finger, 'x': c['x'], 'y': c['y']}


WATCH = """() => { window.__events = []; const c = document.getElementById('gameCanvas');
  for (const t of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel']) c.addEventListener(t, (e) => __events.push(t + ':' + e.pointerId), true); }"""


@pytest.fixture
def touch_page(open_page, engine):
    if engine != 'chromium':
        pytest.skip('real touch needs CDP, which only Chromium has; the pointer handlers are covered by the synthetic-event tests below')
    page = open_page(device='Pixel 7')
    page.evaluate(WATCH)
    start(page)
    return page


def test_d2_a_touch_drag_is_not_taken_over_by_the_browser(touch_page):
    """With the prototype's touch-action: manipulation the browser cancelled every drag."""
    page = touch_page
    t = Touch(page)
    t.send('touchStart', [t.at(1, 40, 1)])
    for y in list(range(4, 70, 4)) + [71]:                             # the last move lands on the bottom frame
        t.send('touchMove', [t.at(1, 40, y)])
        time.sleep(0.008)
    t.send('touchEnd', [])
    events = page.evaluate('__events')
    kinds = [e.split(':')[0] for e in events]
    assert kinds.count('pointercancel') == 0 and kinds.count('pointerup') == 1 and kinds.count('pointermove') >= 10
    st = state(page)
    assert st['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.5) and st['phase'] == 'playing'
    assert page.evaluate('[scrollY, visualViewport.scale]') == [0, 1]


def test_d3_a_second_finger_does_not_take_over_the_route(touch_page):
    page = touch_page
    t = Touch(page)
    f1 = lambda y: t.at(1, 40, y)                                    # noqa: E731
    f2 = lambda: t.at(2, 95, 50)                                     # noqa: E731
    t.send('touchStart', [f1(1)])
    t.send('touchMove', [f1(15)])
    t.send('touchStart', [f1(15), f2()])                             # a second finger lands elsewhere
    assert route(page)['mode'] == 'drawing' and route(page)['tip']['x'] == pytest.approx(40, abs=1)
    t.send('touchMove', [f1(40), f2()])
    t.send('touchMove', [f1(71), t.at(2, 96, 30)])                   # the second finger wanders too
    t.send('touchEnd', [f1(71)])                                     # first finger lifts on the bottom edge: the route closes
    st = state(page)
    assert st['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.5) and st['lives'] == 3
    t.send('touchEnd', [])
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.5)      # the second finger lifting changes nothing
    events = [e.split(':')[0] for e in page.evaluate('__events')]
    assert events.count('pointercancel') == 0


def test_lifting_the_first_finger_first_does_not_promote_the_second(touch_page):
    page = touch_page
    t = Touch(page)
    t.send('touchStart', [t.at(1, 40, 1)])
    t.send('touchMove', [t.at(1, 40, 20)])
    t.send('touchStart', [t.at(1, 40, 20), t.at(2, 95, 50)])
    t.send('touchEnd', [t.at(1, 40, 20)])                            # finger 1 lifts mid-field: the route is cancelled
    assert route(page)['gridRouteCells'] == 0 and state(page)['lives'] == 3
    t.send('touchMove', [t.at(2, 95, 40)])                           # finger 2 is not primary: it never starts a route
    assert route(page)['mode'] == 'idle' and route(page)['gridRouteCells'] == 0
    t.send('touchEnd', [])


def test_a_pinch_on_the_board_does_not_zoom_the_page(touch_page):
    page = touch_page
    t = Touch(page)
    t.send('touchStart', [t.at(1, 50, 30)])
    t.send('touchStart', [t.at(1, 50, 30), t.at(2, 70, 30)])
    for spread in range(0, 40, 4):
        t.send('touchMove', [t.at(1, 50 - spread, 30), t.at(2, 70 + spread, 30)])
    t.send('touchEnd', [])
    assert page.evaluate('visualViewport.scale') == 1
    kinds = [e.split(':')[0] for e in page.evaluate('__events')]
    assert kinds.count('pointercancel') == 0


def test_touch_snaps_within_a_fingertip_and_hints_beyond_it(touch_page):
    page = touch_page
    t = Touch(page)
    rect = page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return { left: r.left, top: r.top, width: r.width }; })()")
    x = rect['left'] + rect['width'] * 40 / 120
    scale = rect['width'] / 120
    inner_edge = rect['top'] + 2 * scale                              # where the frame ends and open field begins
    t.send('touchStart', [{'id': 1, 'x': x, 'y': inner_edge + 16}])   # 16 CSS px inside the field: within the 22 px snap
    assert route(page)['mode'] == 'drawing' and route(page)['cells'] > 0
    t.send('touchEnd', [])
    assert route(page)['gridRouteCells'] == 0
    page.evaluate('__pp.ui._lastHint = -Infinity')
    t.send('touchStart', [{'id': 2, 'x': x, 'y': inner_edge + 45}])  # 45 px in: too far
    assert route(page)['mode'] == 'idle'
    assert page.locator('#toast').inner_text() == 'Start on an edge or on claimed ground'
    t.send('touchEnd', [])


def test_a_touch_that_lifts_mid_field_cancels_the_route(touch_page):
    page = touch_page
    t = Touch(page)
    t.send('touchStart', [t.at(1, 40, 1)])
    t.send('touchMove', [t.at(1, 40, 25)])
    assert route(page)['cells'] > 30
    t.send('touchEnd', [])
    assert route(page)['gridRouteCells'] == 0 and state(page)['lives'] == 3 and state(page)['cleared'] == 0


# ---- synthetic pointer events (both engines): exercises our handlers, not the browser's gesture code ----
POINTER = """([type, x, y, id, kind, primary]) => { const c = document.getElementById('gameCanvas');
  c.dispatchEvent(new PointerEvent(type, { pointerId: id, pointerType: kind, isPrimary: primary, clientX: x, clientY: y, bubbles: true, cancelable: true, button: 0, buttons: type === 'pointerup' ? 0 : 1 })); }"""


def fire(page, type_, x, y, id_=7, kind='touch', primary=True):
    c = client(page, x, y)
    page.evaluate(POINTER, [type_, c['x'], c['y'], id_, kind, primary])


def test_synthetic_touch_drag_draws_and_closes(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    fire(page, 'pointerdown', 40, 1)
    for y in range(6, 72, 6):
        fire(page, 'pointermove', 40, y)
        assert route(page)['gridRouteCells'] == route(page)['cells']
    fire(page, 'pointerup', 40, 71)
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.2) and route(page)['down'] is False
    assert page.evaluate('[__pp.game.route.coarse]') == [True]


def test_synthetic_extra_pointers_are_ignored_whatever_they_claim(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    fire(page, 'pointerdown', 40, 1, id_=7)
    fire(page, 'pointermove', 40, 20, id_=7)
    fire(page, 'pointerdown', 90, 50, id_=8, primary=False)          # a second finger
    fire(page, 'pointerdown', 90, 50, id_=9, primary=True)           # even one that claims to be primary
    fire(page, 'pointermove', 95, 55, id_=8)
    fire(page, 'pointermove', 95, 30, id_=9)
    r = route(page)
    assert r['mode'] == 'drawing' and r['tip']['x'] == pytest.approx(40, abs=1) and r['tip']['y'] == pytest.approx(20, abs=1)
    fire(page, 'pointerup', 95, 30, id_=8)                           # the other fingers lifting does not end the route
    fire(page, 'pointerup', 95, 30, id_=9)
    assert route(page)['mode'] == 'drawing'
    fire(page, 'pointermove', 40, 71, id_=7)
    fire(page, 'pointerup', 40, 71, id_=7)
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.2)


def test_synthetic_pointercancel_and_lost_capture_erase_the_route_for_free(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    for ending in ('pointercancel', 'lostpointercapture'):
        fire(page, 'pointerdown', 40, 1)
        fire(page, 'pointermove', 40, 30)
        assert route(page)['cells'] > 40
        fire(page, ending, 40, 30)
        assert route(page)['gridRouteCells'] == 0 and route(page)['mode'] == 'idle' and route(page)['down'] is False
        assert state(page)['lives'] == 3 and state(page)['cleared'] == 0
        fire(page, 'pointermove', 40, 50)                            # the pointer is gone: further events do nothing
        assert route(page)['gridRouteCells'] == 0


def test_a_pause_lets_go_of_the_pointer_so_the_next_touch_starts_fresh(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    start(page)
    fire(page, 'pointerdown', 40, 1)
    fire(page, 'pointermove', 40, 20)
    assert page.evaluate('__pp.view.frozen') is True
    page.keyboard.press('p')
    assert state(page)['phase'] == 'paused' and route(page)['gridRouteCells'] == 0
    assert page.evaluate('__pp.view.frozen') is False                # the pause let go, so the layout is free to change again
    page.keyboard.press('p')
    fire(page, 'pointermove', 40, 1)                                 # the same finger slides onto the edge...
    fire(page, 'pointermove', 40, 30)                                # ...and into the field: without a new touch it draws nothing
    assert route(page)['gridRouteCells'] == 0 and route(page)['mode'] == 'idle'
    fire(page, 'pointerup', 40, 30)
    fire(page, 'pointerdown', 40, 1)                                 # a new touch works at once
    fire(page, 'pointermove', 40, 71)
    fire(page, 'pointerup', 40, 71)
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.2)


def test_drawing_works_in_the_drive_theme_too(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.keyboard.press('t')                                          # Flight -> Drive, the way a player switches on a keyboard
    assert page.evaluate('__pp.renderer.theme') == 'drive'
    start(page)
    press(page, 40, 1)
    move(page, 40, 30, steps=4)
    frame(page)
    tip = client(page, 40, 20)
    assert route(page)['mode'] == 'drawing' and pixel(page, tip['x'], tip['y']) != [0, 0, 0]
    move(page, 40, 71, steps=6)
    page.mouse.up()
    assert state(page)['cleared'] == pytest.approx(LEFT_CUT_PERCENT, abs=1.2)
