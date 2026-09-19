"""Power-ups: when a pickup appears and where, how it is taken, what freeze, shield and slow each do, that their timers
run on the game clock, that they are saved and shown, and that none of it can hurt the rest of the game."""
import re

import pytest

DESKTOP = {'width': 1280, 'height': 800}

PIXEL = """([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
  const s = document.createElement('canvas'); s.width = s.height = 1; const g = s.getContext('2d', { willReadFrequently: true });
  g.drawImage(c, Math.round((x - r.left) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1); return Array.from(g.getImageData(0, 0, 1, 1).data); }"""


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def level3(page, seed, patrols='[{ x: 110, y: 64 }]'):
    """A level with power-ups, one parked patrol, and the simulation held still (steps are taken by hand)."""
    page.evaluate(f'__pp.game.newRun({{ seed: "{seed}" }}); __pp.game.startLevel(3); __pp.setPatrols({patrols}); __pp.freeze(true)')


def look(page, x, y):
    """The colour on the canvas at a board point, after a fresh draw."""
    page.evaluate('__pp.renderer.invalidate()')
    frame(page)
    return page.evaluate(PIXEL, list(page.evaluate(f'(({{ x, y }}) => [x, y])(__pp.toClient({x}, {y}))')))

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage } = await import('/js/storage.js');
  const { Grid, FIELD, WALL, ROUTE } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { STEP, levelInfo, SNAPSHOT_KEY } = await import('/js/config.js');
  const { POWER } = await import('/js/powerups.js');
  const { eventRng } = await import('/js/rng.js');
  const backendOf = (initial = {}) => { const map = new Map(Object.entries(initial));
    return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: (k) => { map.delete(k); } }; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  /* A game on `level` (3 has power-ups and no tracers) with these patrols ([x, y, vx, vy]) and a log of power events. */
  const setup = (level = 3, patrols = [[110, 64, 0, 0]], seed = 'power', backend = backendOf()) => {
    const game = new Game({ storage: createStorage(backend) }); game.enterTitle(); game.newRun({ seed }); game.startLevel(level);
    game.level.patrols.length = 0; for (const [x, y, vx, vy] of patrols) game.level.patrols.push(makePatrol(x, y, vx || 0, vy || 0));
    game.log = []; game.on('power', (e) => game.log.push([e.type, e.kind, +game.clock.now.toFixed(3), e.x === undefined ? null : +e.x.toFixed(6), e.y === undefined ? null : +e.y.toFixed(6)]));
    return game; };
  const colCells = (game, unitX) => { const g = game.grid, x = Math.floor(unitX * 2), cells = []; for (let y = 0; y < g.h; y++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); return cells; };
  const pos = (game) => JSON.stringify(game.level.patrols.map((p) => [p.x, p.y]));
  const clearObstacles = (game) => { for (const o of game.level.obstacles) game.grid.fillRect(o.x * 2, o.y * 2, (o.x + o.w) * 2, (o.y + o.h) * 2, FIELD); };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "\n}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- when and where ---------------------------------------------------------------------------------------------------------
def test_pickups_start_at_level_three_and_appear_every_12_to_20_seconds_lasting_10(page):
    got = js(page, """
      const out = { early: {} };
      for (const level of [1, 2]) { const g = setup(level); run(g, 60); out.early[level] = [g.powerups.enabled, g.log.length, g.powerups.pickup]; }
      const g = setup(3, [[110, 64, 0, 0]], 'schedule'); run(g, 130);
      const spawns = g.log.filter((e) => e[0] === 'spawn').map((e) => e[2]), expires = g.log.filter((e) => e[0] === 'expire').map((e) => e[2]);
      let maxAtOnce = 0; const g2 = setup(3, [[110, 64, 0, 0]], 'schedule'); for (let i = 0; i < 130 * 120; i++) { g2.step(STEP); maxAtOnce = Math.max(maxAtOnce, g2.powerups.pickup ? 1 : 0); }
      return { ...out, first: spawns[0], gaps: spawns.slice(1).map((t, i) => +(t - spawns[i]).toFixed(3)), lives: expires.map((t, i) => +(t - spawns[i]).toFixed(3)), count: spawns.length, maxAtOnce };""")
    assert got['early'] == {'1': [False, 0, None], '2': [False, 0, None]}                # none before level 3
    assert 12 <= got['first'] <= 20 and got['count'] >= 6
    assert all(12 <= gap <= 20.001 for gap in got['gaps'])                                # 12-20 s between appearances
    assert all(life == pytest.approx(10, abs=0.02) for life in got['lives'])              # each waits exactly 10 s if nobody takes it
    assert got['maxAtOnce'] == 1


def test_kinds_and_timings_are_the_same_for_everyone_whatever_they_do_on_the_board(page):
    got = js(page, """
      const schedule = (game, seconds) => { run(game, seconds); return game.log.filter((e) => e[0] === 'spawn').map((e) => [e[1], e[2]]); };
      const idle = setup(5, [[110, 64, 0, 0]], 'daily-2026'); const a = schedule(idle, 100);
      const busy = setup(5, [[110, 64, 0, 0]], 'daily-2026');                        // the same board, but this player keeps cutting it up
      let b = []; for (let i = 0; i < 100 * 120; i++) { busy.step(STEP); if (i % 1400 === 0 && i) { busy.commitCapture(colCells(busy, 10 + (i / 1400) * 6)); } if (busy.phase !== 'playing') break; }
      b = busy.log.filter((e) => e[0] === 'spawn').map((e) => [e[1], e[2]]);
      const kinds = new Set(); for (let i = 0; i < 40; i++) { const g = setup(5, [[110, 64, 0, 0]], 'k' + i); run(g, 25); for (const e of g.log) if (e[0] === 'spawn') kinds.add(e[1]); }
      const firsts = new Set(); for (let i = 0; i < 12; i++) { const g = setup(5, [[110, 64, 0, 0]], 'f' + i); firsts.add(+g.powerups.nextAt.toFixed(4)); }
      return { a, b, kinds: [...kinds].sort(), distinctFirstTimes: firsts.size };""")
    n = min(len(got['a']), len(got['b']))
    assert n >= 3 and got['a'][:n] == got['b'][:n]                                        # same kinds at the same times, however the board was played
    assert got['kinds'] == ['freeze', 'shield', 'slow'] and got['distinctFirstTimes'] > 8


