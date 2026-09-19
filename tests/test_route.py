"""The route engine and the geometry under it, tested directly (no browser input): what a route does
when it is drawn, closed, hit, lifted or interrupted. Real pointer input is in test_drawing.py."""
import pytest

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { FIELD, WALL, BORDER, ROUTE, toCell, walkCells } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { STEP } = await import('/js/config.js');
  const { simplify, MIN_ROUTE_CELLS } = await import('/js/route.js');
  /* A level-1 game (open board, 2-unit frame, no obstacles) with exactly these patrols. */
  const fresh = (patrols = []) => {
    const game = new Game({ storage: createStorage(memoryBackend()) });
    game.enterTitle(); game.newRun({ seed: 'route-tests' });
    game.level.patrols.length = 0;
    for (const p of patrols) game.level.patrols.push(makePatrol(p.x, p.y, p.vx || 0, p.vy || 0));
    game.events = []; game.on('route', (e) => game.events.push(e.type));
    return game;
  };
  const drag = (game, points, snap = 0) => { const r = game.route; r.begin(points[0][0], points[0][1], snap); for (const [x, y] of points.slice(1)) r.move(x, y); return r; };
  const count = (game, kind) => game.grid.count(kind);
"""


@pytest.fixture
def page(open_page):
    return open_page()


def run(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


# ---- walkCells -----------------------------------------------------------------------------------
def test_walk_cells_is_four_connected_and_visits_exactly_the_cells_the_line_crosses(page):
    got = page.evaluate("""async () => { const { walkCells } = await import('/js/grid.js');
      let seed = 42; const rnd = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296;
      const problems = [];
      for (let n = 0; n < 400; n++) {
        const x0 = rnd() * 40, y0 = rnd() * 40, x1 = rnd() * 40, y1 = rnd() * 40;
        const visited = []; walkCells(x0, y0, x1, y1, (cx, cy) => { visited.push([cx, cy]); });
        let prev = [Math.floor(x0), Math.floor(y0)];
        for (const [cx, cy] of visited) { if (Math.abs(cx - prev[0]) + Math.abs(cy - prev[1]) !== 1) problems.push(`gap at ${n}`); prev = [cx, cy]; }
        if (prev[0] !== Math.floor(x1) || prev[1] !== Math.floor(y1)) problems.push(`wrong end ${n}`);
        const want = Math.abs(Math.floor(x1) - Math.floor(x0)) + Math.abs(Math.floor(y1) - Math.floor(y0));
        if (visited.length !== want) problems.push(`length ${n}: ${visited.length} vs ${want}`);
        // brute force: every cell a finely sampled copy of the segment lands in must have been visited
        const seen = new Set([`${Math.floor(x0)},${Math.floor(y0)}`, ...visited.map((c) => c.join(','))]);
        for (let t = 0; t <= 4000; t++) { const f = t / 4000; const key = `${Math.floor(x0 + (x1 - x0) * f)},${Math.floor(y0 + (y1 - y0) * f)}`; if (!seen.has(key)) { problems.push(`missed ${key} in ${n}`); break; } }
      }
      const same = []; walkCells(3.2, 4.7, 3.9, 4.1, (cx, cy) => same.push([cx, cy]));
      const stop = []; walkCells(0, 0, 10, 0, (cx) => { stop.push(cx); return cx === 3; });
      const negative = []; walkCells(5.5, 5.5, 2.5, 3.5, (cx, cy) => negative.push([cx, cy]));
      const corner = []; walkCells(0.5, 0.5, 2.5, 2.5, (cx, cy) => corner.push([cx, cy]));           // straight through cell corners
      return { problems: problems.slice(0, 5), problemCount: problems.length, same, stop, negative, corner }; }""")
    assert got['problemCount'] == 0, got['problems']
    assert got['same'] == []                                   # start and end in one cell: nothing entered
    assert got['stop'] == [1, 2, 3]                            # the visitor can stop the walk
    assert got['negative'] == [[4, 5], [4, 4], [3, 4], [3, 3], [2, 3]]           # leftwards and upwards
    assert got['corner'] == [[1, 0], [1, 1], [2, 1], [2, 2]]                     # through exact cell corners: x first, never diagonal


def test_simplify(page):
    got = page.evaluate("""async () => { const { simplify } = await import('/js/route.js');
      const line = []; for (let i = 0; i <= 20; i++) line.push(i, i * 0.5);                            // dead straight
      const corner = [0, 0, 5, 0, 10, 0, 10, 5, 10, 10];                                                  // an L
      const wobble = []; for (let i = 0; i <= 40; i++) wobble.push(i * 0.25, Math.sin(i) * 0.02);         // noise below tolerance
      const bump = [0, 0, 2, 0, 4, 1, 6, 0, 8, 0];                                                        // a real bump: nothing may be dropped
      const noise = [0, 0, 1, 0.02, 2, 0, 3, -0.03, 4, 0];
      const dist = (p, a, b) => { const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy; const t = l ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l)) : 0; return Math.hypot(a[0] + dx * t - p[0], a[1] + dy * t - p[1]); };
      const simplified = simplify(wobble, 0.1); let worst = 0;
      for (let i = 0; i < wobble.length; i += 2) { let best = Infinity; for (let j = 0; j < simplified.length - 2; j += 2) best = Math.min(best, dist([wobble[i], wobble[i + 1]], [simplified[j], simplified[j + 1]], [simplified[j + 2], simplified[j + 3]])); worst = Math.max(worst, best); }
      return { line: simplify(line, 0.1), corner: simplify(corner, 0.1), wobbleLen: simplified.length, worst, bump: simplify(bump, 0.1), noise: simplify(noise, 0.1), two: simplify([1, 2, 3, 4], 0.1), one: simplify([1, 2], 0.1),
               idempotent: JSON.stringify(simplify(simplify(bump, 0.1), 0.1)) === JSON.stringify(simplify(bump, 0.1)) }; }""")
    assert got['line'] == [0, 0, 20, 10]
    assert got['corner'] == [0, 0, 10, 0, 10, 10]
    assert got['wobbleLen'] < 10 and got['worst'] <= 0.1 + 1e-9        # noise removed, never further than the tolerance
    assert got['bump'] == [0, 0, 2, 0, 4, 1, 6, 0, 8, 0]                # a real bump loses nothing
    assert got['noise'] == [0, 0, 4, 0]                                 # wobble under the tolerance is dropped
    assert got['two'] == [1, 2, 3, 4] and got['one'] == [1, 2] and got['idempotent']


# ---- arming and laying ---------------------------------------------------------------------------
def test_begin_on_safe_ground_arms_and_nothing_is_laid_yet(page):
    got = run(page, """const game = fresh(); const r = game.route;
      const armed = r.begin(40, 1);                                   // inside the 2-unit frame
      return { armed, mode: r.mode, down: r.down, anchor: r.anchor, cells: r.cells.length, routeCells: count(game, ROUTE), events: game.events };""")
    assert got == {'armed': True, 'mode': 'armed', 'down': True, 'anchor': {'cx': 80, 'cy': 2}, 'cells': 0, 'routeCells': 0, 'events': ['armed']}


def test_route_cells_exist_the_instant_the_pointer_moves(page):
    """The prototype waited for release, then grew a line at 39 cells/s. Here the cells are there at once."""
    got = run(page, """const game = fresh([]); const r = game.route; const sizes = [];
      r.begin(40, 1); sizes.push(r.cells.length);
      r.move(40, 10); sizes.push(r.cells.length, count(game, ROUTE));
      r.move(40, 30); sizes.push(r.cells.length, count(game, ROUTE));
      const idx = r.cells.slice(); const connected = idx.every((v, i) => i === 0 || Math.abs(v - idx[i - 1]) === game.grid.w || Math.abs(v - idx[i - 1]) === 1);
      const allRoute = idx.every((i) => game.grid.cells[i] === ROUTE);
      return { sizes, mode: r.mode, connected, allRoute, lastCellRow: Math.floor(idx[idx.length - 1] / game.grid.w), firstCellRow: Math.floor(idx[0] / game.grid.w), events: game.events };""")
    # cells 4..60 (world y 2..30) at column 80: 57 cells; the jump from the edge to y=10 alone lays cells 4..20
    assert got['sizes'] == [0, 17, 17, 57, 57]
    assert got['mode'] == 'drawing' and got['connected'] and got['allRoute']
    assert (got['firstCellRow'], got['lastCellRow']) == (4, 60)
    assert got['events'] == ['armed', 'start']


def test_a_single_huge_jump_lays_a_gap_free_path(page):
    got = run(page, """const game = fresh([{ x: 100, y: 40 }]); const r = game.route; r.begin(40, 1); r.move(40, 71);   // one event, edge to edge
      const g = game.grid; const wallColumn = []; for (let y = 4; y < 140; y++) wallColumn.push(g.get(80, y));
      // a single gap in that column would let the flood fill leak, leaving the left side open
      return { mode: r.mode, routeCells: count(game, ROUTE), cleared: game.level.cleared, wallColumnAllWall: wallColumn.every((v) => v === WALL),
               leftClaimed: g.get(40, 70) === WALL && g.get(10, 10) === WALL, rightOpen: g.get(160, 70) === FIELD, routes: game.level.routes.length, phase: game.phase };""")
    assert got['mode'] == 'armed' and got['routeCells'] == 0 and got['phase'] == 'playing'
    assert got['wallColumnAllWall'] and got['leftClaimed'] and got['rightOpen'] and got['routes'] == 1
    assert got['cleared'] == pytest.approx(33.19, abs=0.1)


# ---- closing -------------------------------------------------------------------------------------
def test_closing_claims_the_side_without_a_patrol(page):
    got = run(page, """const out = {};
      for (const [label, patrolX] of [['patrolRight', 100], ['patrolLeft', 12]]) {
        const game = fresh([{ x: patrolX, y: 20 }]); const r = drag(game, [[40, 1], [40, 30], [40, 71]]);
        const g = game.grid; const total = game.level.initialPlayable;
        out[label] = { cleared: game.level.cleared, mode: r.mode, routeCells: count(game, ROUTE), leftOpen: g.get(40, 70) === FIELD, rightOpen: g.get(160, 70) === FIELD,
                       consistent: Math.abs(game.level.cleared - (1 - g.countField() / total) * 100) < 1e-9, phase: game.phase, polyline: game.level.routes[0] };
      }
      return out;""")
    right, left = got['patrolRight'], got['patrolLeft']
    assert right['cleared'] == pytest.approx(33.19, abs=0.1) and right['phase'] == 'playing' and not right['leftOpen'] and right['rightOpen']
    assert left['cleared'] == pytest.approx(67.24, abs=0.1) and left['phase'] == 'clear' and left['leftOpen'] and not left['rightOpen']   # 65 % target reached
    assert right['consistent'] and left['consistent'] and right['routeCells'] == 0
    assert right['mode'] == 'armed' and left['mode'] == 'idle'                                     # a win ends the interaction
    poly = right['polyline']
    assert len(poly) >= 4 and poly[0] == pytest.approx(40.25) and poly[-1] == pytest.approx(70.25, abs=0.3)   # begins and ends on the two edges


def test_after_closing_the_pointer_keeps_sliding_and_can_start_the_next_route(page):
    got = run(page, """const game = fresh([{ x: 110, y: 40 }]); const r = game.route;
      drag(game, [[40, 1], [40, 30], [40, 71]]);                       // first route closes on the bottom frame
      const first = { mode: r.mode, routes: game.level.routes.length };
      r.move(60, 71.4); r.move(60, 40); r.move(60, 1);                 // slide along the frame, then straight back up: a second route
      return { first, mode: r.mode, routes: game.level.routes.length, cleared: game.level.cleared, down: r.down };""")
    assert got['first'] == {'mode': 'armed', 'routes': 1}
    assert got['routes'] == 2 and got['mode'] == 'armed' and got['down'] is True
    assert got['cleared'] > 40                                          # both strips claimed


def test_a_route_that_comes_straight_back_is_jitter_not_a_route(page):
    got = run(page, """const out = {};
      let game = fresh([{ x: 100, y: 40 }]); let r = drag(game, [[40, 1], [40, 2.6], [40, 1]]);     // 2 cells out and back
      out.two = { mode: r.mode, cleared: game.level.cleared, routes: game.level.routes.length, routeCells: count(game, ROUTE), openCells: game.grid.countField(), total: game.level.initialPlayable, events: game.events };
      game = fresh([{ x: 100, y: 40 }]); r = drag(game, [[40, 1], [40, 3.1], [40, 1]]);              // 3 cells: the minimum
      out.three = { routes: game.level.routes.length, cleared: game.level.cleared, min: MIN_ROUTE_CELLS };
      return out;""")
    assert got['two']['mode'] == 'armed' and got['two']['cleared'] == 0 and got['two']['routes'] == 0
    assert got['two']['routeCells'] == 0 and got['two']['openCells'] == got['two']['total']        # nothing left behind
    assert got['two']['events'] == ['armed', 'start', 'cancel']
    assert got['three']['min'] == 3 and got['three']['routes'] == 1 and got['three']['cleared'] > 0


def test_a_route_may_cross_itself_and_an_enclosed_loop_is_claimed(page):
    got = run(page, """const game = fresh([{ x: 105, y: 36 }]); const r = game.route;
      // down the left, a rectangle whose top edge crosses the vertical, then out to the bottom edge
      drag(game, [[30, 1], [30, 40], [45, 40], [45, 25], [30, 25], [20, 25], [20, 71]]);
      const g = game.grid;
      return { mode: r.mode, routeCells: count(game, ROUTE), loopInside: g.get(75, 65) === WALL, patrolSide: g.get(200, 70) === FIELD, stripLeft: g.get(20, 100) === WALL,
               phase: game.phase, cleared: game.level.cleared };""")
    assert got['routeCells'] == 0 and got['loopInside'] and got['patrolSide'] and got['stripLeft']
    assert got['phase'] == 'playing' and got['mode'] == 'armed'


# ---- hits ----------------------------------------------------------------------------------------
def test_drawing_into_a_patrol_costs_exactly_one_life_and_ignores_the_rest_of_the_drag(page):
    got = run(page, """const game = fresh([{ x: 40, y: 20 }]); const r = game.route;
      r.begin(40, 1); r.move(40, 12); const before = { lives: game.run.lives, mode: r.mode };
      r.move(40, 25);                                                  // through the patrol
      const hit = { lives: game.run.lives, mode: r.mode, routeCells: count(game, ROUTE), cells: r.cells.length };
      r.move(40, 60); r.move(40, 71); r.move(40, 40);                  // the rest of the drag: ignored
      const after = { lives: game.run.lives, mode: r.mode, routeCells: count(game, ROUTE), cleared: game.level.cleared };
      r.end(); const lifted = { mode: r.mode, down: r.down };
      game.level.patrols.length = 0; const again = drag(game, [[60, 1], [60, 71]]);         // a new drag works
      return { before, hit, after, lifted, events: game.events, againClosed: game.level.routes.length, phase: game.phase };""")
    assert got['before'] == {'lives': 3, 'mode': 'drawing'}
    assert got['hit'] == {'lives': 2, 'mode': 'spent', 'routeCells': 0, 'cells': 0}
    assert got['after'] == {'lives': 2, 'mode': 'spent', 'routeCells': 0, 'cleared': 0}
    assert got['lifted'] == {'mode': 'idle', 'down': False}
    assert got['events'][:3] == ['armed', 'start', 'hit'] and got['againClosed'] == 1


def test_a_patrol_flying_into_the_route_costs_a_life_at_the_step_it_touches(page):
    got = run(page, """const game = fresh([{ x: 60, y: 20, vx: -30, vy: 0 }]); const r = game.route;
      r.begin(40, 1); r.move(40, 40);                                  // a route from the top down to y=40, held
      let steps = 0; while (game.run.lives === 3 && steps < 400) { game.step(STEP); steps++; }
      return { steps, lives: game.run.lives, mode: r.mode, routeCells: count(game, ROUTE), x: game.level.patrols[0].x };""")
    # the patrol's edge meets the route's cells (x 40..40.5) when its centre is 1.35 from x = 40.5: after ~0.6 s
    assert got['lives'] == 2 and got['mode'] == 'spent' and got['routeCells'] == 0
    assert 70 <= got['steps'] <= 76 and got['x'] == pytest.approx(41.85, abs=0.3)


def test_the_hit_distance_is_the_patrol_radius_from_the_route_cell(page):
    """Route cells at x 30..30.5, patrol radius 1.35: touching starts at x = 31.85 exactly."""
    got = run(page, """const out = {};
      for (const [label, x] of [['clear', 31.87], ['touching', 31.83]]) {
        const game = fresh([{ x, y: 20 }]); const r = game.route;
        r.begin(30, 1); r.move(30, 40);                                                 // route down x = 30 to y = 40, drawn well away from the patrol's row... then check it
        const beforeStep = game.run.lives;                                              // drawing next to a patrol can hit at once, so measure after a step too
        game.step(STEP);
        out[label] = { beforeStep, lives: game.run.lives, mode: r.mode, routeCells: count(game, ROUTE) };
      }
      return out;""")
    assert got['clear'] == {'beforeStep': 3, 'lives': 3, 'mode': 'drawing', 'routeCells': 77}
    assert got['touching']['lives'] == 2 and got['touching']['mode'] == 'spent' and got['touching']['routeCells'] == 0


def test_d6c_a_patrol_is_never_left_inside_the_wall_a_route_becomes(page):
    """The prototype hit-tested a route 0.66 wide but built a wall up to 0.78 wide, so a patrol that a cut
    missed could finish embedded in the new wall, frozen. Now the route's cells are the wall's cells."""
    got = run(page, """const out = { cases: 0, survived: 0, hit: 0, embedded: [] };
      const lines = [[60, 60], [60, 63], [60, 70], [60, 80], [60, 100], [20, 90]];             // top x -> bottom x: 0 to 45 degrees
      for (const [xt, xb] of lines) {
        const L = Math.hypot(xb - xt, 70), nx = 70 / L, ny = -(xb - xt) / L;                    // unit normal, pointing right
        const mx = xt + (xb - xt) * 35 / 70;
        for (let d = 1.0; d <= 3.01; d += 0.1) {
          const game = fresh([{ x: mx + nx * d, y: 36 + ny * d }]);
          drag(game, [[xt, 1], [mx, 36], [xb, 71]]);
          out.cases++;
          if (game.run.lives < 3) { out.hit++; continue; }                                      // touched while drawing: a normal hit
          out.survived++;
          const p = game.level.patrols[0];
          if (game.grid.circleHitsSolid(p.x, p.y, p.r) || game.grid.get(Math.floor(p.x * 2), Math.floor(p.y * 2)) !== FIELD) out.embedded.push([xt, xb, +d.toFixed(1)]);
        }
      }
      return out;""")
    assert got['embedded'] == [], got['embedded']
    assert got['survived'] > 60 and got['hit'] > 10                                            # the sweep covers both outcomes


# ---- lifting, cancelling, interruptions ------------------------------------------------------------
def test_lifting_mid_field_erases_the_route_for_free(page):
    got = run(page, """const game = fresh([{ x: 100, y: 40 }]); const r = drag(game, [[40, 1], [40, 30]]);
      const before = count(game, ROUTE); r.end('lift');
      return { before, after: count(game, ROUTE), lives: game.run.lives, mode: r.mode, down: r.down, cleared: game.level.cleared, events: game.events };""")
    assert got['before'] == 57 and got['after'] == 0 and got['lives'] == 3
    assert got['mode'] == 'idle' and got['down'] is False and got['cleared'] == 0
    assert got['events'] == ['armed', 'start', 'cancel']


def test_a_pause_a_restart_or_a_win_erases_a_route_in_progress(page):
    got = run(page, """const out = {};
      let game = fresh([{ x: 100, y: 40 }]); drag(game, [[40, 1], [40, 30]]);
      game.pause('manual'); out.pause = { routeCells: count(game, ROUTE), mode: game.route.mode };
      game.resume(); game.route.move(40, 40); out.afterResume = { routeCells: count(game, ROUTE), mode: game.route.mode };   // the pointer is still down, but armed nothing
      game = fresh([{ x: 100, y: 40 }]); drag(game, [[40, 1], [40, 30]]);
      game.restartLevel(); out.restart = { routeCells: count(game, ROUTE), mode: game.route.mode, phase: game.phase };
      game = fresh([{ x: 100, y: 40 }]); drag(game, [[40, 1], [40, 30]]);
      game.crash(new Error('x')); out.crash = { routeCells: count(game, ROUTE), mode: game.route.mode };
      return out;""")
    assert got['pause'] == {'routeCells': 0, 'mode': 'idle'}
    assert got['afterResume'] == {'routeCells': 0, 'mode': 'idle'}
    assert got['restart'] == {'routeCells': 0, 'mode': 'idle', 'phase': 'playing'}
    assert got['crash'] == {'routeCells': 0, 'mode': 'idle'}


def test_armed_is_announced_when_a_touch_finds_safe_ground_and_not_when_a_route_merely_ends_on_it(page):
    """The tutorial's first step ("touch the edge") is driven by this event, so it must fire exactly then."""
    got = run(page, """const out = {};
      let game = fresh([{ x: 100, y: 40 }]);
      game.route.begin(40, 1); out.direct = [...game.events];                                       // straight onto the frame
      game = fresh([{ x: 100, y: 40 }]); game.route.begin(40, 3.0, 1.6); out.snapped = [...game.events];    // pulled onto it
      game = fresh([{ x: 100, y: 40 }]); game.route.begin(40, 30); game.route.move(40, 20); out.midField = [...game.events];   // a touch in the field: nothing yet
      game.route.move(40, 3); game.route.move(40, 1); out.reachedTheEdge = [...game.events];       // now it has found safe ground
      game = fresh([{ x: 100, y: 60 }]); const r = game.route; r.begin(40, 1); r.move(40, 30); r.move(40, 71);   // draw across: the closing re-arms silently
      out.closed = [...game.events]; out.mode = r.mode;
      game = fresh([{ x: 100, y: 60 }]); game.route.begin(60, 1); game.route.move(60, 2.6); game.route.move(60, 1.5);   // a jitter re-arms silently too
      out.jitter = [...game.events];
      game = fresh([{ x: 100, y: 60 }]); game.route.begin(60, 1); game.route.end('lift'); game.route.begin(60, 1); out.twice = [...game.events];   // a fresh touch arms again
      return out;""")
    assert got['direct'] == ['armed'] and got['snapped'][0] == 'armed'
    assert got['midField'] == ['edge-hint'] and got['reachedTheEdge'] == ['edge-hint', 'armed']
    assert got['closed'] == ['armed', 'start'] and got['mode'] == 'armed'
    assert got['jitter'] == ['armed', 'start', 'cancel']
    assert got['twice'] == ['armed', 'armed']


