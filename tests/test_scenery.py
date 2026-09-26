"""The board's art and motion (round 2): scenery that moves with the simulation and only with it, the flood that uncovers
newly claimed ground, the sweep between levels, patrols that stand out on every palette and time of day, and a lost
route that shatters where it lay. Decoration, so the tests hold it to the rules that matter: deterministic, still when
the game is still or motion is reduced, never hiding the real state of the board once it has finished."""
import pytest

DESKTOP = {'width': 1280, 'height': 800}


def frame(page, n=2):
    page.evaluate(f'new Promise((resolve) => {{ let n = {n}; const go = () => (--n ? requestAnimationFrame(go) : resolve()); requestAnimationFrame(go); }})')


def region(page, x0, y0, x1, y1):
    """The RGB pixels of a board rectangle (board units), read from the game canvas as it is."""
    return page.evaluate("""([x0, y0, x1, y1]) => { const c = document.getElementById('gameCanvas');
      const a = __pp.view.toCanvas(x0, y0), b = __pp.view.toCanvas(x1, y1);
      const l = Math.round(Math.min(a.x, b.x)), t = Math.round(Math.min(a.y, b.y)), w = Math.max(1, Math.round(Math.abs(b.x - a.x))), h = Math.max(1, Math.round(Math.abs(b.y - a.y)));
      const s = document.createElement('canvas'); s.width = w; s.height = h; const g = s.getContext('2d', { willReadFrequently: true });
      g.drawImage(c, l, t, w, h, 0, 0, w, h); const d = g.getImageData(0, 0, w, h).data; const out = [];
      for (let i = 0; i < d.length; i += 4) out.push([d[i], d[i + 1], d[i + 2]]); return out; }""", [x0, y0, x1, y1])


def mean(pixels):
    n = len(pixels)
    return [sum(p[i] for p in pixels) / n for i in range(3)]


def still_board(page, theme='flight', level=1, patrols='[{ x: 110, y: 64 }]'):
    page.evaluate(f"__pp.game.newRun({{ seed: 'scenery' }}); __pp.game.startLevel({level}); __pp.freeze(true); __pp.ui.setTheme('{theme}'); __pp.setPatrols({patrols}); 0")
    frame(page)


def draw_across(page, x=30):
    """A real route from the top edge to the bottom one: its capture carries the polyline the flood starts from."""
    page.evaluate(f'(() => {{ const r = __pp.game.route; r.begin({x}, 1); r.move({x}, 30); r.move({x}, 71); }})()')


# ---- ambient motion runs on simulated time ---------------------------------------------------------------------------
def test_the_scenery_is_perfectly_still_while_the_game_is_and_moves_when_it_runs(open_page):
    page = open_page(viewport=DESKTOP)
    still_board(page)
    a = region(page, 20, 20, 40, 40)
    frame(page, 6)
    page.evaluate('__pp.renderer.invalidate(); 0')
    frame(page)
    assert region(page, 20, 20, 40, 40) == a                                         # frozen: not one pixel of the water moves
    age = page.evaluate('__pp.game.age')
    page.evaluate('__pp.step(240)')                                                   # two seconds of simulation
    assert page.evaluate('__pp.game.age') == pytest.approx(age + 2, abs=1e-9)
    frame(page)
    b = region(page, 20, 20, 40, 40)
    changed = sum(1 for p, q in zip(a, b) if sum(abs(u - v) for u, v in zip(p, q)) > 6)
    assert changed > len(a) * 0.05, changed                                           # ripples and cloud shadows have drifted


