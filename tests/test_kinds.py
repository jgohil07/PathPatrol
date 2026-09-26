"""Patrol kinds (round 2): scouts (small, fast), bombers (big, slow) and hunters (wind up, then chase a slow pen).

The limits are pinned as literals here (radius, speed factor, turn rate, wind-up, the levels each kind arrives), so a
changed number must fail a test rather than quietly follow the code."""
import hashlib
import json
import math

import pytest

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP, levelInfo, KINDS } = await import('/js/config.js');
  const { Grid, FIELD, WALL, BORDER } = await import('/js/grid.js');
  const { makePatrol, advance, stats: P } = await import('/js/physics.js');
  const { buildLevel } = await import('/js/level.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const rngOf = (seed) => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const box = () => { const g = new Grid(); g.frame(4); return g; };
  const fresh = (patrols, seed = 'kinds') => {
    const storage = createStorage(memoryBackend()); const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed });
    game.level.patrols.length = 0; for (const [x, y, vx, vy, kind] of patrols) game.level.patrols.push(makePatrol(x, y, vx, vy, kind));
    return { game, storage }; };
  const angle = (p) => Math.atan2(p.vy, p.vx);
  const diff = (a, b) => { let d = a - b; d -= Math.PI * 2 * Math.round(d / (Math.PI * 2)); return d; };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- the kinds and the curve ------------------------------------------------------------------------------------------
def test_each_kind_has_its_size_speed_and_turning(page):
    got = js(page, "return Object.fromEntries(Object.entries(KINDS).map(([k, v]) => [k, { ...v }]));")
    assert got['standard'] == {'radius': 1.35, 'speed': 1}
    assert got['scout'] == {'radius': 1.0, 'speed': 1.35}
    assert got['bomber'] == {'radius': 2.1, 'speed': 0.7}
    assert got['hunter']['radius'] == 1.35 and got['hunter']['speed'] == 0.9 and got['hunter']['windup'] == 0.4
    assert got['hunter']['turn'] == pytest.approx(math.radians(50))


def test_new_kinds_join_one_at_a_time_and_replace_standard_patrols(page):
    levels = [1, 5, 7, 8, 9, 11, 12, 16, 17, 18, 19, 21, 25, 26, 28, 29, 31, 39]      # (no boss level: test_special.py covers those)
    got = js(page, "return arg.map((l) => { const i = levelInfo(l); return [i.patrols, i.kinds]; });", levels)
    S, C, B, H = 'standard', 'scout', 'bomber', 'hunter'
    table = {1: [S], 5: [S], 7: [S, S], 8: [S, C], 9: [S, C], 11: [S, S, C], 12: [S, C, B], 16: [S, S, C, B], 17: [S, S, C, B],
             18: [S, C, B, H], 19: [S, C, B, H], 21: [S, S, C, B, H], 25: [S, S, C, B, H], 26: [S, S, S, C, B, H], 28: [S, S, S, C, B, H],
             29: [S, S, S, C, B, H], 31: [S, S, S, C, B, H], 39: [S, S, S, C, B, H]}
    for level, (count, kinds) in zip(levels, got):
        assert kinds == table[level], level
        assert len(kinds) == count, level                                          # the curve's patrol count is untouched


def test_levels_one_to_seven_are_exactly_the_boards_they_were_before_kinds(page):
    # (level 5 is left out: it became an odd-shaped special level on purpose, test_special.py)
    """Hash of every patrol and obstacle on levels 1-7 for three seeds, taken from the code as it was before kinds existed
    (commit f195115): spawning by radius reduces to the old 2.2 u clearance and 8 u spacing for standard patrols. Values are
    rounded to 1e-9 first, because WebKit's and Chromium's Math.cos differ in the last bit."""
    got = js(page, """
      const out = {}; for (const seed of ['pathpatrol-campaign', 'seed0', 'seed7']) for (const n of [1, 2, 3, 4, 6, 7]) {
        const g = new Grid(); const l = buildLevel(n, seed, g); out[seed + '/' + n] = { p: l.patrols.map((p) => [p.x, p.y, p.vx, p.vy].map((v) => Math.round(v * 1e9) / 1e9)), o: l.obstacles }; }
      return out;""")
    digest = hashlib.sha256(json.dumps(got).encode()).hexdigest()
    assert digest == '51b87e0a326018e379b4db6be7f3e8d0dfaa913ee4c553e14a540421202d4ed1'


