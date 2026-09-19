"""Edge tracers: the contour loops they crawl (checked against a brute-force oracle on random grids), how they
spawn and move, when they chase a route and when they cannot, what a capture does to them, and saving them."""
import pytest

DESKTOP = {'width': 1280, 'height': 800}

PRELUDE = """
  const contour = await import('/js/contour.js');
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { Grid, FIELD, WALL, BORDER, ROUTE } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { buildLevel } = await import('/js/level.js');
  const { STEP, levelInfo, GRID_W, GRID_H } = await import('/js/config.js');
  const { TRACER } = await import('/js/tracers.js');
  const backendOf = (initial = {}) => { const map = new Map(Object.entries(initial));
    return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: (k) => { map.delete(k); } }; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  /* A game on `level` with no patrol but one parked far away, and these tracers ({ x, y, dir }) exactly. */
  const setup = (level, tracers = null, seed = 'tracers', backend = backendOf()) => {
    const game = new Game({ storage: createStorage(backend) }); game.enterTitle(); game.newRun({ seed }); game.startLevel(level);
    game.level.patrols.length = 0; game.level.patrols.push(makePatrol(100, 62, 0, 0));
    if (tracers) game.tracers.place(tracers);
    game.events = []; game.on('tracer', (e) => game.events.push(e.type)); game.on('route', (e) => { if (e.type === 'hit') game.events.push('hit:' + e.by); });
    return game; };
  /* The oracle: the directed edges a boundary must have, by brute force. Open = in the grid and not solid. */
  const expectedEdges = (g) => { const set = new Set(); const open = (x, y) => x >= 0 && y >= 0 && x < g.w && y < g.h && !g.isSolid(x, y);
    for (let y = 0; y < g.h; y++) for (let x = 0; x < g.w; x++) { if (!open(x, y)) continue;
      if (!open(x, y - 1)) set.add(`${x},${y},0`); if (!open(x + 1, y)) set.add(`${x + 1},${y},1`);
      if (!open(x, y + 1)) set.add(`${x + 1},${y + 1},2`); if (!open(x - 1, y)) set.add(`${x},${y + 1},3`); }
    return set; };
  const dirOf = (dx, dy) => (dx === 1 && dy === 0 ? 0 : dx === 0 && dy === 1 ? 1 : dx === -1 && dy === 0 ? 2 : dx === 0 && dy === -1 ? 3 : -1);
  /* Everything that must hold of a set of loops over grid g. Returns a list of what is wrong. */
  const audit = (g, loops) => { const bad = []; const seen = new Set(); let area = 0;
    for (const [li, l] of loops.entries()) { let a2 = 0;
      for (let k = 0; k < l.n; k++) { const j = (k + 1) % l.n; const dir = dirOf(l.vx[j] - l.vx[k], l.vy[j] - l.vy[k]);
        if (dir < 0) bad.push(`loop ${li} edge ${k} is not one step long`);
        const key = `${l.vx[k]},${l.vy[k]},${dir}`; if (seen.has(key)) bad.push(`edge ${key} appears twice`); seen.add(key);
        a2 += l.vx[k] * l.vy[j] - l.vx[j] * l.vy[k]; }
      area += a2 / 2; }
    const want = expectedEdges(g);
    for (const key of want) if (!seen.has(key)) bad.push(`edge ${key} is in no loop`);
    for (const key of seen) if (!want.has(key)) bad.push(`edge ${key} is not a boundary edge`);
    let open = 0; for (let y = 0; y < g.h; y++) for (let x = 0; x < g.w; x++) if (!g.isSolid(x, y)) open++;
    if (Math.abs(area) !== open) bad.push(`the loops enclose ${Math.abs(area)} cells but ${open} are open`);
    for (let i = 1; i < loops.length; i++) if (loops[i].n > loops[i - 1].n) bad.push('loops are not longest first');
    return bad.slice(0, 5); };
  /* Distance (board units) from a point to the nearest loop segment. */
  const toContour = (game, x, y) => { let best = Infinity; const S = 2;
    for (const l of game.tracers.loops) for (let k = 0; k < l.n; k++) { const j = (k + 1) % l.n;
      const ax = l.vx[k] / S, ay = l.vy[k] / S, bx = l.vx[j] / S, by = l.vy[j] / S; const dx = bx - ax, dy = by - ay;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))); const ex = ax + dx * t - x, ey = ay + dy * t - y;
      best = Math.min(best, Math.hypot(ex, ey)); }
    return best; };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "\n}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- the contour loops -----------------------------------------------------------------------------------------------
def test_a_rectangular_field_has_one_loop_around_it_and_an_obstacle_adds_a_second(page):
    got = js(page, """
      const grid = (w, h, frame = 2) => { const g = new Grid(w, h); g.frame(frame); return g; };
      const g = grid(12, 9);                                                   // open interior: 8 x 5
      const a = contour.traceContours(g);
      const withBlock = grid(12, 9); withBlock.fillRect(5, 4, 7, 6, BORDER);  // a 2 x 2 obstacle inside
      const b = contour.traceContours(withBlock);
      return { plain: { loops: a.loops.map((l) => l.n), edges: a.edges, bad: audit(g, a.loops) },
               block: { loops: b.loops.map((l) => l.n), edges: b.edges, bad: audit(withBlock, b.loops) },
               solidsAreAdjacent: a.loops[0].solid.every((c, k) => c >= 0 && g.cells[c] === BORDER) };""")
    assert got['plain'] == {'loops': [26], 'edges': 26, 'bad': []}                   # 2 x (8 + 5) edges around the interior
    assert got['block'] == {'loops': [26, 8], 'edges': 34, 'bad': []}                # and 4 x 2 around the block, as its own loop
    assert got['solidsAreAdjacent'] is True


def test_two_open_cells_that_only_touch_at_a_corner_get_separate_loops(page):
    """The loop turns right at such a corner, keeping to the cell it is on: the game's flood fill is 4-connected, so those two
    cells are two separate areas, and a tracer must never cross from one to the other."""
    got = js(page, """
      const g = new Grid(4, 4); g.cells.fill(WALL); g.set(1, 1, FIELD); g.set(2, 2, FIELD);
      const t = contour.traceContours(g);
      return { loops: t.loops.map((l) => l.n), bad: audit(g, t.loops) };""")
    assert got == {'loops': [4, 4], 'bad': []}


def test_on_hundreds_of_random_grids_every_boundary_edge_is_in_exactly_one_closed_loop(page):
    got = js(page, """
      let seed = 987654321; const rnd = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296;
      const out = { grids: 0, edges: 0, problems: [] };
      for (let n = 0; n < 250; n++) {
        const w = 6 + Math.floor(rnd() * 22), h = 6 + Math.floor(rnd() * 16), density = 0.15 + rnd() * 0.5;
        const g = new Grid(w, h);
        for (let i = 0; i < g.cells.length; i++) g.cells[i] = rnd() < density ? (rnd() < 0.5 ? WALL : BORDER) : FIELD;
        if (n % 5 === 0) for (let i = 0; i < 6; i++) g.cells[Math.floor(rnd() * g.cells.length)] = ROUTE;          // a live route changes nothing
        const t = contour.traceContours(g);
        const bad = audit(g, t.loops); out.grids++; out.edges += t.edges;
        if (bad.length) out.problems.push(`${w}x${h} ${density.toFixed(2)}: ${bad.join('; ')}`);
      }
      return out;""")
    assert got['problems'] == [] and got['grids'] == 250 and got['edges'] > 20000


def test_positions_along_a_loop_interpolate_wrap_and_find_the_nearest_edge(page):
    got = js(page, """
      const g = new Grid(12, 9); g.frame(2); const { loops } = contour.traceContours(g); const l = loops[0];
      const at = (t) => contour.pointAt(l, t);
      const out = { start: at(0), half: at(0.5), wrapped: at(l.n + 0.5), sameAsFirst: JSON.stringify(at(l.n)) === JSON.stringify(at(0)) };
      // nearest edge against brute force, for points all over the board
      let seed = 4242; const rnd = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296; let wrong = 0;
      for (let i = 0; i < 200; i++) { const x = rnd() * 6, y = rnd() * 4.5; const near = contour.nearestEdge(loops, x, y);
        let best = Infinity; for (let k = 0; k < l.n; k++) { const j = (k + 1) % l.n; const mx = (l.vx[k] + l.vx[j]) / 4, my = (l.vy[k] + l.vy[j]) / 4; best = Math.min(best, (mx - x) ** 2 + (my - y) ** 2); }
        if (Math.abs(near.d2 - best) > 1e-9) wrong++; }
      out.wrong = wrong; out.firstVertex = [l.vx[0] / 2, l.vy[0] / 2]; out.secondVertex = [l.vx[1] / 2, l.vy[1] / 2];
      return out;""")
    assert got['wrong'] == 0 and got['sameAsFirst'] is True
    assert (got['start']['x'], got['start']['y']) == tuple(got['firstVertex'])
    assert got['half']['x'] == pytest.approx((got['firstVertex'][0] + got['secondVertex'][0]) / 2) and got['wrapped'] == got['half']


# ---- spawning --------------------------------------------------------------------------------------------------------
def test_tracers_appear_from_level_four_one_more_every_three_levels_up_to_three(page):
    got = js(page, """
      const counts = {}; for (const level of [1, 2, 3, 4, 5, 6, 7, 9, 10, 13, 30]) counts[level] = setup(level).tracers.list.length;
      const info = [1, 4, 7, 10, 13].map((l) => levelInfo(l).tracers);
      const game = setup(4); const onLoop = game.tracers.list.every((t) => toContour(game, t.x, t.y) < 1e-6);
      const tutorial = new Game({ storage: createStorage(backendOf()) }); tutorial.enterTitle(); tutorial.startTutorial();
      const title = new Game({ storage: createStorage(backendOf()) }); title.enterTitle();
      return { counts, info, onLoop, tutorial: tutorial.tracers.list.length, attract: title.tracers.list.length };""")
    assert got['counts'] == {'1': 0, '2': 0, '3': 0, '4': 1, '5': 1, '6': 1, '7': 2, '9': 2, '10': 3, '13': 3, '30': 3}
    assert got['info'] == [0, 1, 2, 3, 3] and got['onLoop'] is True
    assert got['tutorial'] == 0 and got['attract'] == 1                              # none in the tutorial; the title's level 6 has one crawling


def test_spawning_is_deterministic_evenly_spaced_and_leaves_every_layout_alone(page):
    got = js(page, """
      const spawn = (seed, level) => setup(level, null, seed).tracers.list.map((t) => [t.loop, +t.t.toFixed(6), t.dir]);
      const out = { same: JSON.stringify(spawn('daily-x', 10)) === JSON.stringify(spawn('daily-x', 10)) };
      const others = new Set(); for (let i = 0; i < 20; i++) others.add(JSON.stringify(spawn('seed' + i, 10)));
      out.varies = others.size;
      const dirs = new Set(); for (let i = 0; i < 30; i++) for (const t of setup(10, null, 'dir' + i).tracers.list) dirs.add(t.dir);
      out.directions = [...dirs].sort();
      const n = setup(10).tracers.loops[0].n; const three = spawn('spacing', 10);
      const gaps = three.map((t, i) => (three[(i + 1) % 3][1] - t[1] + n) % n).sort((a, b) => a - b);
      out.spacing = { n, gaps: gaps.map((g) => +g.toFixed(4)), third: +(n / 3).toFixed(4) };
      // the layout streams are untouched: the level a game builds has exactly the obstacles and patrols buildLevel alone gives
      const game = new Game({ storage: createStorage(backendOf()) }); game.enterTitle(); game.newRun({ seed: 'layout' }); game.startLevel(9);
      const alone = buildLevel(9, 'layout', new Grid());
      const shape = (lvl) => JSON.stringify({ o: lvl.obstacles, p: lvl.patrols.map((p) => [p.x, p.y, p.vx, p.vy]) });
      out.layoutSame = shape(game.level) === shape(alone);
      return out;""")
    assert got['same'] is True and got['varies'] > 10 and got['directions'] == [-1, 1]      # both ways round, chosen by the seed
    assert got['spacing']['gaps'] == [got['spacing']['third']] * 3                    # exactly a third of the loop apart
    assert got['layoutSame'] is True


# ---- moving -----------------------------------------------------------------------------------------------------------
def test_a_tracer_crawls_the_boundary_at_exactly_22_units_a_second_in_its_direction_and_wraps(page):
    got = js(page, """
      const game = setup(4, [{ x: 30, y: 2, dir: 1 }, { x: 90, y: 70, dir: -1 }]);
      const [a, b] = game.tracers.list; const n = game.tracers.loops[0].n; const t0 = [a.t, b.t];
      const start = [[a.x, a.y], [b.x, b.y]];
      run(game, 1);
      const out = { n, forward: (a.t - t0[0] + n) % n, backward: (t0[1] - b.t + n) % n, moved: [Math.hypot(a.x - start[0][0], a.y - start[0][1]), Math.hypot(b.x - start[1][0], b.y - start[1][1])] };
      let worst = 0, inRange = true;
      for (let i = 0; i < 4000; i++) { game.step(STEP); if (i % 37 === 0) { for (const t of game.tracers.list) { worst = Math.max(worst, toContour(game, t.x, t.y)); if (!(t.t >= 0 && t.t < game.tracers.loops[t.loop].n)) inRange = false; } } }
      out.worst = worst; out.inRange = inRange; out.lapsAround = 4000 * STEP * 22 * 2 > n;
      return out;""")
    assert got['forward'] == pytest.approx(44) and got['backward'] == pytest.approx(44)          # 22 u/s = 44 cells/s, either way round
    assert all(0 < d <= 22.001 for d in got['moved'])
    assert got['worst'] < 1e-6 and got['inRange'] is True and got['lapsAround'] is True          # always on the boundary line, and it laps the board


def test_tracers_stand_still_when_paused_and_on_the_win_screen_but_crawl_on_the_title(page):
    got = js(page, """
      const game = setup(4); const t = game.tracers.list[0]; run(game, 0.5);
      game.pause('manual'); const paused = [t.x, t.y]; run(game, 1); const stillPaused = t.x === paused[0] && t.y === paused[1]; game.resume();
      game.commitCapture((() => { const g = game.grid, c = []; for (let y = 0; y < g.h; y++) if (g.get(180, y) === FIELD) c.push(g.index(180, y)); return c; })());     // 76%: a win, with the patrol's side still open
      const won = game.phase; const open = game.grid.countField() > 0; const at = [game.tracers.list[0].x, game.tracers.list[0].y]; run(game, 1);
      const title = new Game({ storage: createStorage(backendOf()) }); title.enterTitle(); const tt = title.tracers.list[0]; const before = [tt.x, tt.y]; run(title, 1);
      return { stillPaused, won, open, frozenOnWin: at[0] === game.tracers.list[0].x && at[1] === game.tracers.list[0].y, crawlsOnTitle: Math.hypot(tt.x - before[0], tt.y - before[1]) > 5 };""")
    assert got['stillPaused'] is True and got['won'] == 'clear' and got['open'] is True    # a win with a boundary left to crawl...
    assert got['frozenOnWin'] is True and got['crawlsOnTitle'] is True                      # ...that the tracers leave alone until the next level


# ---- the threat ---------------------------------------------------------------------------------------------------------
CHASE = """
  /* Draw from (40, 1) with the tip advancing `perStep` board units each physics step; returns what happened. */
  const drawSlowly = (game, perStep, steps = 400, from = 3) => {
    const r = game.route; r.begin(40, 1); let y = from; r.move(40, y);
    for (let i = 0; i < steps && game.route.mode === 'drawing'; i++) { y = Math.min(70.9, y + perStep); r.move(40, y); game.step(STEP); }
    return { mode: r.mode, lives: game.run.lives, y, events: [...game.events], routeCells: game.grid.count(ROUTE) };
  };