def test_a_pickup_appears_on_open_ground_clear_of_walls_patrols_and_tracers(page):
    """Two thousand or so spawns on boards with obstacles, a claimed strip, parked patrols and crawling tracers (each forced by
    calling the next one due now), judged at the moment each appears against the numbers themselves: 3 units from a wall,
    12 from a patrol, 8 from a tracer. (Reading the limits from the module would let a changed limit pass its own test.)
    They must also come close to those limits, or the rules would be stricter than intended."""
    got = js(page, """
      const distanceToSolid = (g, x, y) => { let lo = 0, hi = 8; for (let k = 0; k < 24; k++) { const m = (lo + hi) / 2; if (g.grid.circleHitsSolid(x, y, m)) hi = m; else lo = m; } return lo; };
      const bad = new Set(); let spawns = 0; const nearest = { wall: 99, patrol: 99, tracer: 99 };
      for (let i = 0; i < 8; i++) {
        const level = [3, 4, 6, 7, 8, 10, 12, 15][i]; const g = setup(level, [[100, 60, 0, 0], [30, 50, 0, 0]], 'where' + i);
        g.commitCapture(colCells(g, 8 + (i % 4) * 3));                                    // some ground already claimed
        if (g.phase !== 'playing') continue;
        g.on('power', (e) => {                                                             // judged at the moment it appears: tracers move on afterwards
          if (e.type !== 'spawn') return; spawns++;
          if (g.grid.get(Math.floor(e.x * 2), Math.floor(e.y * 2)) !== FIELD) bad.add('not on open ground');
          const wall = distanceToSolid(g, e.x, e.y); nearest.wall = Math.min(nearest.wall, wall); if (wall < 3 - 1e-4) bad.add('too close to a wall');
          for (const q of g.level.patrols) { const d = Math.hypot(q.x - e.x, q.y - e.y); nearest.patrol = Math.min(nearest.patrol, d); if (d < 12) bad.add('too close to a patrol'); }
          for (const t of g.tracers.list) { const d = Math.hypot(t.x - e.x, t.y - e.y); nearest.tracer = Math.min(nearest.tracer, d); if (d < 8) bad.add('too close to a tracer'); }
        });
        for (let k = 0; k < 300; k++) { g.powerups.pickup = null; g.powerups.nextAt = g.clock.now; g.step(STEP); }
      }
      return { bad: [...bad], spawns, nearest };""")
    assert got['bad'] == [] and got['spawns'] > 2000
    assert got['nearest']['wall'] < 3.5 and got['nearest']['patrol'] < 13 and got['nearest']['tracer'] < 9.5, got['nearest']     # and they do come right up to the limits


def test_when_there_is_nowhere_suitable_it_tries_again_later_instead_of_stalling(page):
    got = js(page, """
      const g = setup(3, [[110, 64, 0, 0]], 'nowhere');
      const grid = g.grid; for (let i = 0; i < grid.cells.length; i++) if (grid.cells[i] === FIELD && (i % grid.w) < 236 && (i % grid.w) > 8) grid.cells[i] = WALL;   // almost everything claimed
      g.level.patrols.length = 0; g.level.patrols.push(makePatrol(118, 6, 0, 0));
      const at = g.powerups.nextAt; run(g, at + 0.1);
      const first = { pickup: g.powerups.pickup, retryAt: +(g.powerups.nextAt - g.clock.now).toFixed(3) };
      for (let y = 0; y < grid.h; y++) for (let x = 9; x < 235; x++) if (grid.get(x, y) === WALL && y > 8 && y < 136) grid.set(x, y, FIELD);       // open it up again
      run(g, 2.2);
      return { first, appeared: !!g.powerups.pickup };""")
    assert got['first']['pickup'] is None and 1.5 < got['first']['retryAt'] <= 2.0        # nowhere to put it: try again in 2 s
    assert got['appeared'] is True


# ---- taking one ---------------------------------------------------------------------------------------------------------------
def test_drawing_through_a_pickup_takes_it_even_in_one_fast_swipe_but_passing_beside_it_does_not(page):
    got = js(page, """
      const out = {};
      let g = setup(3); g.powerups.place('shield', 40, 36);
      g.route.begin(40, 1); g.route.move(40, 71);                                       // one pointer event from the top edge to the bottom
      out.fast = { kind: g.powerups.pickup, active: g.powerups.active('shield'), log: g.log.map((e) => e[0] + ':' + e[1]) };
      g = setup(3); g.powerups.place('freeze', 40, 36);
      g.route.begin(37.4, 1); g.route.move(37.4, 71);                                   // 2.6 units to the side: outside the 1.8 radius
      out.beside = { still: !!g.powerups.pickup, active: g.powerups.active('freeze') };
      g = setup(3); g.powerups.place('slow', 40, 36);
      g.route.begin(38.5, 1); g.route.move(38.5, 30);                                   // 1.5 units to the side, stopping short of it: the cells laid so far are not near enough
      out.stopsShort = !!g.powerups.pickup; g.route.move(38.5, 34.9);
      out.reaches = { taken: !g.powerups.pickup, active: g.powerups.active('slow') };
      return out;""")
    assert got['fast']['kind'] is None and got['fast']['active'] is True and got['fast']['log'] == ['start:shield']
    assert got['beside'] == {'still': True, 'active': False}
    assert got['stopsShort'] is True and got['reaches'] == {'taken': True, 'active': True}