def test_every_kind_spawns_clear_of_walls_and_of_each_other_at_its_own_speed(page):
    got = js(page, """
      const bad = []; let seen = {};
      for (let s = 0; s < 30; s++) for (const n of [8, 12, 18, 26, 31]) {
        const g = new Grid(); const l = buildLevel(n, 'spawn' + s, g); const info = levelInfo(n);
        l.patrols.forEach((p, i) => {
          seen[p.kind] = (seen[p.kind] || 0) + 1;
          if (p.kind !== info.kinds[i]) bad.push(`${s}/${n}: patrol ${i} is ${p.kind}, wanted ${info.kinds[i]}`);
          if (p.r !== KINDS[p.kind].radius) bad.push(`${s}/${n}: wrong radius`);
          if (g.circleHitsSolid(p.x, p.y, p.r + 0.85)) bad.push(`${s}/${n}: ${p.kind} too close to a wall`);
          if (Math.abs(Math.hypot(p.vx, p.vy) - info.speed * KINDS[p.kind].speed) > 1e-9) bad.push(`${s}/${n}: ${p.kind} at the wrong speed`);
          for (const q of l.patrols.slice(i + 1)) if (Math.hypot(p.x - q.x, p.y - q.y) <= p.r + q.r + 5.3) bad.push(`${s}/${n}: two start too close`);
        });
      }
      return { bad: bad.slice(0, 5), seen };""")
    assert got['bad'] == []
    assert all(got['seen'].get(k, 0) > 0 for k in ('standard', 'scout', 'bomber', 'hunter'))


# ---- physics with mixed kinds ---------------------------------------------------------------------------------------------
def test_mixed_kinds_keep_their_speeds_never_overlap_and_never_leave_the_box(page):
    got = js(page, """
      const rnd = rngOf(3); const bad = []; let pairs = 0;
      for (let t = 0; t < 40; t++) {
        const g = box(); g.fillRect(100, 50, 130, 80, BORDER);                             // a block in the middle
        const kinds = ['standard', 'scout', 'bomber', 'hunter', 'scout', 'bomber'];
        const ps = kinds.map((k, i) => { const a = rnd() * Math.PI * 2, sp = 26 * KINDS[k].speed; return makePatrol(12 + i * 17, 20 + (i % 2) * 30, Math.cos(a) * sp, Math.sin(a) * sp, k); });
        for (let i = 0; i < 120 * 10; i++) {
          advance(ps, STEP, g);
          for (let a = 0; a < ps.length; a++) {
            const p = ps[a];
            if (Math.abs(Math.hypot(p.vx, p.vy) - 26 * KINDS[p.kind].speed) > 1e-6) bad.push(`${t}/${i}: ${p.kind} speed ${Math.hypot(p.vx, p.vy)}`);
            if (g.circleHitsSolid(p.x, p.y, p.r - 0.05)) bad.push(`${t}/${i}: ${p.kind} in a wall`);
            for (let b = a + 1; b < ps.length; b++) { pairs++; const q = ps[b]; if (Math.hypot(p.x - q.x, p.y - q.y) < p.r + q.r - 0.02) bad.push(`${t}/${i}: ${p.kind} inside ${q.kind}`); }
          }
          if (bad.length > 4) break;
        }
      }
      return { bad: bad.slice(0, 5), pairs };""")
    assert got['bad'] == [] and got['pairs'] > 100000


def test_a_small_fast_scout_never_tunnels_through_a_thin_wall(page):
    """Sub-steps follow the smallest radius on the board: a scout at 35 u/s (level 31's 26 x 1.35) and far faster must never
    cross a wall one cell thick. With the old rule (a standard radius for everyone) it moved 0.34 u per sub-step, a third
    of its own radius, and the invariant would only have held by luck."""
    got = js(page, """
      const bad = [];
      for (const speed of [35.1, 60, 120, 400]) for (let n = 0; n < 60; n++) {
        const g = box(); for (let y = 0; y < g.h; y++) g.cells[y * g.w + 120] = WALL;        // a wall one cell thick at x = 60
        const a = (n / 60 - 0.5) * 1.2, p = makePatrol(40, 12 + (n % 12) * 4, Math.cos(a) * speed, Math.sin(a) * speed, 'scout');
        for (let i = 0; i < 600; i++) { advance([p], STEP, g, { minAngle: 0 }); if (p.x > 60) { bad.push(`${speed}: crossed`); break; } }
      }
      P.substeps = 0; advance([makePatrol(40, 30, 35.1, 0, 'scout'), makePatrol(80, 30, 26, 0)], STEP, box());
      return { bad: bad.slice(0, 3), substeps: P.substeps };""")
    assert got['bad'] == []
    assert got['substeps'] == math.ceil((35.1 / 1.0) * (1 / 120) / 0.25)             # the scout's radius decides, not the standard's


