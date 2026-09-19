"""Patrol physics: does a patrol behave like a real disc? Tested against an analytic billiard model, against
mirror reflection off walls at many angles, against the conservation laws for collisions, and by running
hundreds of thousands of steps on random boards and checking that nothing ever goes wrong."""
import math

import pytest

PRELUDE = """
  const { Grid, FIELD, WALL, BORDER, walkCells } = await import('/js/grid.js');
  const P = await import('/js/physics.js');
  const { makePatrol, advance, collidePair, awayFromAxes, settle } = P;
  const { STEP, PATROL_RADIUS: R, MIN_BOUNCE_ANGLE } = await import('/js/config.js');
  const S = 2;
  const rngOf = (seed) => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const framed = () => { const g = new Grid(); g.frame(4); return g; };
  const polyline = (g, pts) => { g.set(Math.floor(pts[0][0] * S), Math.floor(pts[0][1] * S), WALL);
    for (let i = 1; i < pts.length; i++) walkCells(pts[i - 1][0] * S, pts[i - 1][1] * S, pts[i][0] * S, pts[i][1] * S, (cx, cy) => { g.set(cx, cy, WALL); }); };
  const region = (g, x, y) => {                                      // the open cells connected to (x, y)
    const seen = new Uint8Array(g.w * g.h), queue = [g.index(Math.floor(x * S), Math.floor(y * S))]; seen[queue[0]] = 1;
    for (let h = 0; h < queue.length; h++) { const i = queue[h], cx = i % g.w, cy = (i / g.w) | 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const nx = cx + dx, ny = cy + dy; if (nx < 0 || ny < 0 || nx >= g.w || ny >= g.h) continue;
        const j = ny * g.w + nx; if (!seen[j] && g.cells[j] === FIELD) { seen[j] = 1; queue.push(j); } } }
    return { seen, size: queue.length }; };
  const randomBoard = (seed) => {
    const rnd = rngOf(seed), g = framed();
    for (let k = 0, n = 2 + Math.floor(rnd() * 3); k < n; k++) { const pts = []; for (let i = 0, m = 2 + Math.floor(rnd() * 3); i < m; i++) pts.push([6 + rnd() * 108, 6 + rnd() * 60]); polyline(g, pts); }
    for (let k = 0; k < 3; k++) { const w = 5 + rnd() * 14, h = 4 + rnd() * 10, x = 10 + rnd() * 90, y = 8 + rnd() * 50; g.fillRect(Math.floor(x * S), Math.floor(y * S), Math.floor((x + w) * S), Math.floor((y + h) * S), k === 0 ? WALL : BORDER); }
    return { g, rnd };
  };
  const spawn = (g, rnd, speed) => {
    for (let t = 0; t < 4000; t++) { const x = 6 + rnd() * 108, y = 6 + rnd() * 60;
      if (g.circleHitsSolid(x, y, R + 0.5)) continue; const reg = region(g, x, y); if (reg.size < 3000) continue;
      const a = rnd() * Math.PI * 2; return { p: makePatrol(x, y, Math.cos(a) * speed, Math.sin(a) * speed), reg }; }
    return null; };
  const angleBetween = (ax, ay, bx, by) => Math.acos(Math.max(-1, Math.min(1, (ax * bx + ay * by) / (Math.hypot(ax, ay) * Math.hypot(bx, by))))) * 180 / Math.PI;
"""


@pytest.fixture
def page(open_page):
    return open_page()