def test_begin_is_refused_outside_play(page):
    got = run(page, """const game = fresh(); game.pause('manual'); const paused = game.route.begin(40, 1);
      game.resume(); const game2 = new Game({ storage: createStorage(memoryBackend()) }); game2.enterTitle(); const title = game2.route.begin(40, 1);
      return { paused, title, down: game.route.down };""")
    assert got == {'paused': False, 'title': False, 'down': False}


# ---- starting: snapping, hints, floating pointers ----------------------------------------------------
def test_snapping_pulls_a_start_near_safe_ground_onto_it(page):
    got = run(page, """const out = {};
      let game = fresh([{ x: 100, y: 40 }]); let r = game.route;
      out.near = { armed: r.begin(40, 3.0, 1.6), mode: r.mode, anchor: { ...r.anchor }, cells: r.cells.length, routeCells: count(game, ROUTE) };   // 1 unit inside the field, snap 1.6
      game = fresh([{ x: 100, y: 40 }]); r = game.route;
      out.far = { armed: r.begin(40, 3.0, 0.5), mode: r.mode, down: r.down, cells: r.cells.length, events: game.events };                        // snap too small
      game = fresh([{ x: 100, y: 40 }]); r = game.route;
      out.middle = { armed: r.begin(40, 30, 1.6), mode: r.mode, events: game.events };
      return out;""")
    assert got['near']['armed'] is True and got['near']['mode'] == 'drawing'
    assert got['near']['anchor']['cy'] == 3 and got['near']['cells'] > 0            # the connecting segment from the frame to the pointer
    assert got['near']['cells'] == got['near']['routeCells']
    assert got['far'] == {'armed': False, 'mode': 'idle', 'down': True, 'cells': 0, 'events': ['edge-hint']}
    assert got['middle'] == {'armed': False, 'mode': 'idle', 'events': ['edge-hint']}


