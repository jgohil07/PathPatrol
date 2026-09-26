"""Special levels (round 2): every fifth level is special, alternating an odd-shaped board (5, 15, 25...) and a boss (10, 20,
30...), and the level after each starts with an early pickup. Limits pinned as literals, as elsewhere."""
import math

import pytest

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP, levelInfo, KINDS } = await import('/js/config.js');
  const { Grid, FIELD, WALL, BORDER } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { buildLevel, SHAPE_NAMES } = await import('/js/level.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const fresh = (level, seed = 'special') => {
    const storage = createStorage(memoryBackend()); const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed });
    if (level !== 1) game.startLevel(level); return { game, storage }; };
  // A level stripped to its frame (no obstacles, no tracers), so the cell counts below are exact.
  const bare = (game) => { game.grid.clear(); game.grid.frame(4); game.level.obstacles = []; game.level.initialPlayable = game.grid.countField(); game.tracers.list.length = 0; game.tracers.refresh(); };
  const place = (game, patrols) => { game.level.patrols.length = 0; for (const [x, y, vx, vy, kind] of patrols) game.level.patrols.push(makePatrol(x, y, vx, vy, kind)); };
  const col = (game, cx, y0 = 0, y1 = 144) => { const g = game.grid, out = []; for (let y = y0; y < y1; y++) if (g.get(cx, y) === FIELD) out.push(g.index(cx, y)); return out; };
  const row = (game, cy, x0 = 0, x1 = 240) => { const g = game.grid, out = []; for (let x = x0; x < x1; x++) if (g.get(x, cy) === FIELD) out.push(g.index(x, cy)); return out; };
  const connected = (g) => { let start = -1; for (let i = 0; i < g.cells.length; i++) if (g.cells[i] === FIELD) { start = i; break; }
    const seen = new Uint8Array(g.cells.length), st = [start]; seen[start] = 1; let n = 1;
    while (st.length) { const i = st.pop(), x = i % g.w; for (const j of [i - 1, i + 1, i - g.w, i + g.w]) {
      if (j < 0 || j >= g.cells.length || (Math.abs((j % g.w) - x) > 1) || seen[j] || g.cells[j] !== FIELD) continue; seen[j] = 1; n++; st.push(j); } }
    return n === g.countField(); };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- where the specials fall ----------------------------------------------------------------------------------------