def test_claiming_the_ground_a_pickup_sits_on_takes_it_and_leaving_it_does_not(page):
    got = js(page, """
      const out = {};
      let g = setup(3); g.powerups.place('slow', 20, 36);
      g.commitCapture(colCells(g, 40)); out.swallowed = { taken: !g.powerups.pickup, active: g.powerups.active('slow') };      // the left side is claimed, pickup and all
      g = setup(3); g.powerups.place('slow', 80, 36);
      g.commitCapture(colCells(g, 40)); out.left = { still: !!g.powerups.pickup, active: g.powerups.active('slow') };            // it is on the patrol's side: left alone
      return out;""")
    assert got['swallowed'] == {'taken': True, 'active': True} and got['left'] == {'still': True, 'active': False}


def test_patrols_cannot_take_pickups_and_an_untaken_pickup_expires_after_ten_seconds(page):
    got = js(page, """
      const g = setup(3, [[60, 20, 0, 0]]); g.powerups.place('freeze', 60, 20);         // right under a parked patrol
      run(g, 9.9); const before = !!g.powerups.pickup; run(g, 0.2);
      return { before, after: !!g.powerups.pickup, active: g.powerups.active('freeze'), log: g.log.map((e) => e[0]) };""")
    assert got['before'] is True and got['after'] is False and got['active'] is False and got['log'] == ['expire']


def test_taking_the_same_kind_again_refreshes_it_rather_than_stacking(page):
    got = js(page, """
      const g = setup(3, [[110, 64, 0, 0]]);
      g.powerups.place('shield', 40, 36); g.route.begin(40, 1); g.route.move(40, 40); const first = g.powerups.remaining('shield');
      run(g, 2); const later = g.powerups.remaining('shield');
      g.powerups.place('shield', 40, 46); g.route.move(40, 50); const again = g.powerups.remaining('shield');
      return { first, later, again };""")
    assert got['first'] == pytest.approx(5) and got['later'] == pytest.approx(3, abs=0.01) and got['again'] == pytest.approx(5)      # back to a full 5 s, not 8


# ---- the three effects -----------------------------------------------------------------------------------------------------------
def test_freeze_stops_patrols_and_tracers_for_three_seconds_and_a_frozen_patrol_still_hurts(page):
    got = js(page, """
      const g = setup(7, [[100, 40, 7, 5]]);                                              // level 7 has tracers
      g.powerups.until.freeze = g.clock.now + POWER.freeze;
      const patrolAt = pos(g), tracerAt = JSON.stringify(g.tracers.list.map((t) => [t.x, t.y]));
      run(g, 2.9); const stillFrozen = pos(g) === patrolAt && JSON.stringify(g.tracers.list.map((t) => [t.x, t.y])) === tracerAt;
      run(g, 0.3); const movedAfter = pos(g) !== patrolAt && JSON.stringify(g.tracers.list.map((t) => [t.x, t.y])) !== tracerAt;
      const h = setup(3, [[60, 30, 0, 0]]); h.powerups.until.freeze = h.clock.now + 3;
      h.route.begin(60, 1); h.route.move(60, 29.5);                                       // drawn straight into the frozen patrol (radius 1.35 at y = 30)
      return { stillFrozen, movedAfter, hurts: h.run.lives, ended: g.log.map((e) => e[0] + ':' + e[1]) };""")
    assert got['stillFrozen'] is True and got['movedAfter'] is True
    assert got['hurts'] == 2 and got['ended'] == ['end:freeze']                         # a route drawn onto a frozen patrol still costs a life


def test_a_frozen_patrol_is_drawn_where_it_stands_and_does_not_shimmer_between_two_steps(page):
    got = js(page, """
      const g = setup(3, [[60, 36, 8, 6]]); run(g, 0.5);                                   // moving, so its previous position differs from its position
      const p = g.level.patrols[0]; const moving = p.px !== p.x;
      g.powerups.until.freeze = g.clock.now + 3; g.step(STEP);
      return { moving, still: p.px === p.x && p.py === p.y };""")
    assert got['moving'] is True and got['still'] is True       # the renderer blends the previous and current positions: they must be one and the same


def test_a_frozen_tracer_neither_chases_nor_catches_and_thaws_to_do_both_afterwards(page):
    got = js(page, """
      const g = setup(4, [[110, 64, 0, 0]]); g.tracers.place([{ x: 40, y: 2, dir: -1 }]); const chases = [];
      g.on('tracer', (e) => chases.push([e.type, +g.clock.now.toFixed(2)]));
      g.powerups.until.freeze = g.clock.now + 3;
      g.route.begin(40, 1); g.route.move(40, 3);                                         // the route starts right where the tracer stands
      for (let i = 0; i < 2.5 * 120; i++) { g.route.move(40, 3 + i * 0.001); g.step(STEP); }       // an almost stationary tip for 2.5 s: as good as caught, if it could move
      const during = { lives: g.run.lives, mode: g.route.mode, tracerMode: g.tracers.list[0].mode, events: chases.length };
      let caught = false; for (let i = 0; i < 2 * 120 && !caught; i++) { g.route.move(40, 3.3 + i * 0.0005); g.step(STEP); caught = g.run.lives < 3; }
      return { during, caughtAfter: caught, events: chases.map((c) => c[0]) };""")
    assert got['during'] == {'lives': 3, 'mode': 'drawing', 'tracerMode': 'patrol', 'events': 0}      # not even a warning while it is frozen
    assert got['caughtAfter'] is True and got['events'] == ['chase', 'caught']