def test_a_touch_that_starts_in_the_field_arms_when_it_reaches_safe_ground(page):
    got = run(page, """const game = fresh([{ x: 100, y: 40 }]); const r = game.route;
      r.begin(40, 30); const start = r.mode; r.move(40, 15); const midway = { mode: r.mode, cells: r.cells.length };
      r.move(40, 1); const arrived = r.mode;                           // reached the frame: armed, nothing drawn
      r.move(40, 30); const drawing = { mode: r.mode, cells: r.cells.length };
      return { start, midway, arrived, drawing };""")
    assert got['start'] == 'idle' and got['midway'] == {'mode': 'idle', 'cells': 0} and got['arrived'] == 'armed'
    assert got['drawing']['mode'] == 'drawing' and got['drawing']['cells'] > 50


def test_pointer_positions_far_outside_the_board_are_harmless(page):
    got = run(page, """const out = {};
      let game = fresh([{ x: 100, y: 40 }]); let r = game.route; let t0 = performance.now();
      r.begin(40, 1); r.move(40, 5000);                                  // dragged miles below the board: clamped, closes on the frame
      out.below = { ms: performance.now() - t0, routes: game.level.routes.length, routeCells: count(game, ROUTE), phase: game.phase };
      game = fresh([{ x: 100, y: 40 }]); r = game.route; t0 = performance.now();
      r.begin(40, 1); r.move(9000, -9000); r.move(-9000, 9000); r.move(9000, 9000);
      out.wild = { ms: performance.now() - t0, agree: r.cells.length === count(game, ROUTE), phase: game.phase };
      return out;""")
    assert got['below']['ms'] < 250 and got['below']['routes'] == 1 and got['below']['routeCells'] == 0 and got['below']['phase'] == 'playing'
    assert got['wild']['ms'] < 250 and got['wild']['agree'] and got['wild']['phase'] in ('playing', 'over', 'clear')


def test_a_route_can_end_on_an_obstacle(page):
    got = run(page, """const game = fresh([{ x: 110, y: 40 }]); game.grid.fillRect(100, 60, 130, 80, BORDER);      // a block at x 50..65, y 30..40
      const r = drag(game, [[20, 1], [20, 35], [51, 35]]);                                                       // runs into its left face
      return { mode: r.mode, routes: game.level.routes.length, cleared: game.level.cleared };""")
    assert got['mode'] == 'armed' and got['routes'] == 1 and got['cleared'] > 0