"""


def test_a_tracer_at_the_start_of_a_slow_route_chases_it_down_and_catches_the_tip(page):
    got = js(page, CHASE + """
      const game = setup(4, [{ x: 40, y: 2, dir: -1 }]);                       // on the boundary right where the route will start
      const t = game.tracers.list[0]; let noticedAt = null;
      game.on('tracer', (e) => { if (e.type === 'chase') noticedAt = t.t; });                  // its place along the loop when it set off
      const result = drawSlowly(game, 0.1);                                    // 12 u/s: slower than the 26.4 u/s chase
      return { ...result, tracerMode: t.mode, backHome: noticedAt !== null && Math.abs(t.t - noticedAt) < 1e-9, onContour: toContour(game, t.x, t.y) };""")
    assert got['events'][0] == 'chase' and got['events'][1:3] == ['caught', 'hit:tracer']
    assert got['lives'] == 2 and got['mode'] == 'spent' and got['routeCells'] == 0                # a life lost, the route gone
    assert got['tracerMode'] == 'patrol' and got['backHome'] is True and got['onContour'] < 1e-6    # patrolling again from where it set off, back on the boundary


def test_a_fast_swipe_outruns_a_tracer_and_closes_without_being_caught(page):
    got = js(page, CHASE + """
      const game = setup(4, [{ x: 40, y: 2, dir: -1 }]);
      const result = drawSlowly(game, 0.4);                                    // 48 u/s: faster than the chase
      return { ...result, cleared: game.level.cleared };""")
    assert 'chase' in got['events'] and 'caught' not in got['events'] and 'hit:tracer' not in got['events']       # it noticed, and could not catch up
    assert got['lives'] == 3 and got['cleared'] > 20                                                              # the route closed as a capture


def test_a_finger_resting_on_the_edge_is_safe_however_long_a_tracer_takes_to_pass(page):
    got = js(page, """
      const game = setup(4, [{ x: 40, y: 2, dir: 1 }]);
      game.route.begin(40, 1);                                                  // armed on the frame, not drawing
      const t = game.tracers.list[0]; let chased = false;
      for (let i = 0; i < 120 * 25; i++) { game.step(STEP); if (t.mode === 'chase') chased = true; }     // 25 s: it laps the whole board
      return { chased, lives: game.run.lives, mode: game.route.mode, events: game.events };""")
    assert got == {'chased': False, 'lives': 3, 'mode': 'armed', 'events': []}


def test_a_tracer_only_notices_a_route_when_it_reaches_the_place_it_started(page):
    got = js(page, CHASE + """
      const out = {};
      // far away along the boundary: nothing happens to a short quick route
      let game = setup(4, [{ x: 100, y: 70, dir: 1 }]); out.far = drawSlowly(game, 0.05, 30).events;
      // coming towards the start: it arrives, notices, and only then chases
      game = setup(4, [{ x: 30, y: 2, dir: 1 }]);                               // 10 units (20 cells) short of x = 40, heading towards it
      game.route.begin(40, 1); game.route.move(40, 3); let noticedAt = null;
      for (let i = 0; i < 120 && noticedAt === null; i++) { game.route.move(40, 3 + i * 0.01); game.step(STEP); if (game.events.includes('chase')) noticedAt = i * STEP; }
      out.noticedAt = noticedAt;
      // the same tracer heading the other way never gets there in that time
      game = setup(4, [{ x: 30, y: 2, dir: -1 }]);
      game.route.begin(40, 1); game.route.move(40, 3); for (let i = 0; i < 120; i++) { game.route.move(40, 3 + i * 0.01); game.step(STEP); }
      out.awayAndNotNoticed = !game.events.includes('chase');
      return out;""")
    assert got['far'] == []
    assert 0.3 < got['noticedAt'] < 0.5                                                                # about 20 cells at 44 cells/s
    assert got['awayAndNotNoticed'] is True


def test_a_tracer_on_another_loop_cannot_reach_a_route_and_a_closed_or_lifted_route_ends_the_chase(page):
    got = js(page, CHASE + """
      const out = {};
      let game = setup(5, null);                                               // level 5 has two obstacles: their edges are loops of their own
      const o = game.level.obstacles[0]; game.tracers.place([{ x: o.x + o.w / 2, y: o.y - 0.02, dir: 1 }]);
      out.onObstacleLoop = game.tracers.list[0].loop !== 0;
      out.obstacleTracer = drawSlowly(game, 0.02, 200).events;                 // slow drawing from the frame, right under a tracer that can never come
      game = setup(4, [{ x: 40, y: 2, dir: -1 }]);
      game.route.begin(40, 1); game.route.move(40, 4); game.step(STEP);        // the tracer sets off after the route...
      out.chasing = game.tracers.list[0].mode; const at = game.tracers.list[0].t;
      game.route.end('lift');                                                  // ...and the finger lifts
      game.step(STEP);
      out.afterLift = { mode: game.tracers.list[0].mode, samePlace: Math.abs(game.tracers.list[0].t - at) < 0.5, lives: game.run.lives,
                        caught: game.events.includes('caught') };              // it gave up: nothing was caught
      return out;""")
    assert got['onObstacleLoop'] is True and 'chase' not in got['obstacleTracer']
    assert got['chasing'] == 'chase' and got['afterLift'] == {'mode': 'patrol', 'samePlace': True, 'lives': 3, 'caught': False}


# ---- captures ---------------------------------------------------------------------------------------------------------------
def test_a_capture_traces_the_boundary_again_and_puts_each_tracer_on_the_nearest_remaining_edge(page):
    got = js(page, """
      const game = setup(4, [{ x: 20, y: 2, dir: 1 }]);
      const before = game.tracers.loops.map((l) => l.n); const t = game.tracers.list[0];
      // a route that claims the left third, with the tracer standing inside what gets claimed
      game.route.begin(40, 1); game.route.move(40, 30); game.route.move(40, 71);
      const after = game.tracers.loops.map((l) => l.n);
      const bad = audit(game.grid, game.tracers.loops);
      // the nearest edge of the new contour, by brute force from where the tracer was standing
      const spot = contour.nearestEdge(game.tracers.loops, 20, 2);
      return { before, after, bad, mode: t.mode, onContour: toContour(game, t.x, t.y), phase: game.phase, lives: game.run.lives,
               nowAt: [t.x, t.y], expected: [game.tracers.loops[spot.loop].vx[spot.k] / 2, game.tracers.loops[spot.loop].vy[spot.k] / 2] };""")
    assert got['bad'] == [] and got['before'] != got['after']                                   # the loops really changed, and are still exact
    assert got['mode'] == 'patrol' and got['onContour'] < 1e-6 and got['lives'] == 3
    assert got['nowAt'] == pytest.approx(got['expected'])                                         # snapped to the nearest edge start of the new boundary


def test_a_level_played_with_tracers_keeps_the_loops_exact_through_many_captures(page):
    got = js(page, """
      const game = setup(7); const problems = []; let captures = 0;
      for (const x of [10, 14, 30, 34, 50, 54, 70, 74, 90]) {
        const cells = []; const g = game.grid, col = Math.floor(x * 2); for (let y = 0; y < g.h; y++) if (g.get(col, y) === FIELD) cells.push(g.index(col, y));
        game.commitCapture(cells); captures++;
        const bad = audit(game.grid, game.tracers.loops); if (bad.length) problems.push(`after ${x}: ${bad.join('; ')}`);
        for (const t of game.tracers.list) if (toContour(game, t.x, t.y) > 1e-6) problems.push(`tracer off the boundary after ${x}`);
        run(game, 0.3);
        if (game.phase !== 'playing') break;
      }
      return { problems, captures, loops: game.tracers.loops.length, count: game.tracers.list.length };""")
    assert got['problems'] == [] and got['captures'] >= 5 and got['count'] == 2


# ---- saving and showing -----------------------------------------------------------------------------------------------------
def test_a_resumed_run_puts_the_tracers_back_exactly_and_they_carry_on_identically(page):
    got = js(page, """
      const backend = backendOf(); const A = setup(7, null, 'resume-tracers', backend);
      run(A, 2.3); A.commitCapture((() => { const g = A.grid, c = []; for (let y = 0; y < g.h; y++) if (g.get(20, y) === FIELD) c.push(g.index(20, y)); return c; })()); run(A, 1.7);
      A.persist();
      const B = new Game({ storage: createStorage(backend) }); B.enterTitle(); const offered = !!B.saved && B.saved.tracers.length; B.resumeRun(); B.tick(3.1);
      const rows = (g) => JSON.stringify(g.tracers.list.map((t) => [t.loop, t.t, t.dir, t.x, t.y, t.mode]));
      const out = { offered, same: rows(A) === rows(B), rows: A.tracers.list.length };
      B.level.patrols.length = 0; B.level.patrols.push(makePatrol(100, 62, 0, 0)); A.level.patrols.length = 0; A.level.patrols.push(makePatrol(100, 62, 0, 0));
      run(A, 3); run(B, 3); out.stillSame = rows(A) === rows(B); return out;""")
    assert got == {'offered': 2, 'same': True, 'rows': 2, 'stillSame': True}


def test_a_snapshot_with_the_wrong_tracers_is_not_trusted_and_one_that_does_not_fit_respawns_them(page):
    got = js(page, """
      const snap = await import('/js/snapshot.js');
      const game = setup(7, null, 'validate'); game.persist();
      const good = JSON.parse(game.storage.loadSnapshot ? JSON.stringify(game.storage.loadSnapshot()) : 'null');
      const edit = (fn) => { const c = JSON.parse(JSON.stringify(good)); fn(c); return c; };
      const ok = (raw) => snap.validateSnapshot(raw) !== null;
      const out = { good: ok(good), rejected: {} };
      const bad = { 'missing': (c) => { delete c.tracers; }, 'one too few': (c) => { c.tracers.pop(); }, 'one too many': (c) => { c.tracers.push([0, 1, 1]); },
        'text position': (c) => { c.tracers[0][1] = '5'; }, 'NaN': (c) => { c.tracers[0][1] = NaN; }, 'a sideways direction': (c) => { c.tracers[0][2] = 0; },
        'a fractional loop': (c) => { c.tracers[0][0] = 0.5; }, 'a negative position': (c) => { c.tracers[0][1] = -1; }, 'a short row': (c) => { c.tracers[0] = [0, 1]; } };
      for (const [name, fn] of Object.entries(bad)) out.rejected[name] = ok(edit(fn));
      // rows that pass validation but do not fit this board: the game starts the tracers afresh instead
      const b2 = backendOf(); const g2 = setup(7, null, 'respawn', b2); g2.persist();
      const raw = JSON.parse(b2.map.get('pathpatrol:v2:run')); raw.tracers = raw.tracers.map((t) => [999, t[1], t[2]]); b2.map.set('pathpatrol:v2:run', JSON.stringify(raw));
      const g3 = new Game({ storage: createStorage(b2) }); g3.enterTitle(); g3.resumeRun();
      out.respawned = { count: g3.tracers.list.length, onLoop: g3.tracers.list.every((t) => toContour(g3, t.x, t.y) < 1e-6) };
      return out;""")
    assert got['good'] is True and not any(got['rejected'].values()), [k for k, v in got['rejected'].items() if v]
    assert got['respawned'] == {'count': 2, 'onLoop': True}


def test_tracers_are_drawn_amber_and_coral_while_chasing_and_a_chase_says_so(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.newRun({ seed: "look" }); __pp.game.startLevel(4); __pp.setPatrols([{ x: 100, y: 62 }]); __pp.setTracers([{ x: 40, y: 2, dir: 1 }]); __pp.freeze(true)')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('__pp.renderer.tracersDrawn') == 1

    def centre():
        t = page.evaluate('({ x: __pp.game.tracers.list[0].x, y: __pp.game.tracers.list[0].y })')
        at = page.evaluate('([x, y]) => __pp.toClient(x, y)', [t['x'], t['y']])
        return page.evaluate("""([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
          const s = document.createElement('canvas'); s.width = s.height = 1; const g = s.getContext('2d', { willReadFrequently: true });
          g.drawImage(c, Math.round((x - r.left) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1);
          return Array.from(g.getImageData(0, 0, 1, 1).data); }""", [at['x'], at['y']])
    r, g, b, _ = centre()
    assert r > 200 and 130 < g < 210 and b < 150                                        # amber at the tracer's position
    page.evaluate('__pp.game.route.begin(40, 1); __pp.game.route.move(40, 3); __pp.step(1)')          # one physics step: it sets off after the route
    assert page.evaluate('__pp.game.tracers.list[0].mode') == 'chase'
    assert page.locator('#toast').text_content() == 'A tracer is chasing your route'
    assert page.evaluate('__pp.fx.stats().rings') == 1                                   # a ring where it noticed
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    r, g, b, _ = centre()
    assert r > 200 and g < 160 and b < 130                                               # coral while it chases