def test_every_fifth_level_is_special_alternating_a_shape_and_a_boss_and_the_next_is_a_valley(page):
    got = js(page, "return Array.from({ length: 45 }, (_, i) => { const x = levelInfo(i + 1); return [x.special, x.valley, x.kinds.includes('boss')]; });")
    for level, (special, valley, boss) in enumerate(got, start=1):
        want = None if level % 5 else ('shape' if (level // 5) % 2 == 1 else 'boss')
        assert special == want, level
        assert valley == (level > 5 and level % 5 == 1), level
        assert boss == (want == 'boss'), level
    assert [got[l - 1][0] for l in (5, 10, 15, 20, 25, 30, 35, 40, 45)] == ['shape', 'boss'] * 4 + ['shape']


def test_the_boss_takes_the_place_of_a_standard_patrol_and_the_curve_keeps_its_numbers(page):
    got = js(page, "return [9, 10, 11, 19, 20, 29, 30, 31, 40].map((l) => { const x = levelInfo(l); return [l, x.patrols, x.kinds]; });")
    S, C, B, H, X = 'standard', 'scout', 'bomber', 'hunter', 'boss'
    assert got == [[9, 2, [S, C]], [10, 2, [X, C]], [11, 3, [S, S, C]], [19, 4, [S, C, B, H]], [20, 4, [X, C, B, H]],
                   [29, 6, [S, S, S, C, B, H]], [30, 6, [X, S, S, C, B, H]], [31, 6, [S, S, S, C, B, H]], [40, 6, [X, S, S, C, B, H]]]


def test_the_boss_is_big_slow_and_turns_slowly_after_a_long_wind_up(page):
    got = js(page, "return { ...KINDS.boss };")
    assert got['radius'] == 3.5 and got['speed'] == 0.6 and got['windup'] == 0.8
    assert got['turn'] == pytest.approx(math.radians(30))


# ---- shaped boards ---------------------------------------------------------------------------------------------------
def test_every_shape_leaves_one_connected_field_with_room_for_the_whole_level(page):
    got = js(page, """
      const plain = (() => { const g = new Grid(); buildLevel(1, 'plain', g); return g.countField(); })();
      const bad = [], seen = {}; let smallest = 1, largest = 0;
      for (let s = 0; s < 80; s++) for (const n of [5, 15, 25, 35, 45]) {
        const g = new Grid(); const l = buildLevel(n, 'shape' + s, g); const info = levelInfo(n);
        seen[l.shape.name] = (seen[l.shape.name] || 0) + 1;
        const share = l.initialPlayable / plain; smallest = Math.min(smallest, share); largest = Math.max(largest, share);
        if (!connected(g)) bad.push(`${s}/${n} ${l.shape.name}: the field is in pieces`);
        if (l.patrols.length !== info.patrols) bad.push(`${s}/${n} ${l.shape.name}: ${l.patrols.length} patrols, wanted ${info.patrols}`);
        if (l.obstacles.length !== info.obstacles) bad.push(`${s}/${n} ${l.shape.name}: ${l.obstacles.length} obstacles, wanted ${info.obstacles}`);
        for (const p of l.patrols) if (g.circleHitsSolid(p.x, p.y, p.r)) bad.push(`${s}/${n}: a patrol starts in a wall`);
        if (l.initialPlayable !== g.countField()) bad.push(`${s}/${n}: initialPlayable is stale`);
      }
      const plainLevel = (() => { const g = new Grid(); return buildLevel(6, 'shape0', g).shape; })();
      return { bad: bad.slice(0, 5), seen, names: SHAPE_NAMES, smallest, largest, plainLevel };""")
    assert got['bad'] == []
    assert sorted(got['seen']) == sorted(got['names']) and len(got['names']) == 6       # all six turn up
    assert 0.6 < got['smallest'] and got['largest'] < 0.97                              # never a sliver, and every shape takes a real part (the
                                                                                         # twin bays' dividing wall only ~5 %, but it splits the board)
    assert got['plainLevel'] is None


def test_a_shaped_board_is_the_same_for_everyone_and_survives_a_save(page):
    got = js(page, """
      const a = new Grid(), b = new Grid(); const la = buildLevel(15, 'same', a), lb = buildLevel(15, 'same', b);
      const { game, storage } = fresh(15, 'saved'); game.persist();
      const again = new Game({ storage }); again.enterTitle(); const resumed = again.resumeRun();
      return { same: JSON.stringify(la.shape) === JSON.stringify(lb.shape) && a.cells.every((v, i) => v === b.cells[i]),
               resumed, shape: again.level.shape, grid: again.grid.cells.every((v, i) => v === game.grid.cells[i]) };""")
    assert got['same'] and got['resumed'] and got['grid'] and got['shape'] is not None


# ---- the boss --------------------------------------------------------------------------------------------------------------
def test_trapping_the_boss_in_twelve_percent_wins_the_level_at_once_with_its_bonus(page):
    """Level 10 stripped to its frame: 31,552 open cells, so the boss's limit is 3,786.24 cells and the others' 1,262.08. The cut
    down column 208 leaves the right 27 columns x 136 = 3,672 cells: a pocket for the boss, not for anyone else."""
    got = js(page, """
      const { game } = fresh(10); bare(game); const events = []; game.on('trap', (e) => events.push(e));
      place(game, [[110, 36, 6, 4, 'boss'], [20, 20, 9, 7, 'scout']]);
      const r = game.commitCapture(col(game, 208));
      return { phase: game.phase, cleared: game.level.cleared, trapped: r.trapped, trapPoints: r.trapPoints, boss: events[0] && events[0].boss,
               sweep: events[0] && events[0].sweep, left: game.level.patrols.length, field: game.level.initialPlayable };""")
    assert got['field'] == 31552
    assert got['trapped'] == 1 and got['boss'] is True and got['sweep'] is True and got['left'] == 0
    assert got['trapPoints'] == 5000 and got['phase'] == 'clear' and got['cleared'] == 100


def test_a_boss_pocket_just_over_twelve_percent_is_not_a_trap_and_the_others_keep_four(page):
    got = js(page, """
      const out = {};
      { const { game } = fresh(10); bare(game); place(game, [[110, 36, 6, 4, 'boss'], [20, 20, 9, 7, 'scout']]);
        const r = game.commitCapture(col(game, 206)); out.over = { trapped: r.trapped, phase: game.phase, left: game.level.patrols.length }; }  // 29 x 136 = 3,944 cells
      { const { game } = fresh(10); bare(game); place(game, [[110, 36, 6, 4, 'scout'], [20, 20, 9, 7, 'boss']]);
        const r = game.commitCapture(col(game, 208)); out.scout = { trapped: r.trapped, left: game.level.patrols.length }; }         // 3,672 cells: too big for a scout
      return out;""")
    assert got['over'] == {'trapped': 0, 'phase': 'playing', 'left': 2}
    assert got['scout'] == {'trapped': 0, 'left': 2}


def test_the_boss_winds_up_for_eight_tenths_then_turns_no_faster_than_30_degrees_a_second(page):
    got = js(page, """
      const { game } = fresh(10); bare(game); place(game, [[60, 50, 12, 4, 'boss'], [20, 20, 9, 7, 'scout']]);
      const b = game.level.patrols[0]; const r = game.route; r.begin(100, 1); r.move(100, 8);
      const ang = () => Math.atan2(b.vy, b.vx); const d = (x, y) => { let v = x - y; v -= Math.PI * 2 * Math.round(v / (Math.PI * 2)); return v; };
      let early = 0, most = 0; const start = ang();
      for (let i = 0; i < 240; i++) { const a0 = ang(); game.step(STEP); const t = Math.abs(d(ang(), a0)); if (i < 95) early = Math.max(early, t); else most = Math.max(most, t); }
      return { early, most, turned: Math.abs(d(ang(), start)) };""")
    assert got['early'] < 1e-12                                                          # nothing for 95 steps (0.79 s)
    assert got['most'] <= math.radians(30) / 120 + 1e-9 and got['turned'] > math.radians(10)


def test_the_level_line_names_the_twist_and_the_boss_is_drawn_from_its_own_sprite(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    said = page.evaluate("""(() => { const out = []; __pp.game.on('toast', (t) => out.push(t.text));
      __pp.game.newRun({ seed: 'twist' }); for (const l of [5, 6, 10]) __pp.game.startLevel(l); return out.filter((t) => t.startsWith('Level')); })()""")
    assert said == ['Level 01 · clear 65%', 'Level 05 · clear 66% · odd board', 'Level 06 · clear 66%', 'Level 10 · clear 68% · boss']
    page.wait_for_function("Object.values(__pp.renderer.sprites).every((set) => set.boss && set.boss.complete && set.boss.naturalWidth > 0)")
    assert page.evaluate("__pp.renderer.sprites.flight.boss.src.split('/').pop()") == 'boss.svg'
    assert page.evaluate("__pp.renderer.sprites.drive.boss.src.split('/').pop()") == 'boss-car.svg'


# ---- the valley after the peak --------------------------------------------------------------------------------------------
def test_the_level_after_a_special_offers_its_first_pickup_within_four_seconds(page):
    got = js(page, """
      const out = {};
      for (const l of [6, 7, 11, 12, 16, 21, 31]) for (let s = 0; s < 12; s++) { const { game } = fresh(l, 'valley' + s);
        const first = game.powerups.nextAt - game.clock.now; (out[l] = out[l] || []).push(first); }
      return Object.fromEntries(Object.entries(out).map(([l, v]) => [l, [Math.min(...v), Math.max(...v)]]));""")
    for level in ('6', '11', '16', '21', '31'):
        lo, hi = got[level]
        assert 2 <= lo and hi <= 4, (level, got[level])
    for level in ('7', '12'):
        lo, hi = got[level]
        assert 12 <= lo and hi <= 20, (level, got[level])