def test_pausing_stops_the_scenerys_clock(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    page.evaluate('__pp.game.pause(); 0')
    age = page.evaluate('__pp.game.age')
    page.wait_for_timeout(300)
    assert page.evaluate('__pp.game.age') == age


@pytest.mark.parametrize('theme', ['flight', 'drive'])
def test_claimed_ground_and_obstacles_never_change_as_the_scenery_moves(open_page, theme):
    """Ripples and cloud shadows drift over open ground only: claimed ground and the obstacles on it keep their colours
    (the prototype's snow and lit windows among them)."""
    page = open_page(viewport=DESKTOP)
    still_board(page, theme, 12)                                                      # two obstacles, both on the left half
    page.evaluate('__pp.cutLine("v", 62); 0')                                         # the patrol is at x 110: the left half is claimed (not enough to win)
    page.wait_for_function('!__pp.fx.active', timeout=3000)                            # (the capture's popup is over the board: let it go)
    frame(page)
    assert page.evaluate('__pp.state().phase') == 'playing'
    assert all(o['x'] + o['w'] < 59 for o in page.evaluate('__pp.state().obstacles'))      # the obstacles stand on the claimed half
    a = region(page, 3, 3, 59, 69)
    for _ in range(4):
        page.evaluate('__pp.step(600)')                                               # five seconds at a time: clouds move 6.5 units each time
        frame(page)
        assert page.evaluate('__pp.state().phase') == 'playing'
        assert region(page, 3, 3, 59, 69) == a


def test_reduced_motion_holds_the_scenery_still_even_as_the_game_runs(open_page):
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    still_board(page)
    a = region(page, 20, 20, 40, 40)
    page.evaluate('__pp.step(240)')
    frame(page)
    assert region(page, 20, 20, 40, 40) == a


@pytest.mark.parametrize('theme', ['flight', 'drive'])
def test_every_level_has_its_own_texture_but_the_same_level_is_always_the_same(open_page, theme):
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')                                      # no drift: only the texture itself is compared
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    still_board(page, theme, 1)
    one = region(page, 10, 10, 50, 30)
    still_board(page, theme, 25)                                                      # same palette and same time of day as level 1 (they repeat every
    other = region(page, 10, 10, 50, 30)                                              # 6 and 24 levels): only the texture itself can tell them apart
    still_board(page, theme, 1)
    assert region(page, 10, 10, 50, 30) == one
    assert len({tuple(p) for p in one}) > 40                                          # a texture, not a flat colour
    differ = sum(1 for p, q in zip(one, other) if sum(abs(u - v) for u, v in zip(p, q)) > 4)
    assert differ > len(one) * 0.3, differ


def test_night_falls_every_third_band_of_six_levels(open_page):
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    lum = {}
    for level in (1, 13):                                                             # both use the first palette: day, then night
        still_board(page, 'flight', level)
        m = mean(region(page, 10, 10, 50, 60))
        lum[level] = 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]
    assert lum[13] < lum[1] * 0.75, lum


# ---- the flood that uncovers a capture -------------------------------------------------------------------------------
def test_a_capture_floods_out_from_its_route_and_ends_exactly_as_the_board_is(open_page):
    page = open_page(viewport=DESKTOP)
    still_board(page)
    far_before = mean(region(page, 3, 34, 5, 38))                                     # open water, far from where the route will be
    draw_across(page)
    got = page.evaluate('(() => { __pp.renderer.draw(1); return { revealing: __pp.renderer.revealing, far: 0 }; })()')
    assert got['revealing'] is True
    far_now = mean(region(page, 3, 34, 5, 38))
    assert sum(abs(a - b) for a, b in zip(far_now, far_before)) < 30, (far_now, far_before)     # 50 cells from the route: not reached yet
    page.wait_for_function('!__pp.renderer.revealing', timeout=2000)
    frame(page)
    far_after = mean(region(page, 3, 34, 5, 38))
    assert sum(far_after) < sum(far_before) * 0.6                                     # now it is dark claimed ground
    page.wait_for_function('!__pp.fx.active', timeout=3000)                            # (the capture's popup outlives the flood: let it go)
    frame(page)
    done = region(page, 2, 10, 28, 62)
    # The same capture on another page, under reduced motion (no flood at all): claimed ground does not depend on the
    # scenery's clock, so the two must match pixel for pixel.
    other = open_page(viewport=DESKTOP)
    other.emulate_media(reduced_motion='reduce')
    other.wait_for_function('__pp.renderer.reducedMotion === true')
    still_board(other)
    draw_across(other)
    other.wait_for_function('!__pp.fx.active', timeout=3000)
    frame(other)
    assert region(other, 2, 10, 28, 62) == done                                       # the flood leaves exactly what a plain paint shows