def test_two_kinds_collide_at_the_sum_of_their_radii_and_part_at_their_own_speeds(page):
    got = js(page, """
      const g = box(); const a = makePatrol(40, 36, 20, 0, 'bomber'), b = makePatrol(60, 36, -27, 0, 'scout');
      let closest = 99; for (let i = 0; i < 240; i++) { advance([a, b], STEP, g, { minAngle: 0 }); closest = Math.min(closest, Math.hypot(a.x - b.x, a.y - b.y)); }
      return { closest, a: Math.hypot(a.vx, a.vy), b: Math.hypot(b.vx, b.vy), apart: a.vx < 0 && b.vx > 0 };""")
    assert got['closest'] == pytest.approx(2.1 + 1.0, abs=0.02) and got['apart']
    assert got['a'] == pytest.approx(20) and got['b'] == pytest.approx(27)


# ---- hunters -------------------------------------------------------------------------------------------------------------
def test_a_hunter_winds_up_for_four_tenths_of_a_second_then_turns_towards_the_pen_at_most_50_degrees_a_second(page):
    got = js(page, """
      const { game } = fresh([[60, 50, 20, 6, 'hunter'], [14, 30, 20, 6, 'standard']]);
      const h = game.level.patrols[0], s = game.level.patrols[1];
      const route = game.route; route.begin(100, 1); route.move(100, 8);                    // the pen is up and to the right of the hunter
      const before = angle(h), std0 = angle(s); const turns = []; let windupSteps = 0, bounced = false;
      for (let i = 0; i < 120 * 1.5; i++) {
        const a0 = angle(h); game.step(STEP); const d = diff(angle(h), a0);
        if (i < 47) { if (Math.abs(d) > 1e-9) windupSteps++; } else turns.push(Math.abs(d));
      }
      const towards = Math.abs(diff(angle(h), Math.atan2(route.tip.y - h.y, route.tip.x - h.x)));
      route.end('lift');
      const after = angle(h); for (let i = 0; i < 12; i++) game.step(STEP);
      return { windupSteps, maxTurn: Math.max(...turns), turned: Math.abs(diff(angle(h), before)), towards,
               stillAfterLift: Math.abs(diff(angle(h), after)), std: Math.abs(diff(angle(s), std0)), lives: game.run.lives };""")
    assert got['windupSteps'] == 0                                                      # not a hair of turning while it winds up (47 steps < 0.4 s)
    assert got['maxTurn'] <= math.radians(50) / 120 + 1e-9                               # never faster than 50 degrees a second
    assert got['turned'] > math.radians(20)                                              # and then it really did turn
    assert got['stillAfterLift'] < 1e-9                                                  # once the pen is lifted it flies straight on
    assert got['std'] < 1e-9                                                             # a standard patrol never steers


def test_a_hunter_only_winds_up_while_a_route_is_being_drawn_and_a_freeze_stops_it(page):
    got = js(page, """
      const { steeringOf } = await import('/js/steering.js');
      const { game } = fresh([[60, 50, 20, 6, 'hunter']]);
      const h = game.level.patrols[0]; const out = {};
      for (let i = 0; i < 60; i++) game.step(STEP); out.idle = steeringOf(h).state;
      game.route.begin(100, 1); out.armed = steeringOf(h).state;                                 // touching the edge is not drawing
      game.route.move(100, 8); game.step(STEP); out.drawing = steeringOf(h);
      game.powerups.until.freeze = game.clock.now + 5;                                           // a freeze holds the wind-up too
      for (let i = 0; i < 120; i++) game.step(STEP); out.frozen = steeringOf(h);
      delete game.powerups.until.freeze; for (let i = 0; i < 60; i++) game.step(STEP); out.later = steeringOf(h).state;
      game.route.end('lift'); game.step(STEP); out.lifted = steeringOf(h).state;
      return out;""")
    assert got['idle'] == 'idle' and got['armed'] == 'idle'
    assert got['drawing']['state'] == 'windup' and got['drawing']['t'] < 0.05
    assert got['frozen']['state'] == 'windup' and got['frozen']['t'] < 0.05
    assert got['later'] == 'chase' and got['lifted'] == 'idle'