def run(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


# ---- flat walls: exact -----------------------------------------------------------------------------
def test_a_disc_in_a_box_follows_the_exact_billiard_path(page):
    """Unfold the box: a disc bouncing between four walls moves like a free particle folded back into the box.
    The simulation must match that analytic path to floating-point precision, bounce after bounce."""
    got = run(page, """const rnd = rngOf(7), g = framed(); const lo = [2 + R, 2 + R], hi = [118 - R, 70 - R];
      const fold = (v, a, b) => { const w = b - a, u = ((v - a) % (2 * w) + 2 * w) % (2 * w); return a + (u <= w ? u : 2 * w - u); };
      let worst = 0, trials = 0, bounces = 0, skipped = 0;
      for (let n = 0; n < 150; n++) {
        const speed = 14 + rnd() * 12, a = rnd() * Math.PI * 2; const x0 = lo[0] + 3 + rnd() * (hi[0] - lo[0] - 6), y0 = lo[1] + 3 + rnd() * (hi[1] - lo[1] - 6);
        const vx = Math.cos(a) * speed, vy = Math.sin(a) * speed;
        // a path that passes within a step of a corner is a double bounce, which is not the analytic model: skip those
        let nearCorner = false; for (let t = 0; t <= 8; t += STEP) { const ux = x0 + vx * t, uy = y0 + vy * t;
          const fx = fold(ux, lo[0], hi[0]), fy = fold(uy, lo[1], hi[1]); if (Math.min(fx - lo[0], hi[0] - fx) < 0.5 && Math.min(fy - lo[1], hi[1] - fy) < 0.5) { nearCorner = true; break; } }
        if (nearCorner) { skipped++; continue; }
        const p = makePatrol(x0, y0, vx, vy); let t = 0;
        for (let i = 0; i < 8 * 120; i++) { bounces += advance([p], STEP, g, { minAngle: 0 }); t += STEP;
          const ex = fold(x0 + vx * t, lo[0], hi[0]), ey = fold(y0 + vy * t, lo[1], hi[1]); worst = Math.max(worst, Math.hypot(p.x - ex, p.y - ey)); }
        trials++;
      }
      return { worst, trials, bounces, skipped }; """)
    assert got['trials'] >= 100 and got['bounces'] > 300
    assert got['worst'] < 1e-6, got                                       # exact: the push-back is the mirror image of the overshoot


@pytest.mark.parametrize('label,line', [('vertical', [60, 2, 60, 70]), ('horizontal', [2, 36, 118, 36])])
def test_thin_axis_aligned_walls_mirror_exactly(page, label, line):
    got = run(page, """const g = framed(); polyline(g, [[arg[0], arg[1]], [arg[2], arg[3]]]); const rnd = rngOf(3);
      const vertical = arg[0] === arg[2]; const worst = []; let n = 0, tries = 0;
      while (n < 300 && tries++ < 100000) { const x = 6 + rnd() * 108, y = 6 + rnd() * 60; const side = vertical ? x - arg[0] : y - arg[1];
        if (Math.abs(side) < 6 || g.circleHitsSolid(x, y, R + 0.3)) continue;
        const a = rnd() * Math.PI * 2, dx = Math.cos(a), dy = Math.sin(a); if ((vertical ? dx * Math.sign(side) : dy * Math.sign(side)) > -0.25) continue;
        const along = vertical ? y : x; if (along < 10 || along > (vertical ? 62 : 110)) continue;
        const p = makePatrol(x, y, dx * 20, dy * 20); let b = 0, steps = 0; while (!b && steps++ < 4000) b = advance([p], STEP, g, { minAngle: 0 });
        const ideal = vertical ? [-dx * 20, dy * 20] : [dx * 20, -dy * 20];
        const near = vertical ? Math.abs(p.x - arg[0]) < 3 && p.y > 8 && p.y < 64 : Math.abs(p.y - arg[1]) < 3 && p.x > 8 && p.x < 112;
        if (!b || !near) continue; worst.push(angleBetween(p.vx, p.vy, ...ideal)); n++; }
      return { worst: Math.max(...worst), n }; """, line)
    assert got['n'] == 300 and got['worst'] < 1e-4, (label, got)          # degrees; below the ~1e-6 noise floor of measuring an angle with acos


# ---- any other angle: within a few degrees --------------------------------------------------------------
@pytest.mark.parametrize('label,line,thick,flip', [
    ('thin 45', [30, 2, 98, 70], False, False), ('thin 30', [20, 2, 100, 48.2], False, False), ('thin 60', [40, 2, 80, 71.3], False, False),
    ('thick 45', [30, 2, 98, 70], True, False), ('thick 30', [20, 2, 100, 48.2], True, False),
    ('thin 12', [10, 30, 110, 51], False, False), ('confined diagonal', [8, 10, 30, 70], False, True), ('confined vertical', [6.2, 2, 6.2, 70], False, True),
])
def test_walls_at_any_angle_reflect_like_mirrors(page, label, line, thick, flip):
    """The prototype turned every diagonal bounce by 90 degrees off the ideal. The staircase a freehand curve
    leaves is not a surface, so the normal is estimated from the wall around the contact."""
    got = run(page, """const [line, thick, flip] = arg; const g = framed(); polyline(g, [[line[0], line[1]], [line[2], line[3]]]);
      const L = Math.hypot(line[2] - line[0], line[3] - line[1]), tx = (line[2] - line[0]) / L, ty = (line[3] - line[1]) / L;
      let nx = -ty, ny = tx; if (nx > 0 || (nx === 0 && ny > 0)) { nx = -nx; ny = -ny; } if (flip) { nx = -nx; ny = -ny; }
      if (thick) for (let cy = 0; cy < g.h; cy++) for (let cx = 0; cx < g.w; cx++) if (((cx + 0.5) / S - line[0]) * nx + ((cy + 0.5) / S - line[1]) * ny < 0) g.set(cx, cy, WALL);
      const rnd = rngOf(11), errors = []; let tries = 0;
      while (errors.length < 300 && tries++ < 80000) {
        const x = 4 + rnd() * 112, y = 4 + rnd() * 64; const rel = (x - line[0]) * nx + (y - line[1]) * ny; if (rel < 6) continue;
        const along = (x - line[0]) * tx + (y - line[1]) * ty; if (along < 8 || along > L - 8) continue;
        const a = rnd() * Math.PI * 2, dx = Math.cos(a), dy = Math.sin(a); if (dx * nx + dy * ny > -0.25) continue;
        const p = makePatrol(x, y, dx * 20, dy * 20); if (g.circleHitsSolid(x, y, R + 0.3)) continue;
        const v0 = [p.vx, p.vy]; let b = 0, steps = 0; while (!b && steps++ < 4000) b = advance([p], STEP, g, { minAngle: 0 });
        if (!b) continue; const foot = (p.x - line[0]) * tx + (p.y - line[1]) * ty, dist = Math.abs((p.x - line[0]) * nx + (p.y - line[1]) * ny);
        if (dist > 3.2 || foot < 6 || foot > L - 6) continue;                                     // the frame or a corner got in the way
        const dot = v0[0] * nx + v0[1] * ny; errors.push(angleBetween(p.vx, p.vy, v0[0] - 2 * dot * nx, v0[1] - 2 * dot * ny)); }
      errors.sort((a, b) => a - b); return { n: errors.length, median: errors[Math.floor(errors.length / 2)], p90: errors[Math.floor(errors.length * 0.9)], max: errors[errors.length - 1] }; """,
              [line, thick, flip])
    assert got['n'] == 300, got
    assert got['median'] < 1.5 and got['p90'] < 3.5 and got['max'] < 4.5, (label, got)      # measured: median <= 1.1, max <= 2.8 degrees


# ---- patrols against each other -------------------------------------------------------------------
def test_pair_collisions_conserve_momentum_and_energy_and_always_separate(page):
    got = run(page, """const rnd = rngOf(5); let worstMomentum = 0, worstEnergy = 0, overlapAfter = 0, impulses = 0, gentle = 0;
      for (let n = 0; n < 2000; n++) {
        const a = makePatrol(50 + rnd() * 5, 30 + rnd() * 5, (rnd() - 0.5) * 60, (rnd() - 0.5) * 60), b = makePatrol(a.x + (rnd() - 0.5) * 2 * R * 1.9, a.y + (rnd() - 0.5) * 2 * R * 1.9, (rnd() - 0.5) * 60, (rnd() - 0.5) * 60);
        const dist = Math.hypot(b.x - a.x, b.y - a.y); if (dist >= 2 * R || dist < 1e-6) continue;
        const nx = (b.x - a.x) / dist, ny = (b.y - a.y) / dist, closing = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
        const px = a.vx + b.vx, py = a.vy + b.vy, e = a.vx ** 2 + a.vy ** 2 + b.vx ** 2 + b.vy ** 2;
        collidePair(a, b, 0, false);                                       // the raw elastic exchange, no speed governor
        worstMomentum = Math.max(worstMomentum, Math.hypot(a.vx + b.vx - px, a.vy + b.vy - py)); worstEnergy = Math.max(worstEnergy, Math.abs(a.vx ** 2 + a.vy ** 2 + b.vx ** 2 + b.vy ** 2 - e));
        overlapAfter = Math.max(overlapAfter, 2 * R - Math.hypot(b.x - a.x, b.y - a.y));
        if (closing > 0) { impulses++; const after = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny; if (Math.abs(after + closing) > 1e-9) gentle++; } }
      return { worstMomentum, worstEnergy, overlapAfter, impulses, wrongExchange: gentle }; """)
    assert got['impulses'] > 300
    assert got['worstMomentum'] < 1e-9 and got['worstEnergy'] < 1e-7
    assert got['overlapAfter'] < 1e-9                                       # always pushed apart to exactly touching
    assert got['wrongExchange'] == 0                                        # the normal approach speed reverses exactly


def test_d6b_patrols_bounce_off_each_other_instead_of_passing_through(page):
    got = run(page, """const g = framed(); const a = makePatrol(30, 36, 20, 0), b = makePatrol(90, 36, -20, 0);
      let minGap = 1e9, crossed = false, bounces = 0, first = null;
      for (let i = 0; i < 600; i++) { const n = advance([a, b], STEP, g, { minAngle: 0 }); bounces += n; minGap = Math.min(minGap, Math.hypot(a.x - b.x, a.y - b.y)); if (a.x > b.x) crossed = true; if (n && !first) first = [a.vx, b.vx]; }
      const glance = makePatrol(40, 30, 20, 0), other = makePatrol(60, 31.8, -20, 0); for (let i = 0; i < 200; i++) advance([glance, other], STEP, g);   // an off-centre hit
      return { minGap, crossed, first, glanceSpeeds: [Math.hypot(glance.vx, glance.vy), Math.hypot(other.vx, other.vy)], glanceTurned: [glance.vy !== 0, other.vy !== 0] }; """)
    assert got['minGap'] >= 2.7 - 1e-9 and got['crossed'] is False        # the prototype: minimum distance 0, and they crossed
    assert got['first'] == [-20, 20]                                       # head on: they swap velocities
    assert got['glanceSpeeds'] == pytest.approx([20, 20], abs=1e-9) and got['glanceTurned'] == [True, True]   # an off-centre hit deflects both, at unchanged speeds


def test_a_collision_that_would_stop_a_patrol_dead_sends_it_back_the_way_it_came(page):
    got = run(page, """const a = makePatrol(50, 36, 20, 0), b = makePatrol(50 + 2 * R - 0.05, 36, 0, 20);      // a runs into b's side: the exchange leaves a at rest
      collidePair(a, b, 0, true); return { a: [a.vx, a.vy], speed: Math.hypot(a.vx, a.vy), bSpeed: Math.hypot(b.vx, b.vy), b: [b.vx, b.vy] }; """)
    assert got['speed'] == pytest.approx(20, abs=1e-9) and got['bSpeed'] == pytest.approx(20, abs=1e-9)
    assert got['a'][0] == pytest.approx(-20) and got['a'][1] == pytest.approx(0, abs=1e-9)   # it rebounds along the line of centres, away from b
    assert got['b'][0] > 0 and got['b'][1] > 0                                                # b takes the momentum


# ---- speed, walls, tunnelling ------------------------------------------------------------------------
def test_speed_is_constant_and_patrols_never_enter_walls_on_random_boards(page):
    """Six random boards (thin walls at random angles, blocks, a claimed region), three patrols each, 40,000
    steps a patrol: the speed never drifts, nothing is ever inside a wall, nothing crosses one."""
    got = run(page, """P.stats.passes.fill(0); const problems = []; let steps = 0, bounces = 0, worstOverlap = 0, worstSpeedDrift = 0, boards = 0, shallow = 0, deep = 0;
      for (let seed = 1; seed <= 6; seed++) {
        const { g, rnd } = randomBoard(seed * 101); const speeds = [14, 20, 26]; const patrols = [], regions = [];
        for (let i = 0; i < 3; i++) { const s = spawn(g, rnd, speeds[i]); if (s && patrols.every((q) => Math.hypot(q.x - s.p.x, q.y - s.p.y) > 2 * R + 1)) { patrols.push(s.p); regions.push(s.reg); } }
        if (!patrols.length) continue; boards++;
        for (let i = 0; i < 40000; i++) {
          bounces += advance(patrols, STEP, g); steps++;
          for (let k = 0; k < patrols.length; k++) { const p = patrols[k];
            if (!Number.isFinite(p.x + p.y + p.vx + p.vy)) { problems.push(`seed ${seed}: not finite`); i = 1e9; break; }
            worstSpeedDrift = Math.max(worstSpeedDrift, Math.abs(Math.hypot(p.vx, p.vy) - p.speed));
            const idx = Math.floor(p.y * S) * g.w + Math.floor(p.x * S);
            if (!regions[k].seen[idx]) { problems.push(`seed ${seed}: patrol ${k} left its region at step ${i}`); i = 1e9; break; }
            if (g.circleHitsSolid(p.x, p.y, R - 0.001)) { shallow++; let lo = 0.001, hi = R; for (let b = 0; b < 30; b++) { const mid = (lo + hi) / 2; if (g.circleHitsSolid(p.x, p.y, R - mid)) lo = mid; else hi = mid; } worstOverlap = Math.max(worstOverlap, lo); if (lo > 0.02) deep++; } } } }
      return { problems: problems.slice(0, 4), boards, steps, bounces, shallow, deep, worstOverlap, worstSpeedDrift, passes: P.stats.passes.slice() }; """)
    assert got['problems'] == [] and got['boards'] >= 5 and got['bounces'] > 500
    assert got['worstSpeedDrift'] < 1e-9
    # A patrol can be wedged in a throat about as narrow as its own diameter, where no position clears both
    # walls at once: then it ends a step a hair inside one. That must be rare and tiny, and never deeper than
    # a fiftieth of a unit (a tenth of a cell).
    assert got['deep'] == 0 and got['shallow'] <= 8, got
    # Ordinary contacts clear in one pass (measured: 6033 of 6054, none in 3-11). Pushing along the fitted
    # normal by the plain overlap instead of overlap / cos(angle) needs 4-11 passes for ~90 of them and
    # runs into the cap for ~170; only wedge throats should reach it.
    passes = got['passes']
    assert passes[1] > 1000 and sum(passes[3:12]) <= 2 and passes[12] <= 40, passes


def test_nothing_tunnels_through_a_one_cell_wall_at_absurd_speeds(page):
    got = run(page, """const bad = []; const rnd = rngOf(9);
      for (const speed of [26, 60, 120, 240, 600, 1200]) {
        const g = framed(); polyline(g, [[60, 2], [60, 70]]);                         // one cell thick
        for (let n = 0; n < 60; n++) { const x = 30 + rnd() * 20, y = 12 + rnd() * 48, a = (rnd() - 0.5) * 1.2; const p = makePatrol(x, y, Math.cos(a) * speed, Math.sin(a) * speed);
          for (let i = 0; i < 600; i++) { advance([p], STEP, g, { minAngle: 0 }); if (p.x > 60) { bad.push(`speed ${speed}: crossed`); break; } if (p.x < 2 || p.y < 2 || p.y > 70) { bad.push(`speed ${speed}: escaped the board`); break; } } } }
      return { bad: bad.slice(0, 4), count: bad.length }; """)
    assert got['count'] == 0, got['bad']


def test_a_step_is_made_of_the_fewest_sub_steps_that_keep_each_under_a_quarter_radius(page):
    got = run(page, """const g = framed(); const rows = [];
      for (const speed of [14, 26, 60, 120, 400]) { const p = makePatrol(60, 36, speed, 0); const before = p.x; P.stats.substeps = 0; advance([p], STEP, g, { minAngle: 0 });
        rows.push({ speed, moved: p.x - before, substeps: P.stats.substeps }); }
      return rows; """)
    for row in got:
        assert row['moved'] == pytest.approx(row['speed'] / 120, abs=1e-9)          # exactly one step of travel...
        assert row['substeps'] == max(1, math.ceil(row['speed'] / 120 / (0.25 * 1.35)))    # ...in ceil(travel / quarter-radius) sub-steps


# ---- the minimum angle ---------------------------------------------------------------------------------
def test_awayFromAxes_turns_near_axis_directions_to_exactly_twelve_degrees(page):
    got = run(page, """const lo = Math.sin(MIN_BOUNCE_ANGLE); const rnd = rngOf(21); const out = { badLength: 0, changedFine: 0, tooClose: 0, notAtLimit: 0, checked: 0 }; const t = { x: 0, y: 0 };
      for (let i = 0; i < 4000; i++) { const a = rnd() * Math.PI * 2, ux = Math.cos(a), uy = Math.sin(a); awayFromAxes(ux, uy, MIN_BOUNCE_ANGLE, 1, 1, t); out.checked++;
        if (Math.abs(Math.hypot(t.x, t.y) - 1) > 1e-12) out.badLength++;
        if (Math.abs(t.x) < lo - 1e-12 || Math.abs(t.y) < lo - 1e-12) out.tooClose++;
        const fine = Math.abs(ux) >= lo && Math.abs(uy) >= lo; if (fine && (t.x !== ux || t.y !== uy)) out.changedFine++;
        if (!fine && Math.abs(Math.min(Math.abs(t.x), Math.abs(t.y)) - lo) > 1e-12) out.notAtLimit++; }
      const exact = []; for (const [ux, uy, bx, by] of [[1, 0, 1, 1], [1, 0, 1, -1], [-1, 0, 1, 1], [0, 1, 1, 1], [0, -1, -1, 1], [0, 1, -1, 1]]) { awayFromAxes(ux, uy, MIN_BOUNCE_ANGLE, bx, by, t); exact.push([Math.sign(t.x), Math.sign(t.y)]); }
      return { out, exact, degrees: MIN_BOUNCE_ANGLE * 180 / Math.PI }; """)
    assert got['degrees'] == pytest.approx(12)
    assert got['out']['badLength'] == 0 and got['out']['tooClose'] == 0 and got['out']['changedFine'] == 0 and got['out']['notAtLimit'] == 0
    assert got['exact'] == [[1, 1], [1, -1], [-1, 1], [1, 1], [-1, -1], [-1, 1]]      # an exactly-zero component turns the way the bias points


def test_the_guard_breaks_an_endless_horizontal_shuttle_that_otherwise_persists(page):
    got = run(page, """const g = framed(); polyline(g, [[100, 2], [100, 70]]);                       // two vertical walls: the frame's left side and this one
      const run1 = (minAngle) => { const p = makePatrol(50, 36, 20, 0); const angles = []; let last = null;
        for (let i = 0; i < 120 * 30; i++) { const b = advance([p], STEP, g, { minAngle }); if (b) { angles.push([Math.abs(p.vy) / p.speed, Math.abs(p.vx) / p.speed]); } last = p; } return { angles, vy: last.vy }; };
      const guarded = run1(MIN_BOUNCE_ANGLE), free = run1(0); const lo = Math.sin(MIN_BOUNCE_ANGLE);
      return { guardedBounces: guarded.angles.length, everyBounceOffAxes: guarded.angles.every(([ay, ax]) => ay >= lo - 1e-9 && ax >= lo - 1e-9), freeBounces: free.angles.length, freeVy: free.vy, lo }; """)
    assert got['guardedBounces'] >= 5 and got['everyBounceOffAxes']
    assert got['freeBounces'] >= 5 and got['freeVy'] == 0                    # without the guard the shuttle never leaves the horizontal


def test_level_spawns_are_never_axis_aligned(page):
    got = page.evaluate("""async () => { const { Grid } = await import('/js/grid.js'); const { buildLevel } = await import('/js/level.js'); const { MIN_BOUNCE_ANGLE } = await import('/js/config.js');
      const lo = Math.sin(MIN_BOUNCE_ANGLE) - 1e-9; let bad = 0, total = 0;
      for (let s = 0; s < 60; s++) for (let n = 1; n <= 14; n++) { const lvl = buildLevel(n, 'spawn' + s, new Grid()); for (const p of lvl.patrols) { total++; if (Math.abs(p.vx) / p.speed < lo || Math.abs(p.vy) / p.speed < lo) bad++; } }
      return { bad, total }; }""")
    assert got['bad'] == 0 and got['total'] > 1000


# ---- drawing the sprite, determinism, cost -----------------------------------------------------------
def test_the_drawn_heading_eases_towards_the_velocity_instead_of_snapping(page):
    got = run(page, """const g = framed(); const p = makePatrol(60, 36, 20, 0); p.vx = -20; p.vy = 0.0001;               // turned right round in one instant
      const t0 = p.heading; const seen = []; for (let i = 0; i < 120; i++) { advance([p], STEP, g, { minAngle: 0 }); seen.push(p.heading); }
      const stationary = makePatrol(60, 36, 0, 0); stationary.heading = 1.234; for (let i = 0; i < 50; i++) advance([stationary], STEP, g);
      const target = Math.atan2(p.vy, p.vx); const wrap = (d) => d - Math.PI * 2 * Math.round(d / (Math.PI * 2));
      return { start: t0, after70ms: seen[Math.round(0.07 / STEP) - 1], after1s: seen[seen.length - 1], target, monotone: seen.every((h, i) => i === 0 || Math.abs(wrap(target - h)) <= Math.abs(wrap(target - seen[i - 1])) + 1e-12),
               biggestJump: Math.max(...seen.map((h, i) => Math.abs(wrap(h - (i ? seen[i - 1] : t0))))), stationary: stationary.heading }; """)
    remaining_at_70ms = abs(((got['target'] - got['after70ms'] + 3.14159265) % 6.2831853) - 3.14159265) / 3.14159265
    assert got['monotone'] and got['biggestJump'] < 0.15 * 3.1416             # smooth: the first step covers at most 12 % of a half turn, never all of it
    assert 0.30 < remaining_at_70ms < 0.45                                    # about 37 % of the turn left after one time constant
    assert abs(((got['target'] - got['after1s'] + 3.14159265) % 6.2831853) - 3.14159265) < 0.02
    assert got['stationary'] == 1.234                                         # a patrol at rest keeps its heading


def test_physics_is_deterministic(page):
    got = run(page, """const trace = () => { const { g, rnd } = randomBoard(404); const ps = []; for (let i = 0; i < 3; i++) { const s = spawn(g, rnd, 20); if (s) ps.push(s.p); }
        let sum = 0; for (let i = 0; i < 20000; i++) { advance(ps, STEP, g); for (const p of ps) sum = (sum * 31 + p.x * 1000 + p.y * 7) % 1e9; } return [sum, ps.map((p) => [p.x, p.y, p.vx, p.vy])]; };
      return { a: trace(), b: trace() }; """)
    assert got['a'] == got['b']


def test_advance_is_cheap_enough_for_a_phone(page):
    got = run(page, """const { g, rnd } = randomBoard(77); const ps = []; for (let i = 0; i < 6; i++) { const s = spawn(g, rnd, 26); if (s) ps.push(s.p); }
      for (let i = 0; i < 2000; i++) advance(ps, STEP, g); const t0 = performance.now(); const N = 20000; for (let i = 0; i < N; i++) advance(ps, STEP, g);
      return { patrols: ps.length, msPerStep: (performance.now() - t0) / N }; """)
    assert got['patrols'] >= 3
    assert got['msPerStep'] < 0.4, got                    # a 60 fps frame runs 2 steps; the whole frame budget is 16 ms


# ---- after a capture ---------------------------------------------------------------------------------------
def test_settle_moves_a_patrol_clear_of_a_wall_that_appears_on_it(page):
    got = run(page, """const g = framed(); const p = makePatrol(60, 36, 20, 0); g.fillRect(Math.floor(60 * S), 60, Math.floor(70 * S), 90, WALL);      // a wall lands on the patrol's right side
      const before = g.circleHitsSolid(p.x, p.y, p.r); settle([p], g);
      return { before, after: g.circleHitsSolid(p.x, p.y, p.r - 1e-6), vx: p.vx, x: p.x }; """)
    assert got['before'] is True and got['after'] is False
    assert got['vx'] < 0 and got['x'] < 60                                    # pushed out, and turned away from the wall