def test_slow_halves_the_speed_of_patrols_for_five_seconds_and_leaves_tracers_alone(page):
    got = js(page, """
      const dist = (game, seconds) => { const p = game.level.patrols[0], x0 = p.x, y0 = p.y; run(game, seconds); return Math.hypot(p.x - x0, p.y - y0); };
      const normal = setup(7, [[60, 36, 8, 6]]), slowed = setup(7, [[60, 36, 8, 6]]);
      slowed.powerups.until.slow = slowed.clock.now + POWER.slow;
      const tracerDist = (game) => { const t = game.tracers.list[0], x0 = t.t; return () => Math.abs(t.t - x0); };
      const tn = tracerDist(normal), ts = tracerDist(slowed);
      const a = dist(normal, 1), b = dist(slowed, 1);
      const after = setup(3, [[60, 36, 8, 6]]); after.powerups.until.slow = after.clock.now + 5; run(after, 5.05); const p = after.level.patrols[0]; const x0 = p.x, y0 = p.y; run(after, 1);
      return { ratio: b / a, tracerSame: tn() === ts(), full: Math.hypot(p.x - x0, p.y - y0) / a, ended: after.log.map((e) => e[0] + ':' + e[1]) };""")
    assert got['ratio'] == pytest.approx(0.5, abs=0.02) and got['tracerSame'] is True      # half the distance, tracers unchanged
    assert got['full'] == pytest.approx(1, abs=0.05) and got['ended'] == ['end:slow']       # and back to full speed after 5 s


def test_freeze_beats_slow_and_slow_carries_on_after_it(page):
    got = js(page, """
      const g = setup(3, [[60, 36, 8, 6]]); g.powerups.until.slow = g.clock.now + 5; g.powerups.until.freeze = g.clock.now + 3;
      const p = g.level.patrols[0]; const at = pos(g); run(g, 2.9); const frozen = pos(g) === at;
      run(g, 0.1); const x1 = p.x, y1 = p.y; run(g, 1); const slowed = Math.hypot(p.x - x1, p.y - y1);
      return { frozen, slowedSpeed: slowed / 10 };""")
    assert got['frozen'] is True and got['slowedSpeed'] == pytest.approx(0.5, abs=0.03)     # 10 u/s patrol, at half speed once the freeze is over


def test_a_shielded_route_earns_no_close_calls_because_nothing_can_hurt_it(page):
    got = js(page, """
      const pass = (shielded) => { const g = setup(3, [[43.5, 10, 0, 9]]);                    // a patrol running down the route's side, 3 units off: a near miss
        if (shielded) g.powerups.until.shield = g.clock.now + 5;
        const events = []; g.on('route', (e) => { if (e.type === 'closecall') events.push(e); });
        g.route.begin(40, 1); g.route.move(40, 45); run(g, 1); return { events: events.length, remembered: g.route.closeCalls.size, lives: g.run.lives }; };
      return { bare: pass(false), shielded: pass(true) };""")
    assert got['bare'] == {'events': 1, 'remembered': 1, 'lives': 3}                          # unprotected, that is a close call (banked when the route closes)
    assert got['shielded'] == {'events': 0, 'remembered': 0, 'lives': 3}                      # protected, it is nothing


def test_shield_makes_the_route_solid_so_a_patrol_bounces_off_it_instead_of_hurting_it(page):
    got = js(page, """
      const flight = (shielded) => { const g = setup(3, [[52, 20, -9, 0]]);                // a patrol heading left at the route at x = 40
        if (shielded) g.powerups.until.shield = g.clock.now + 5;
        g.route.begin(40, 1); g.route.move(40, 40);                                         // a live route from the top edge down to y = 40
        run(g, 2); const p = g.level.patrols[0];
        return { lives: g.run.lives, mode: g.route.mode, vx: p.vx, x: p.x, routeCells: g.grid.count(ROUTE) }; };
      const a = flight(true), b = flight(false);
      // the bounce is a mirror: the patrol arrives at (-9, 0) and leaves with the sign of vx flipped (12-degree rule aside)
      const g = setup(3, [[52, 20, -9, 0]]); g.powerups.until.shield = g.clock.now + 5; g.route.begin(40, 1); g.route.move(40, 40);
      const p = g.level.patrols[0]; let bounced = false; for (let i = 0; i < 240 && !bounced; i++) { g.step(STEP); if (p.vx > 0) bounced = true; }
      return { shielded: a, unshielded: b, bounced, speed: Math.hypot(p.vx, p.vy), atTheRoute: p.x > 40 + p.r - 0.2 };""")
    assert got['shielded']['lives'] == 3 and got['shielded']['mode'] == 'drawing' and got['shielded']['x'] > 40      # it stayed on its side of the route
    assert got['bounced'] is True and got['speed'] == pytest.approx(9, abs=1e-6) and got['atTheRoute'] is True
    assert got['unshielded']['lives'] == 2 and got['unshielded']['mode'] == 'spent'                                    # without it, the same flight costs a life


