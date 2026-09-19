"""Visual effects: particles, popups, rings, the route glow and the screen shake. They are decoration, so the tests care
about the rules that matter: they appear for the right events, they end by themselves, they are capped, they are quiet
under reduced motion, popups stay upright and on the canvas on the rotated board, and shaking never moves the page."""
import pytest

DESKTOP = {'width': 1280, 'height': 800}


def stats(page):
    return page.evaluate('__pp.fx.stats()')


def frame(page, n=2):
    page.evaluate(f'new Promise((resolve) => {{ let n = {n}; const go = () => (--n ? requestAnimationFrame(go) : resolve()); requestAnimationFrame(go); }})')


def new_run(page, patrols='[{ x: 100, y: 60 }]'):
    page.evaluate(f'__pp.game.newRun({{ seed: "fx" }}); __pp.setPatrols({patrols})')


def draw_across(page, x=40):
    """A real route from the top edge to the bottom one, so the capture carries its polyline."""
    page.evaluate(f'(() => {{ const r = __pp.game.route; r.begin({x}, 1); r.move({x}, 30); r.move({x}, 71); }})()')


def wait_until_quiet(page, timeout=3000):
    page.wait_for_function('!__pp.fx.active', timeout=timeout)


# ---- what appears --------------------------------------------------------------------------------------------
def test_a_capture_bursts_along_its_route_glows_and_pops_up_its_points_then_fades_away(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    assert stats(page) == {'particles': 0, 'popups': 0, 'rings': 0, 'glows': 0, 'shaking': False}
    draw_across(page)                                                               # 77 columns claimed: worth 3,927
    st = stats(page)
    assert st['particles'] >= 10 and st['glows'] == 1 and st['popups'] == 1 and st['rings'] == 0
    assert page.evaluate('__pp.fx.popups[0].text') == '+3,927'
    assert page.evaluate('__pp.fx.active') is True
    wait_until_quiet(page)                                                          # they end by themselves, within about a second
    assert stats(page) == {'particles': 0, 'popups': 0, 'rings': 0, 'glows': 0, 'shaking': False}

    page.evaluate('__pp.setPatrols([{ x: 118, y: 60 }])')
    draw_across(page, 80)                                                           # the second capture, at combo x1.25: the popup says so
    assert page.evaluate('__pp.fx.popups[0].text').endswith('x1.25')


def test_a_hit_bursts_rings_and_shakes_briefly_without_moving_the_page(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page, '[{ x: 40, y: 20 }]')
    before = page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
    page.evaluate('__pp.freeze(true); __pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')          # straight into the patrol
    st = stats(page)
    assert st['particles'] == 28 and st['rings'] == 1 and st['shaking'] is True and st['popups'] == 0
    offset = page.evaluate('__pp.fx.shakeOffset(performance.now() + 40, 1)')          # 40 ms into it
    assert abs(offset['x']) + abs(offset['y']) > 0.5                                # the board really is nudged...
    after = page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
    assert after == before                                                          # ...but only what is drawn: the page itself never moves
    quiet = page.evaluate('__pp.fx.shakeOffset(performance.now() + 400, 1)')
    assert quiet == {'x': 0, 'y': 0}                                                # and it is over well inside half a second
    wait_until_quiet(page)


def test_a_close_call_rings_the_patrol_and_says_so_an_extra_life_and_a_clear_have_their_own(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page, '[{ x: 43, y: 36 }]')
    page.evaluate('__pp.freeze(true); const r = __pp.game.route; r.begin(40, 1); r.move(40, 36); __pp.step(6)')
    assert stats(page)['rings'] == 1 and page.evaluate('__pp.fx.popups.map((p) => p.text)') == ['CLOSE']
    assert page.evaluate('__pp.fx.rings[0].tint') == 'amber'
    page.evaluate('__pp.game.route.end("lift")')
    new_run(page)
    page.evaluate('__pp.game.emit("extraLife", { lives: 4 })')
    assert page.evaluate('__pp.fx.popups.map((p) => p.text)') == ['+1 LIFE']
    new_run(page, '[]')
    page.evaluate('__pp.forceWin()')
    assert stats(page)['particles'] >= 80                                           # a spread of confetti across the board


def test_a_new_level_wipes_whatever_is_left(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    draw_across(page)
    assert stats(page)['popups'] == 1
    page.evaluate('__pp.game.startLevel(2)')
    assert stats(page) == {'particles': 0, 'popups': 0, 'rings': 0, 'glows': 0, 'shaking': False}


def test_the_tutorials_practice_captures_show_a_burst_but_no_points(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.startTutorial(); __pp.game.route.begin(34, 1); __pp.game.route.move(34, 30); __pp.game.route.move(34, 71)')
    assert page.evaluate('__pp.game.tutorial.active') is False and page.evaluate('__pp.game.phase') == 'clear'
    st = stats(page)
    assert st['particles'] > 0 and st['glows'] == 1 and st['popups'] == 0


# ---- limits ----------------------------------------------------------------------------------------------------
def test_a_flood_of_events_cannot_grow_the_pools_past_their_caps(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    page.evaluate("""() => { for (let i = 0; i < 400; i++) {
      __pp.game.emit('capture', { percent: 50, gained: 30, points: 100 + i, combo: 1, nextCombo: 1, closeCalls: 0, route: [10, 1, 10, 30, 12, 71] });
      __pp.game.emit('route', { type: 'hit' });
      __pp.game.emit('route', { type: 'closecall', patrol: 0 }); } }""")
    st = stats(page)
    assert st['particles'] <= 240 and st['popups'] <= 8 and st['glows'] <= 3 and st['rings'] <= 6
    assert st['particles'] == 240 and st['popups'] == 8 and st['rings'] == 6         # and the caps were really reached


def test_effects_finish_on_a_paused_board_and_then_drawing_stops(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    draw_across(page)
    page.evaluate('__pp.game.pause("manual")')
    a = page.evaluate('__pp.state().frames')
    page.wait_for_timeout(300)
    assert page.evaluate('__pp.state().frames') - a >= 5                            # still animating the last effects on the paused board...
    wait_until_quiet(page)
    page.wait_for_timeout(100)
    b = page.evaluate('__pp.state().frames')
    page.wait_for_timeout(500)
    assert page.evaluate('__pp.state().frames') - b <= 1                            # ...and once they are gone the idle screen costs nothing again


# ---- reduced motion ----------------------------------------------------------------------------------------------
def test_reduced_motion_removes_movement_but_keeps_the_points_and_tones_the_flash_down(open_page):
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    new_run(page, '[{ x: 43, y: 36 }]')
    page.evaluate('__pp.freeze(true)')
    draw_across(page)
    st = stats(page)
    assert st['particles'] == 0 and st['glows'] == 0 and st['rings'] == 0 and st['shaking'] is False
    assert st['popups'] == 1 and page.evaluate('__pp.fx.popups[0].ms') == 900        # the points are still shown, briefly
    ys = []
    for _ in range(3):
        frame(page, 5)
        ys.append(page.evaluate('__pp.fx.shown[0].y'))
    assert len(set(ys)) == 1                                                        # held still: no float
    new_run(page, '[{ x: 40, y: 20 }]')
    page.evaluate('__pp.freeze(true); __pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')
    frame(page)
    assert 0 < page.evaluate('__pp.renderer.flashAlpha') <= 0.12                    # a faint tint, not a flash
    st = stats(page)
    assert st['particles'] == 0 and st['rings'] == 0 and st['shaking'] is False

    page.click('#settingsButton')                                                   # "Full" overrides the system preference
    page.click('button[data-motion="full"]')
    page.keyboard.press('Escape')
    new_run(page, '[{ x: 40, y: 20 }]')
    page.evaluate('__pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')
    assert stats(page)['particles'] == 28 and stats(page)['shaking'] is True


def test_switching_to_reduced_motion_clears_any_effects_in_flight(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    page.evaluate("__pp.fx.burst(60, 36, 50, 'aqua', { life: 30 })")                # long-lived, so only an explicit clear can remove them
    page.evaluate("__pp.fx.ring(60, 36, 'aqua', { ms: 30000 }); __pp.fx.glow([10, 1, 10, 71]); __pp.fx.popup('+1', 60, 36)")
    assert stats(page)['particles'] == 50 and stats(page)['rings'] == 1
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    st = stats(page)
    assert st['particles'] == 0 and st['rings'] == 0 and st['glows'] == 0 and st['shaking'] is False        # dropped at once, not left to run out


def test_a_popup_that_floats_up_is_stopped_at_the_top_of_the_canvas(open_page):
    page = open_page(viewport=DESKTOP)
    new_run(page)
    page.evaluate("__pp.fx.popup('+9,999', 60, 3)")                                  # 3 units down: about 26 px, less than the rise
    page.wait_for_timeout(700)                                                       # by now it has floated about 32 px
    shown = page.evaluate('__pp.fx.shown')
    assert len(shown) == 1 and shown[0]['y'] >= shown[0]['px'] - 0.5                 # held below the top edge, the whole word still visible


# ---- popups are text: upright, and on the canvas ------------------------------------------------------------------------
@pytest.mark.parametrize('kwargs', [{'viewport': DESKTOP}, {'device': 'Pixel 7'}], ids=['landscape-board', 'portrait-board-rotated'])
def test_popups_stay_upright_and_inside_the_canvas_on_either_board(open_page, kwargs):
    page = open_page(**kwargs)
    page.emulate_media(reduced_motion='reduce')                                     # no particles: they are the same aqua as the text, and would be measured too
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    new_run(page, '[{ x: 20, y: 36 }]')
    page.evaluate('__pp.freeze(true)')
    page.evaluate('(() => { const r = __pp.game.route; r.begin(117, 1); r.move(117, 30); r.move(117, 71); })()')      # a capture right at the board's edge
    frame(page, 3)
    shown = page.evaluate('__pp.fx.shown')
    assert len(shown) == 1 and shown[0]['text'].startswith('+')
    canvas = page.evaluate("(() => { const c = document.getElementById('gameCanvas'); return [c.width, c.height]; })()")
    p = shown[0]
    assert p['x'] - p['half'] >= -0.5 and p['x'] + p['half'] <= canvas[0] + 0.5 and 0 <= p['y'] <= canvas[1]      # never cut off
    box = page.evaluate("""([x, y, half]) => { const c = document.getElementById('gameCanvas');
      const s = document.createElement('canvas'); const w = Math.ceil(half * 2), h = 60; s.width = w; s.height = h;
      const g = s.getContext('2d', { willReadFrequently: true }); g.drawImage(c, Math.round(x - half), Math.round(y - h / 2), w, h, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data; let x0 = w, x1 = -1, y0 = h, y1 = -1;
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const k = (j * w + i) * 4;
        if (d[k] < 160 && d[k + 1] > 200 && d[k + 2] > 170) { x0 = Math.min(x0, i); x1 = Math.max(x1, i); y0 = Math.min(y0, j); y1 = Math.max(y1, j); } }
      return { w: x1 - x0 + 1, h: y1 - y0 + 1, found: x1 >= 0 }; }""", [p['x'], p['y'], p['half']])
    assert box['found'] and box['w'] > 1.8 * box['h']                                # the aqua pixels form a wide, flat word: upright, not turned with the board