def test_a_capture_without_a_route_and_any_capture_under_reduced_motion_appear_at_once(open_page):
    page = open_page(viewport=DESKTOP)
    still_board(page)
    page.evaluate('__pp.cutLine("v", 30); 0')                                         # the test hooks' cut has no route to flood from
    assert page.evaluate('__pp.renderer.revealing') is False
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    still_board(page)
    draw_across(page)
    assert page.evaluate('__pp.renderer.revealing') is False


# ---- the sweep between levels -------------------------------------------------------------------------------------------
def test_the_next_level_sweeps_in_from_the_win_screen_and_only_from_there(open_page):
    page = open_page(viewport=DESKTOP)
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 110, y: 64 }]); __pp.forceWin(); 0')
    assert page.evaluate('__pp.state().phase') == 'clear'
    frame(page)
    assert page.evaluate('__pp.renderer.wipeAt') == float('-inf')
    page.evaluate('__pp.step(120); __pp.game.skipClear(); 0')                         # one second on, the win screen is skipped
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('__pp.state().level') == 2
    assert page.evaluate('performance.now() - __pp.renderer.wipeAt') < 500
    page.evaluate('__pp.game.startLevel(3); 0')                                       # a level started any other way just appears
    page.wait_for_timeout(500)
    wiped = page.evaluate('__pp.renderer.wipeAt')
    page.evaluate('__pp.game.startLevel(4); 0')
    assert page.evaluate('__pp.renderer.wipeAt') == wiped


# ---- sprites stand out --------------------------------------------------------------------------------------------------
def luminance(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize('theme', ['flight', 'drive'])
def test_a_patrol_stands_out_at_3_5_to_1_on_every_palette_and_time_of_day(open_page, theme):
    """Levels 1-24 cover all six palettes at each of the four times of day. Some part of the sprite (its body, its dark
    outline or its pale rim) must reach 3.5:1 against the ground around it, measured on the canvas: 3:1 is the minimum
    for a graphic, and the margin is for cloud shadows, which darken the ground under a patrol by up to about 14 % as
    they pass. (Measured: planes 4.12 at worst with the rim, 3.14 without it; cars 4.21 either way.)"""
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    worst = (99, None)
    for level in range(1, 25):
        still_board(page, theme, level, '[{ x: 60, y: 36 }]')
        sprite = region(page, 58, 34.8, 62, 37.2)
        ring = region(page, 52, 30, 68, 31.5) + region(page, 52, 40.5, 68, 42)
        ring.sort(key=luminance)
        ground = ring[len(ring) // 2]
        best = max(contrast(p, ground) for p in sprite)
        worst = min(worst, (best, level))
    assert worst[0] >= 3.5, worst


# ---- a lost route shatters where it lay -----------------------------------------------------------------------------------
def test_a_lost_route_shatters_along_its_length_and_marks_the_patrol_that_hit_it(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate("__pp.game.newRun({ seed: 'fx' }); __pp.setPatrols([{ x: 40, y: 50 }]); __pp.freeze(true)")
    page.evaluate('(() => { const r = __pp.game.route; r.begin(40, 1); for (let y = 2; y <= 60; y += 2) r.move(40, y); })()')   # through the patrol
    st = page.evaluate('__pp.fx.stats()')
    assert page.evaluate('__pp.state().lives') == 2
    ys = page.evaluate('Array.from(__pp.fx.y.slice(0, __pp.fx.n))')
    assert st['particles'] > 28 and st['rings'] == 2                                   # the tip's burst and ring, the shatter, and a ring on the culprit
    assert min(ys) < 12 and max(ys) > 40                                               # spread along the route, not only at its tip