def test_shield_protects_against_patrols_flying_into_the_route_but_not_from_being_drawn_onto_or_from_tracers(page):
    got = js(page, """
      const out = {};
      let g = setup(3, [[60, 30, 0, 0]]); g.powerups.until.shield = g.clock.now + 5;
      g.route.begin(60, 1); g.route.move(60, 29.5); out.drawnOnto = { lives: g.run.lives, mode: g.route.mode };                  // still a hit: it would leave the patrol inside the route
      g = setup(4, [[110, 64, 0, 0]]); g.tracers.place([{ x: 40, y: 2, dir: -1 }]); g.powerups.until.shield = g.clock.now + 5;
      g.route.begin(40, 1); g.route.move(40, 3); let caught = false;
      for (let i = 0; i < 3 * 120 && !caught; i++) { g.route.move(40, 3 + i * 0.001); g.step(STEP); caught = g.run.lives < 3; }
      out.tracer = caught;                                                                                                    // a tracer still catches a shielded route
      return out;""")
    assert got['drawnOnto'] == {'lives': 2, 'mode': 'spent'} and got['tracer'] is True


def test_a_patrol_touching_a_shielded_route_when_the_shield_ends_is_not_a_false_hit(page):
    """A patrol that has just bounced off the shielded route is touching it. If that counted as a hit, every shield
    would cost a life as it ran out. So: find the step at which each patrol bounces, replay the same flight with the
    shield ending 0-3 steps after that, and as a control end it one step BEFORE, when the patrol flies into the
    route for real and must be a hit (a check that can never fail would prove nothing)."""
    got = js(page, """
      const make = (i) => { const angle = (i % 30) * 0.05 - 0.75, speed = 6 + (i % 7) * 3;              // patrols arriving at many angles and speeds
        const g = setup(3, [[50 + (i % 5), 20, -speed * Math.cos(angle), speed * Math.sin(angle)]], 'end' + i);
        clearObstacles(g);                                                                             // nothing but the route to bounce off: a patrol coming back later would be a fair hit, not a false one
        g.powerups.until.shield = g.clock.now + 60; g.route.begin(40, 1); g.route.move(40, 45); return g; };
      const bounceStep = (i) => { const g = make(i), p = g.level.patrols[0]; for (let s = 1; s <= 4 * 120; s++) { g.step(STEP); if (p.vx > 0) return s; } return -1; };
      const livesIfEndedAfter = (i, steps) => { const g = make(i); for (let s = 0; s < steps; s++) g.step(STEP);
        g.powerups.until.shield = g.clock.now; run(g, 1.5); return g.run.lives; };
      let bounced = 0, falseHits = 0, controlHits = 0;
      for (let i = 0; i < 300; i++) {
        const n = bounceStep(i); if (n < 1) continue; bounced++;
        for (let k = 0; k <= 3; k++) if (livesIfEndedAfter(i, n + k) < 3) falseHits++;
        if (livesIfEndedAfter(i, n - 1) < 3) controlHits++;
      }
      return { bounced, falseHits, controlHits };""")
    assert got['bounced'] > 200                                                           # the patrol really did meet the route in most flights
    assert got['falseHits'] == 0
    assert got['controlHits'] >= got['bounced'] * 0.95                                    # and ending the shield just before contact is a hit


# ---- the clock ------------------------------------------------------------------------------------------------------------------
def test_timers_and_the_pickup_run_on_the_game_clock_so_a_pause_stops_them(page):
    got = js(page, """
      const g = setup(3, [[110, 64, 0, 0]]); g.powerups.until.freeze = g.clock.now + 3; g.powerups.place('slow', 30, 30);
      run(g, 1); g.pause('manual'); run(g, 20);                                                // twenty seconds of nothing while paused
      const paused = { freeze: g.powerups.remaining('freeze'), pickup: g.powerups.pickup && g.powerups.pickup.expires - g.clock.now };
      g.resume(); run(g, 0.5);
      return { paused, after: g.powerups.remaining('freeze') };""")
    assert got['paused']['freeze'] == pytest.approx(2, abs=0.01) and got['paused']['pickup'] == pytest.approx(9, abs=0.02)
    assert got['after'] == pytest.approx(1.5, abs=0.02)


def test_a_new_level_a_restart_and_the_title_clear_every_effect_and_pickup(page):
    got = js(page, """
      const out = {};
      const g = setup(3); g.powerups.until.freeze = g.clock.now + 3; g.powerups.until.shield = g.clock.now + 5; g.powerups.place('slow', 30, 30);
      g.startLevel(4); out.newLevel = [g.powerups.pickup, g.powerups.active('freeze'), g.powerups.active('shield')];
      g.powerups.until.slow = g.clock.now + 5; g.powerups.place('freeze', 30, 30); g.restartLevel(); out.restart = [g.powerups.pickup, g.powerups.active('slow')];
      g.enterTitle(); out.title = [g.powerups.enabled === true, g.powerups.pickup];
      return out;""")
    assert got['newLevel'] == [None, False, False] and got['restart'] == [None, False]