def test_the_wind_up_and_the_chase_are_drawn(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate("__pp.game.newRun({ seed: 'kinds' }); __pp.freeze(true); __pp.setPatrols([{ x: 60, y: 50, vx: 20, vy: 6, kind: 'hunter' }, { x: 20, y: 20 }]); 0")
    page.evaluate("(() => { const r = __pp.game.route; r.begin(100, 1); r.move(100, 8); })(); __pp.step(12); __pp.renderer.draw(1); 0")
    assert page.evaluate('__pp.renderer.steeringDrawn') == {'none': 1, 'windup': 1}
    page.evaluate("__pp.step(60); __pp.renderer.draw(1); 0")
    assert page.evaluate('__pp.renderer.steeringDrawn') == {'none': 1, 'chase': 1}


# ---- saving, the look, the first meeting ------------------------------------------------------------------------------------
def test_kinds_survive_a_save_and_the_validator_rejects_an_unknown_kind(page):
    got = js(page, """
      const { game, storage } = fresh([[60, 50, 20, 6, 'hunter'], [20, 20, 12, 9, 'scout'], [90, 20, 9, 12, 'bomber'], [30, 60, 14, 5, 'standard']]);
      game.persist(); const raw = storage.loadSnapshot();
      const again = new Game({ storage }); again.enterTitle(); again.resumeRun();
      const kinds = again.level.patrols.map((p) => [p.kind, p.r, Math.round(p.speed * 1000) / 1000]);
      const bad = (fn) => { const c = JSON.parse(JSON.stringify(raw)); fn(c); return validateSnapshot(c, { today: game.today() }) === null; };
      return { saved: raw.patrols.map((p) => p[5]), kinds,
               unknown: bad((c) => { c.patrols[0][5] = 'dragon'; }), missing: bad((c) => { c.patrols[0].length = 5; }), number: bad((c) => { c.patrols[0][5] = 3; }) };""")
    assert got['saved'] == ['hunter', 'scout', 'bomber', 'standard']
    assert [k[:2] for k in got['kinds']] == [['hunter', 1.35], ['scout', 1.0], ['bomber', 2.1], ['standard', 1.35]]
    assert got['unknown'] and got['missing'] and got['number']


def test_each_kind_loads_its_own_sprite_in_each_theme(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.wait_for_function("Object.values(__pp.renderer.sprites).every((set) => Object.values(set).every((i) => i.complete && i.naturalWidth > 0))")
    files = page.evaluate("Object.fromEntries(Object.entries(__pp.renderer.sprites).map(([t, set]) => [t, Object.fromEntries(Object.entries(set).map(([k, i]) => [k, i.src.split('/').pop()]))]))")
    assert files == {'flight': {'standard': 'plane.svg', 'scout': 'scout.svg', 'bomber': 'bomber.svg', 'hunter': 'hunter.svg', 'boss': 'boss.svg'},
                     'drive': {'standard': 'car.svg', 'scout': 'scout-car.svg', 'bomber': 'bomber-car.svg', 'hunter': 'hunter-car.svg', 'boss': 'boss-car.svg'}}


def test_a_new_kind_is_introduced_once_per_device_after_the_levels_own_line(page):
    got = js(page, """
      const { game, storage } = fresh([[20, 20, 0, 0]]);
      const said = []; game.on('toast', (t) => said.push([Math.round(game.clock.now * 10) / 10, t.text]));
      game.startLevel(8);                                                                        // the first scout
      for (let i = 0; i < 120 * 2; i++) game.step(STEP);
      const first = said.slice(); said.length = 0;
      game.startLevel(8); for (let i = 0; i < 120 * 2; i++) game.step(STEP);                    // met before: nothing more
      const second = said.slice();
      return { first, second, seen: storage.settings.seenKinds };""")
    assert got['first'][0][1].startswith('Level 08') and got['first'][1] == [1.5, 'New · scouts: small and fast']
    assert [t for _, t in got['second'] if t.startswith('New')] == [] and got['seen'] == ['scout']


def test_the_stored_list_of_kinds_met_takes_only_known_kinds_once_each(page):
    got = js(page, """
      const { sanitize } = await import('/js/storage.js');
      return [['hunter', 'scout', 'hunter', 'dragon', 7, null], 'scout', {}, null].map((v) => sanitize({ settings: { seenKinds: v } }).settings.seenKinds);""")
    assert got == [['scout', 'hunter'], [], [], []]