# ---- saving ----------------------------------------------------------------------------------------------------------------------
def test_a_resumed_run_has_the_same_pickup_timers_and_future_pickups(page):
    got = js(page, """
      const backend = backendOf(); const A = setup(5, [[110, 64, 0, 0]], 'save-power', backend);
      A.commitCapture(colCells(A, 8));                                                     // (before the pickup exists, so it cannot swallow it)
      let guard = 0; while (!A.powerups.pickup && guard++ < 25 * 120) A.step(STEP);        // wait for the first pickup, then let it sit a while
      run(A, 3); A.powerups.until.slow = A.clock.now + POWER.slow; run(A, 1); A.powerups.until.shield = A.clock.now + POWER.shield; run(A, 1); A.persist();
      const before = { pickup: !!A.powerups.pickup, slow: A.powerups.remaining('slow'), shield: A.powerups.remaining('shield') };
      const B = new Game({ storage: createStorage(backend) }); B.enterTitle(); const offered = !!B.saved; B.resumeRun(); B.tick(3.1);
      const state = (g) => JSON.stringify({ p: g.powerups.pickup && { ...g.powerups.pickup, left: +(g.powerups.pickup.expires - g.clock.now).toFixed(6) },
        slow: +g.powerups.remaining('slow').toFixed(6), shield: +g.powerups.remaining('shield').toFixed(6), next: +(g.powerups.nextAt - g.clock.now).toFixed(6), kind: g.powerups.kind, draws: g.powerups.draws });
      const same = state(A) === state(B);
      A.log.length = 0; B.log = []; B.on('power', (e) => B.log.push([e.type, e.kind, +B.clock.now.toFixed(3), e.x === undefined ? null : +e.x.toFixed(6), e.y === undefined ? null : +e.y.toFixed(6)]));
      run(A, 40); run(B, 40);                                                              // patrols are parked, so the two games can only differ in what power-ups do
      const sched = (g) => g.log.map((e) => e.join(':'));
      return { before, offered, same, futureSame: JSON.stringify(sched(A)) === JSON.stringify(sched(B)), events: sched(A).length,
               spawns: A.log.filter((e) => e[0] === 'spawn').length, positionsSame: JSON.stringify(A.powerups.pickup) === JSON.stringify(B.powerups.pickup) };""")
    assert got['before']['pickup'] is True and got['before']['slow'] == pytest.approx(3, abs=0.01) and got['before']['shield'] == pytest.approx(4, abs=0.01)
    assert got['offered'] is True and got['same'] is True
    assert got['spawns'] >= 2 and got['futureSame'] is True and got['positionsSame'] is True      # the same kinds, at the same times, in the same places


def test_a_snapshot_with_bad_power_up_state_is_not_trusted(page):
    got = js(page, """
      const snap = await import('/js/snapshot.js');
      const g = setup(5, [[110, 64, 0, 0]], 'bad-power'); run(g, 14); g.persist();
      const good = JSON.parse(JSON.stringify(g.storage.loadSnapshot()));
      const edit = (fn) => { const c = JSON.parse(JSON.stringify(good)); fn(c); return c; };
      const ok = (raw) => snap.validateSnapshot(raw) !== null;
      const bad = { 'missing': (c) => { delete c.powerups; }, 'not an object': (c) => { c.powerups = 5; }, 'unknown kind': (c) => { c.kind = 'x'; c.powerups.kind = 'teleport'; },
        'a pickup of an unknown kind': (c) => { c.powerups.pickup = { kind: 'x', x: 10, y: 10, left: 5 }; }, 'a pickup off the board': (c) => { c.powerups.pickup = { kind: 'slow', x: 900, y: 10, left: 5 }; },
        'a pickup that lives too long': (c) => { c.powerups.pickup = { kind: 'slow', x: 10, y: 10, left: 99 }; }, 'a timer too long': (c) => { c.powerups.active = { freeze: 30 }; },
        'a negative timer': (c) => { c.powerups.active = { shield: -1 }; }, 'an unknown active kind': (c) => { c.powerups.active = { flight: 1 }; },
        'text draws': (c) => { c.powerups.draws.seq = '5'; }, 'endless draws': (c) => { c.powerups.draws.pos = 1e9; }, 'a next time too far': (c) => { c.powerups.nextIn = 500; } };
      return { good: ok(good), rejected: Object.fromEntries(Object.entries(bad).map(([k, fn]) => [k, ok(edit(fn))])) };""")
    assert got['good'] is True and not any(got['rejected'].values()), [k for k, v in got['rejected'].items() if v]


def test_a_save_written_the_instant_a_pickup_appears_or_is_taken_is_always_readable(page):
    """(now + 5) - now is not always exactly 5 in floating point, and a capture saves in the very step that collects a
    pickup. The saved times must stay inside the range the check on the way back in insists on, or the run is lost."""
    got = js(page, """
      const snap = await import('/js/snapshot.js');
      const stored = (backend) => JSON.parse(backend.map.get(SNAPSHOT_KEY));
      let rejected = 0, tried = 0, worstOver = 0, restored = 0, full = 0;
      for (let i = 0; i < 400; i++) {
        const backend = backendOf(); const g = setup(3, [[110, 64, 0, 0]], 'round' + i, backend);
        run(g, 1 + i * 0.37);                                                                  // a different clock value each time
        const kind = POWER.kinds[i % 3];
        g.powerups.place(kind, 40, 36); g.persist(); tried++;                                  // a pickup that has just appeared
        if (snap.validateSnapshot(stored(backend)) === null) rejected++;
        g.route.begin(40, 1); g.route.move(40, 40); g.persist(); tried++;                      // and one taken in the same instant
        const raw = stored(backend);
        if (snap.validateSnapshot(raw) === null) rejected++;
        worstOver = Math.max(worstOver, raw.powerups.active[kind] - POWER[kind]);
        const B = new Game({ storage: createStorage(backend) }); B.enterTitle();
        if (B.resumeRun()) { restored++; if (Math.abs(B.powerups.remaining(kind) - POWER[kind]) < 1e-9) full++; }
      }
      return { rejected, tried, worstOver, restored, full };""")
    assert got['tried'] == 800 and got['rejected'] == 0 and got['worstOver'] <= 0
    assert got['restored'] == 400 and got['full'] == 400                                        # and the resumed effect has its full time


# ---- what the player sees ---------------------------------------------------------------------------------------------------------------
def test_active_effects_show_as_round_chips_with_a_draining_ring_and_never_block_or_move_the_board(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.newRun({ seed: "chips" }); __pp.game.startLevel(3); __pp.setPatrols([{ x: 110, y: 64 }]); __pp.freeze(true)')
    board = lambda: page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")    # noqa: E731
    before = board()
    assert page.evaluate('document.querySelectorAll(".power").length') == 0
    page.evaluate('__pp.game.powerups.until.freeze = __pp.game.clock.now + 3; __pp.game.powerups.until.shield = __pp.game.clock.now + 5')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    chips = page.evaluate("[...document.querySelectorAll('.power')].map((c) => [c.dataset.kind, c.getAttribute('aria-label'), c.querySelector('.power-ring').getAttribute('stroke-dashoffset')])")
    assert [c[0] for c in chips] == ['freeze', 'shield']
    assert chips[0][1] == 'Freeze, 3 seconds left' and chips[1][1] == 'Shield, 5 seconds left' and float(chips[0][2]) == pytest.approx(0, abs=0.5)
    page.evaluate("document.querySelectorAll('.power').forEach((c) => { c.__mark = true; })")
    page.evaluate('__pp.step(60)')                                                     # 0.5 s later
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    ring = float(page.evaluate("document.querySelector('.power[data-kind=\"freeze\"] .power-ring').getAttribute('stroke-dashoffset')"))
    assert ring == pytest.approx(100 * (0.5 / 3), abs=1.5)                             # a sixth of the ring has drained
    assert page.evaluate("[...document.querySelectorAll('.power')].every((c) => c.__mark === true)") is True      # the same chips: only their rings were touched
    assert board() == before                                                           # the chips sit over the board: nothing moved
    box = page.evaluate("(() => { const r = document.querySelector('.power').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    assert page.evaluate("([x, y]) => document.elementFromPoint(x, y).id", box) == 'gameCanvas'      # a touch on a chip goes through to the board
    page.evaluate('__pp.step(600)')                                                    # 5.5 s in all
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('document.querySelectorAll(".power").length') == 0             # both ran out


@pytest.mark.parametrize('label,viewport,touch', [('landscape', DESKTOP, False), ('portrait', {'width': 390, 'height': 844}, True)])
def test_the_pickup_glyph_stands_upright_on_the_screen_even_when_the_board_is_turned(open_page, label, viewport, touch):
    """The portrait board is drawn turned a quarter. The pickup is drawn in board space, so it has to be turned back or
    its hourglass lies on its side. Measured on the pixels: the glyph must be taller than it is wide."""
    page = open_page(viewport=viewport, has_touch=touch, is_mobile=touch)
    assert page.evaluate('__pp.state().fit.rotated') == (label == 'portrait')
    page.evaluate('__pp.game.newRun({ seed: "upright" }); __pp.game.startLevel(3); __pp.setPatrols([{ x: 110, y: 64 }]); __pp.freeze(true); __pp.game.powerups.place("slow", 60, 36)')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    box = page.evaluate("""() => {
      const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect(), at = __pp.toClient(60, 36);
      const unit = r.width / (__pp.state().fit.rotated ? 72 : 120);                                 // css px per board unit
      const half = 1.6 * unit, ratio = c.width / r.width;                                           // a crop inside the badge's ring
      const n = Math.round(half * 2 * ratio), s = document.createElement('canvas'); s.width = s.height = n;
      const g = s.getContext('2d', { willReadFrequently: true });
      g.drawImage(c, (at.x - r.left - half) * ratio, (at.y - r.top - half) * ratio, n, n, 0, 0, n, n);
      const d = g.getImageData(0, 0, n, n).data; let x0 = n, y0 = n, x1 = -1, y1 = -1, lit = 0;
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        if (Math.hypot(x - n / 2, y - n / 2) > n / 2) continue;                                     // inside the circle: the ring's arcs cross the square's corners
        const i = (y * n + x) * 4; if (Math.min(d[i], d[i + 1], d[i + 2]) > 150) { lit++; x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }   // the glyph is near-white; the ring is amber and the field purple
      }
      return { w: x1 - x0 + 1, h: y1 - y0 + 1, lit };
    }""")
    assert box['lit'] > 20, box
    assert box['h'] > box['w'] * 1.3, box


def test_a_pickup_is_drawn_on_the_board_and_effects_are_announced_and_popped(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.newRun({ seed: "look" }); __pp.game.startLevel(3); __pp.setPatrols([{ x: 110, y: 64 }]); __pp.freeze(true); __pp.game.powerups.place("shield", 60, 36)')
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('__pp.renderer.pickupDrawn') == {'x': 60, 'y': 36, 'kind': 'shield'}
    at = page.evaluate('__pp.toClient(60, 36)')
    dark = page.evaluate("""([x, y]) => { const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
      const s = document.createElement('canvas'); s.width = s.height = 1; const g = s.getContext('2d', { willReadFrequently: true });
      g.drawImage(c, Math.round((x - r.left + 9) * c.width / r.width), Math.round((y - r.top) * c.height / r.height), 1, 1, 0, 0, 1, 1); return Array.from(g.getImageData(0, 0, 1, 1).data); }""", [at['x'], at['y']])
    assert dark[0] < 60 and dark[1] < 90                                                # the badge is a dark disc against the field, beside its glyph
    page.evaluate('__pp.game.route.begin(60, 1); __pp.game.route.move(60, 40)')          # drawn through it
    assert page.evaluate('__pp.game.powerups.active("shield")') is True
    assert page.evaluate('__pp.fx.popups.map((p) => p.text)') == ['SHIELD']
    assert 'Shield on for 5 seconds' in page.locator('#announcer').text_content()
    page.evaluate('__pp.step(1)'); page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.evaluate('__pp.renderer.pickupDrawn') is None                           # taken: gone from the board


def test_chips_show_through_a_live_run_but_not_over_the_win_or_game_over_screens(open_page):
    """The clock stops at game over, so an effect that was running would otherwise sit on that screen for ever."""
    page = open_page(viewport=DESKTOP)
    chips = lambda: page.evaluate('document.querySelectorAll(".power").length')      # noqa: E731
    level3(page, 'phases')
    page.evaluate('__pp.game.powerups.until.shield = __pp.game.clock.now + 5')
    frame(page)
    assert page.evaluate('__pp.state().phase') == 'playing' and chips() == 1
    page.evaluate('__pp.game.pause("manual")'); frame(page)
    assert page.evaluate('__pp.state().phase') == 'paused' and chips() == 1             # paused: the timers are held, and so are the chips
    page.evaluate('__pp.game.resume()'); frame(page)
    assert page.evaluate('__pp.state().phase') in ('playing', 'countdown') and chips() == 1
    page.evaluate('__pp.forceWin()'); frame(page)
    assert page.evaluate('__pp.state().phase') == 'clear' and chips() == 0
    level3(page, 'phases-over')
    page.evaluate('__pp.game.powerups.until.freeze = __pp.game.clock.now + 3; __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife()'); frame(page)
    assert page.evaluate('__pp.state().phase') == 'over' and chips() == 0
    page.evaluate('__pp.game.enterTitle()'); frame(page)
    assert page.evaluate('__pp.state().phase') == 'title' and chips() == 0


def test_only_a_freeze_tints_the_board_ice_blue(open_page):
    page = open_page(viewport=DESKTOP)
    level3(page, 'ice')
    plain = look(page, 30, 20)                                                          # open field, nothing drawn there
    page.evaluate('const p = __pp.game.powerups, now = __pp.game.clock.now; p.until.shield = now + 5; p.until.slow = now + 5')
    assert look(page, 30, 20) == plain                                                  # a shield and a slow-down leave the board as it was
    page.evaluate('__pp.game.powerups.until.freeze = __pp.game.clock.now + 3')
    frozen = look(page, 30, 20)
    assert frozen[1] - plain[1] >= 6 and frozen[2] - plain[2] >= 4 and abs(frozen[0] - plain[0]) <= 6, (plain, frozen)     # a faint cast: green and blue up, red hardly moved
    page.evaluate('__pp.step(400)')                                                      # the freeze runs out
    assert look(page, 30, 20) == plain


def test_a_shielded_route_glows_aqua_beside_the_line_and_an_unshielded_one_does_not(open_page):
    page = open_page(viewport=DESKTOP)
    level3(page, 'glow')
    page.evaluate('__pp.game.route.begin(60, 1); __pp.game.route.move(60, 30)')
    plain = look(page, 61.4, 15)                                                         # just beside the line
    page.evaluate('__pp.game.powerups.until.shield = __pp.game.clock.now + 5')
    glowing = look(page, 61.4, 15)
    assert glowing[1] - plain[1] >= 35 and glowing[2] - plain[2] >= 12, (plain, glowing)   # aqua laid over the field
    page.evaluate('__pp.step(700)')                                                      # the shield runs out
    assert look(page, 61.4, 15) == plain


def test_the_pickups_ring_drains_as_its_time_runs_out(open_page):
    page = open_page(viewport=DESKTOP)
    page.emulate_media(reduced_motion='reduce')                                          # no pulse, so the ring is where it is measured
    level3(page, 'ring')
    page.evaluate('__pp.game.powerups.place("slow", 60, 36)')
    fresh = (look(page, 62.1, 36), look(page, 57.9, 36))                                  # the ring's right and left points
    assert abs(fresh[0][0] - fresh[1][0]) <= 20, fresh                                    # a full ring: both sides alike
    page.evaluate('__pp.step(600)')                                                      # half of its ten seconds
    half = (look(page, 62.1, 36), look(page, 57.9, 36))
    assert half[0][0] - half[1][0] >= 60, half                                            # the clockwise half from the top is still bright amber; the left only a faint outline


def test_a_pickup_appearing_and_an_effect_ending_are_announced_for_screen_readers(open_page):
    page = open_page(viewport=DESKTOP)
    level3(page, 'announce')
    page.evaluate('__pp.step(2400)')                                                     # twenty seconds: the first pickup has appeared
    frame(page)
    assert re.search(r'Power-up: (Freeze|Shield|Slow)', page.locator('#announcer').text_content())
    page.evaluate('__pp.game.powerups.until.freeze = __pp.game.clock.now + 3; __pp.step(400)')
    frame(page)
    assert 'Freeze ended' in page.locator('#announcer').text_content()


def test_a_pickup_appearing_rings_and_taking_it_rings_bursts_and_names_itself(open_page):
    page = open_page(viewport=DESKTOP)
    level3(page, 'fx')
    page.evaluate('__pp.fx.clear(); __pp.game.emit("power", { type: "spawn", kind: "freeze", x: 60, y: 36 })')
    got = page.evaluate('__pp.fx.stats()')
    assert got['rings'] == 1 and got['particles'] == 0 and got['popups'] == 0           # appearing: one quiet ring
    page.evaluate('__pp.fx.clear(); __pp.game.powerups.place("slow", 60, 36); __pp.game.route.begin(60, 1); __pp.game.route.move(60, 38)')
    got = page.evaluate('__pp.fx.stats()')
    assert got['rings'] == 1 and got['popups'] == 1 and got['particles'] >= 18          # taking it: a ring, a burst and its name

