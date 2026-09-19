"""Module-level tests. They import the site's own ES modules inside a real browser and call them
directly, so what is tested is exactly what ships. Reference values for the RNG come from an
independent Python implementation, not from the code under test."""
import math

import pytest

M = 0xFFFFFFFF

# What a fresh profile's settings are. A new setting is added here once, and every test below that compares
# settings builds on it with the fields it cares about overridden.
DEFAULT_SETTINGS = {'sound': True, 'haptics': True, 'theme': 'flight', 'motion': 'auto', 'showFps': False, 'tutorialDone': False}


# ---- independent reference implementations (Python) --------------------------------------------
def ref_hash(text):
    h = 0x811C9DC5
    for unit in memoryview(text.encode('utf-16-le')).cast('H'):    # UTF-16 code units, like charCodeAt
        h ^= unit
        h = (h * 0x01000193) & M
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & M
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & M
    h ^= h >> 16
    return h & M


def ref_mulberry32(seed):
    a = seed & M

    def nxt():
        nonlocal a
        a = (a + 0x6D2B79F5) & M
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & M
        t = t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & M)) & M)
        return ((t ^ (t >> 14)) & M) / 4294967296
    return nxt


@pytest.fixture
def page(open_page):
    return open_page()


# ---- rng ---------------------------------------------------------------------------------------
def test_hash_matches_independent_implementation(page):
    texts = ['', 'a', 'pathpatrol-daily-2026-09-19', 'attract|layout|6', 'héllo ✓', '😀 astral']
    got = page.evaluate("async (texts) => { const { hashString } = await import('/js/rng.js'); return texts.map(hashString); }", texts)
    assert got == [ref_hash(t) for t in texts]


def test_mulberry32_matches_independent_implementation(page):
    seeds = [0, 1, 12345, 4294967295]
    got = page.evaluate("""async (seeds) => { const { mulberry32 } = await import('/js/rng.js');
      return seeds.map((s) => { const r = mulberry32(s); return Array.from({ length: 6 }, () => r()); }); }""", seeds)
    for seed, values in zip(seeds, got):
        ref = ref_mulberry32(seed)
        assert values == [ref() for _ in range(6)]


def test_daily_board_contract_is_pinned(page):
    """If this fails, every player's daily board has changed: only ever do that on purpose."""
    got = page.evaluate("""async () => { const { layoutRng, eventRng, dailySeed, dayKey } = await import('/js/rng.js');
      return { layout: layoutRng(dailySeed('2026-09-19'), 1).float(), events: eventRng(dailySeed('2026-09-19'), 1).float(),
               key: dayKey(new Date(2026, 8, 19)), keyPadded: dayKey(new Date(2026, 0, 5)), seed: dailySeed('2026-09-19') }; }""")
    assert got['seed'] == 'pathpatrol-daily-2026-09-19'
    assert got['key'] == '2026-09-19' and got['keyPadded'] == '2026-01-05'
    assert got['layout'] == ref_mulberry32(ref_hash('pathpatrol-daily-2026-09-19|layout|1'))()
    assert got['events'] == ref_mulberry32(ref_hash('pathpatrol-daily-2026-09-19|events|1'))()
    assert got['layout'] != got['events']


def test_rng_helpers(page):
    got = page.evaluate("""async () => { const { Rng, randomSeed } = await import('/js/rng.js');
      const a = new Rng('x'), b = new Rng('x'), c = new Rng('y');
      const seq = (r) => Array.from({ length: 6 }, () => r.float());
      const ri = new Rng('ints'); const ints = Array.from({ length: 500 }, () => ri.int(3, 7));
      const r = new Rng('pick'); const picks = new Set(Array.from({ length: 200 }, () => r.pick(['a', 'b', 'c'])));
      const rr = new Rng('range'); const ranges = Array.from({ length: 200 }, () => rr.range(-2, 5));
      return { same: JSON.stringify(seq(a)) === JSON.stringify(seq(b)), differs: JSON.stringify(seq(new Rng('x'))) !== JSON.stringify(seq(c)),
               intsOk: ints.every((n) => n >= 3 && n < 7 && Number.isInteger(n)) && new Set(ints).size === 4, picks: [...picks].sort(),
               rangeOk: ranges.every((v) => v >= -2 && v < 5), seedA: randomSeed(), seedB: randomSeed() }; }""")
    assert got['same'] and got['differs'] and got['intsOk'] and got['rangeOk']
    assert got['picks'] == ['a', 'b', 'c']
    assert got['seedA'] and got['seedA'] != got['seedB']


# ---- config ------------------------------------------------------------------------------------
def test_level_curve(page):
    levels = [1, 2, 3, 4, 7, 13, 14, 30]
    infos = page.evaluate("async (levels) => { const { levelInfo } = await import('/js/config.js'); return levels.map(levelInfo); }", levels)
    for level, info in zip(levels, infos):
        assert info['level'] == level
        assert info['patrols'] == min(6, 1 + (level - 1) // 2)
        assert info['obstacles'] == min(5, (level - 1) // 2)
        assert info['target'] == min(70, 65 + ((level - 1) // 2) * 2)
        assert info['tracers'] == (min(3, (level - 1) // 3) if level >= 4 else 0)
        assert info['speed'] == pytest.approx(min(26, 14 * (1 + 0.07 * (level - 1))))
    assert max(i['speed'] for i in infos) == 26          # capped: D7
    odd = page.evaluate("async () => { const { levelInfo } = await import('/js/config.js'); return [levelInfo(0).level, levelInfo(2.7).level, levelInfo(-5).level]; }")
    assert odd == [1, 2, 1]


# ---- grid --------------------------------------------------------------------------------------
def test_flood_fill_claims_only_unreachable_open_cells(page):
    got = page.evaluate("""async () => { const { Grid, FIELD, WALL } = await import('/js/grid.js');
      const make = () => { const g = new Grid(10, 5); for (let y = 0; y < 5; y++) g.set(5, y, WALL); return g; };
      const out = {};
      let g = make(); out.oneSide = { claimed: g.claimUnreachable([g.index(2, 2)]), open: g.count(FIELD),
        rightAllWall: [6, 7, 8, 9].every((x) => [0, 1, 2, 3, 4].every((y) => g.get(x, y) === WALL)) };
      g = make(); out.bothSides = { claimed: g.claimUnreachable([g.index(2, 2), g.index(8, 1)]), open: g.count(FIELD) };
      g = make(); out.noSeeds = { claimed: g.claimUnreachable([]), open: g.count(FIELD) };
      g = make(); out.seedOnWall = { claimed: g.claimUnreachable([g.index(5, 2)]), open: g.count(FIELD) };
      // a diagonal wall: a 4-connected fill must not slip through the corner gaps
      g = new Grid(6, 6); for (let i = 0; i < 6; i++) g.set(5 - i, i, WALL);
      out.diagonal = { claimed: g.claimUnreachable([g.index(0, 0)]), open: g.count(FIELD) };
      return out; }""")
    assert got['oneSide'] == {'claimed': 20, 'open': 25, 'rightAllWall': True}
    assert got['bothSides'] == {'claimed': 0, 'open': 45}
    assert got['noSeeds'] == {'claimed': 45, 'open': 0}
    assert got['seedOnWall'] == {'claimed': 45, 'open': 0}
    assert got['diagonal'] == {'claimed': 15, 'open': 15}


def test_circle_hit_test_uses_true_distance(page):
    got = page.evaluate("""async () => { const { Grid, BORDER } = await import('/js/grid.js');
      const g = new Grid(); g.frame(4);                               // frame = 2 world units
      g.fillRect(100, 60, 120, 80, BORDER);                          // a block at x 50..60, y 30..40
      const r = 1.35;
      return { centre: g.circleHitsSolid(90, 36, r),
               justInside: g.circleHitsSolid(60, 3.34, r), justOutside: g.circleHitsSolid(60, 3.36, r),
               leftEdge: g.circleHitsSolid(3.34, 36, r), leftClear: g.circleHitsSolid(3.36, 36, r),
               outOfBounds: g.circleHitsSolid(-1, 5, r),
               cornerMiss: g.circleHitsSolid(61, 41, r),               // distance to the block's corner is 1.414
               cornerHit: g.circleHitsSolid(60.9, 40.9, r) };          // distance 1.27
    }""")
    assert got == {'centre': False, 'justInside': True, 'justOutside': False, 'leftEdge': True, 'leftClear': False,
                   'outOfBounds': True, 'cornerMiss': False, 'cornerHit': True}


# ---- storage -----------------------------------------------------------------------------------
NO_DAILY = {'streak': 0, 'best': 0, 'last': '', 'result': None}          # the daily's record before it has been played
STORAGE_PRELUDE = """
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const backendOf = (initial = {}) => { const map = new Map(Object.entries(initial));
    return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: (k) => { map.delete(k); } }; };
"""


def test_storage_defaults_and_round_trip(page):
    got = page.evaluate("async () => {" + STORAGE_PRELUDE + """
      const backend = backendOf();
      const a = createStorage(backend);
      const defaults = { settings: { ...a.settings }, records: { ...a.records }, persistent: a.persistent };
      a.updateSettings({ theme: 'drive', sound: false, haptics: false, motion: 'reduced', showFps: true, tutorialDone: true });
      a.updateRecords((r) => { r.runs = 4; r.bestClear = 61.5; r.bestScore = 12480; });
      const b = createStorage(backend);
      return { defaults, settings: { ...b.settings }, records: { ...b.records }, keys: [...backend.map.keys()] }; }""")
    assert got['defaults'] == {'settings': DEFAULT_SETTINGS,
                               'records': {'bestScore': 0, 'bestClear': 0, 'bestLevel': 0, 'runs': 0, 'wins': 0, 'daily': NO_DAILY}, 'persistent': True}
    assert got['settings'] == {**DEFAULT_SETTINGS, 'sound': False, 'haptics': False, 'theme': 'drive', 'motion': 'reduced', 'showFps': True, 'tutorialDone': True}
    assert got['records'] == {'bestScore': 12480, 'bestClear': 61.5, 'bestLevel': 0, 'runs': 4, 'wins': 0, 'daily': NO_DAILY}
    assert got['keys'] == ['pathpatrol:v2']


def test_storage_migrates_the_prototype_records(page):
    got = page.evaluate("async () => {" + STORAGE_PRELUDE + """
      const legacy = JSON.stringify({ bestClear: 55.5, bestLevel: 4, runs: 9, wins: 3, theme: 'drive' });
      const backend = backendOf({ 'color-divide-records-v1': legacy });
      const s = createStorage(backend);
      const before = { settings: { ...s.settings }, records: { ...s.records } };
      s.updateSettings({});                                   // any write creates the v2 key
      return { before, keys: [...backend.map.keys()].sort(), legacyIntact: backend.map.get('color-divide-records-v1') === legacy }; }""")
    assert got['before'] == {'settings': {**DEFAULT_SETTINGS, 'theme': 'drive'},
                             'records': {'bestScore': 0, 'bestClear': 55.5, 'bestLevel': 4, 'runs': 9, 'wins': 3, 'daily': NO_DAILY}}       # the prototype kept no score
    assert got['keys'] == ['color-divide-records-v1', 'pathpatrol:v2']
    assert got['legacyIntact']


def test_storage_survives_garbage(page):
    got = page.evaluate("async () => {" + STORAGE_PRELUDE + """
      const results = {};
      results.notJson = (() => { const s = createStorage(backendOf({ 'pathpatrol:v2': '{nope' })); return { ...s.records }; })();
      results.legacyGarbage = (() => { const s = createStorage(backendOf({ 'color-divide-records-v1': 'also nope' })); return { ...s.records }; })();
      results.wrongTypes = (() => {
        const blob = { v: 2, settings: { sound: 'yes', haptics: 'no', theme: 'neon', motion: 'sideways', showFps: 'yes', tutorialDone: 1 }, records: { bestScore: 'lots', bestClear: -5, bestLevel: '7', runs: 3, wins: null, extra: 1 } };
        const s = createStorage(backendOf({ 'pathpatrol:v2': JSON.stringify(blob) }));
        return { settings: { ...s.settings }, records: { ...s.records } }; })();
      return results; }""")
    zero = {'bestScore': 0, 'bestClear': 0, 'bestLevel': 0, 'runs': 0, 'wins': 0, 'daily': NO_DAILY}
    assert got['notJson'] == zero and got['legacyGarbage'] == zero
    assert got['wrongTypes'] == {'settings': DEFAULT_SETTINGS,                                            # every wrong type falls back to its default
                                 'records': {'bestScore': 0, 'bestClear': 0, 'bestLevel': 0, 'runs': 3, 'wins': 0, 'daily': NO_DAILY}}


def test_storage_that_throws_still_works_in_memory(page):
    got = page.evaluate("async () => {" + STORAGE_PRELUDE + """
      const hostile = { getItem() { throw new Error('denied'); }, setItem() { throw new DOMException('full', 'QuotaExceededError'); }, removeItem() { throw new Error('denied'); } };
      const s = createStorage(hostile);
      s.updateRecords((r) => { r.runs = 2; });
      s.updateSettings({ theme: 'drive' });
      return { persistent: s.persistent, runs: s.records.runs, theme: s.settings.theme }; }""")
    assert got == {'persistent': False, 'runs': 2, 'theme': 'drive'}


def test_reset_records_keeps_settings(page):
    got = page.evaluate("async () => {" + STORAGE_PRELUDE + """
      const s = createStorage(backendOf());
      s.updateSettings({ theme: 'drive', sound: false, haptics: false, motion: 'full', showFps: true, tutorialDone: true });
      s.updateRecords((r) => { r.runs = 7; r.wins = 2; r.bestLevel = 5; r.bestClear = 66; r.bestScore = 9000; });
      s.resetRecords();
      return { settings: { ...s.settings }, records: { ...s.records } }; }""")
    assert got['settings'] == {**DEFAULT_SETTINGS, 'sound': False, 'haptics': False, 'theme': 'drive', 'motion': 'full', 'showFps': True, 'tutorialDone': True}     # D9: the prototype dropped the theme here
    assert got['records'] == {'bestScore': 0, 'bestClear': 0, 'bestLevel': 0, 'runs': 0, 'wins': 0, 'daily': NO_DAILY}


# ---- level -------------------------------------------------------------------------------------
def test_levels_are_deterministic_and_valid(page):
    got = page.evaluate("""async () => { const { Grid, BORDER } = await import('/js/grid.js'); const { buildLevel } = await import('/js/level.js');
      const { levelInfo, FRAME_UNITS, CELLS_PER_UNIT: S } = await import('/js/config.js');
      const summary = (lvl, g) => JSON.stringify({ cells: Array.from(g.cells), p: lvl.patrols.map((p) => [p.x, p.y, p.vx, p.vy]), o: lvl.obstacles });
      const bad = [];
      for (let s = 0; s < 40; s++) {
        const seed = 'seed' + s;
        for (let n = 1; n <= 20; n++) {
          const g = new Grid(); const lvl = buildLevel(n, seed, g); const info = levelInfo(n);
          if (lvl.patrols.length !== info.patrols) bad.push(`${seed}/${n}: ${lvl.patrols.length} patrols, wanted ${info.patrols}`);
          if (lvl.obstacles.length !== info.obstacles) bad.push(`${seed}/${n}: ${lvl.obstacles.length} obstacles, wanted ${info.obstacles}`);
          for (const p of lvl.patrols) if (g.circleHitsSolid(p.x, p.y, p.r)) bad.push(`${seed}/${n}: a patrol starts inside a wall`);
          for (let i = 0; i < lvl.patrols.length; i++) for (let j = i + 1; j < lvl.patrols.length; j++)
            if (Math.hypot(lvl.patrols[i].x - lvl.patrols[j].x, lvl.patrols[i].y - lvl.patrols[j].y) <= 8) bad.push(`${seed}/${n}: two patrols start too close`);
          for (const p of lvl.patrols) if (Math.abs(Math.hypot(p.vx, p.vy) - info.speed) > 1e-9) bad.push(`${seed}/${n}: wrong patrol speed`);
          for (const o of lvl.obstacles) for (let y = o.y * S; y < (o.y + o.h) * S; y++) for (let x = o.x * S; x < (o.x + o.w) * S; x++)
            if (g.get(x, y) !== BORDER) bad.push(`${seed}/${n}: obstacle not stamped`);
          if (lvl.initialPlayable !== g.countField()) bad.push(`${seed}/${n}: initialPlayable is stale`);
        }
      }
      const a = new Grid(), b = new Grid(), c = new Grid(), d = new Grid();
      const la = buildLevel(5, 'same', a), lb = buildLevel(5, 'same', b), lc = buildLevel(5, 'other', c);
      buildLevel(4, 'same', d); const ld = buildLevel(5, 'same', d);       // level 4 built first: level 5 must not change
      return { bad: bad.slice(0, 5), badCount: bad.length, sameSeed: summary(la, a) === summary(lb, b), otherSeed: summary(la, a) !== summary(lc, c),
               independentOfHistory: summary(la, a) === summary(ld, d), frame: a.get(0, 0) === BORDER && a.get(a.w - 1, a.h - 1) === BORDER && a.get(FRAME_UNITS * S, FRAME_UNITS * S) === 0 }; }""")
    assert got['badCount'] == 0, got['bad']
    assert got['sameSeed'] and got['otherSeed'] and got['independentOfHistory'] and got['frame']


# ---- scheduler ---------------------------------------------------------------------------------
def test_scheduler_runs_in_order_and_reset_cancels(page):
    got = page.evaluate("""async () => { const { Scheduler } = await import('/js/game.js');
      const log = []; const s = new Scheduler();
      s.after(1, () => log.push('a')); s.after(0.5, () => log.push('b')); s.after(0.5, () => log.push('b2'));
      s.advance(0.4); const t0 = [...log]; s.advance(0.2); const t1 = [...log]; s.advance(0.5); const t2 = [...log];
      const nested = new Scheduler(); const nlog = []; nested.after(1, () => { nlog.push('outer'); nested.after(1, () => nlog.push('inner')); });
      nested.advance(1.5); const n1 = [...nlog]; nested.advance(1.1); const n2 = [...nlog];
      const r = new Scheduler(); const rlog = []; r.after(1, () => rlog.push('stale')); const epoch = r.epoch; r.reset(); r.advance(5);
      const c = new Scheduler(); const clog = []; const task = c.after(1, () => clog.push('x')); c.cancel(task); c.advance(2);
      return { t0, t1, t2, n1, n2, rlog, epochBumped: r.epoch === epoch + 1, pending: r.pending, clog }; }""")
    assert got['t0'] == [] and got['t1'] == ['b', 'b2'] and got['t2'] == ['b', 'b2', 'a']
    assert got['n1'] == ['outer'] and got['n2'] == ['outer', 'inner']
    assert got['rlog'] == [] and got['epochBumped'] and got['pending'] == 0 and got['clog'] == []


# ---- view maths --------------------------------------------------------------------------------
def test_view_fit_and_rotation_maths(page):
    got = page.evaluate("""async () => { const v = await import('/js/view.js');
      const wide = v.computeFit(800, 500, 1), tall = v.computeFit(400, 800, 3), square = v.computeFit(500, 500, 1);
      const roundTrip = []; for (const rotated of [false, true]) for (let i = 0; i < 50; i++) {
        const x = (i * 7.3) % 120, y = (i * 3.1) % 72; const f = v.boardToFraction(rotated, x, y); const b = v.fractionToBoard(rotated, f.u, f.v);
        roundTrip.push(Math.abs(b.x - x) < 1e-9 && Math.abs(b.y - y) < 1e-9 && f.u >= 0 && f.u <= 1 && f.v >= 0 && f.v <= 1); }
      const apply = (m, x, y) => ({ x: m[0] * x + m[2] * y + m[4], y: m[1] * x + m[3] * y + m[5] });
      const corners = (fit) => { const m = v.boardMatrix(fit); return { tl: apply(m, 0, 0), br: apply(m, 120, 72), tr: apply(m, 120, 0) }; };
      const dirs = []; for (const rotated of [false, true]) for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const f = v.boardToFraction(rotated, 60, 36), eps = 0.001; const moved = v.fractionToBoard(rotated, f.u + dx * eps, f.v + dy * eps);
        const want = v.screenDirToBoard(rotated, dx, dy); const got = { x: (moved.x - 60), y: (moved.y - 36) };
        const scale = Math.hypot(got.x, got.y); dirs.push(Math.abs(got.x / scale - want.x) < 1e-9 && Math.abs(got.y / scale - want.y) < 1e-9); }
      return { wide, tall, square, roundTrip: roundTrip.every(Boolean), wideCorners: corners(wide), tallCorners: corners(tall), dirs: dirs.every(Boolean),
               tiny: v.computeFit(0, 0, 1) }; }""")
    wide, tall, square = got['wide'], got['tall'], got['square']
    assert not wide['rotated'] and wide['cssW'] == pytest.approx(800) and wide['cssH'] == pytest.approx(480)
    assert tall['rotated'] and tall['cssW'] == pytest.approx(400) and tall['cssH'] == pytest.approx(400 * 120 / 72)
    assert tall['ratio'] == 2 and tall['pxW'] == 800                     # a 3x screen is capped at 2x
    assert not square['rotated']                                         # square stays landscape
    assert got['roundTrip'] and got['dirs']
    k = wide['k']
    assert got['wideCorners']['tl'] == {'x': 0, 'y': 0} and got['wideCorners']['br']['x'] == pytest.approx(120 * k)
    tk = tall['k']                                                       # rotated 90 degrees clockwise: top-left goes to top-right
    assert got['tallCorners']['tl']['x'] == pytest.approx(72 * tk) and got['tallCorners']['tl']['y'] == pytest.approx(0)
    assert got['tallCorners']['br']['x'] == pytest.approx(0) and got['tallCorners']['br']['y'] == pytest.approx(120 * tk)
    assert got['tiny']['pxW'] >= 1 and got['tiny']['pxH'] >= 1


# ---- game state machine ------------------------------------------------------------------------
GAME_PRELUDE = """
  const { Game, PHASE } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP } = await import('/js/config.js');
  const { FIELD, WALL } = await import('/js/grid.js');
  const fresh = () => { const storage = createStorage(memoryBackend()); const game = new Game({ storage }); game.enterTitle(); return { game, storage }; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  const rowCells = (game, unitY) => { const g = game.grid, y = Math.floor(unitY * 2), cells = []; for (let x = 0; x < g.w; x++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); return cells; };
"""


def test_game_run_lifecycle_and_lives(page):
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const { game, storage } = fresh(); const out = { title: game.phase, hudOnTitle: game.hud() };
      game.newRun({ seed: 't1' }); out.started = { phase: game.phase, lives: game.run.lives, level: game.level.number, runs: storage.records.runs };
      game.loseLife(); game.loseLife(); out.afterTwoHits = { phase: game.phase, lives: game.run.lives };
      game.loseLife(); out.afterThree = { phase: game.phase, lives: game.run.lives, report: game.report };
      out.restartAfterGameOver = game.restartLevel();                      // D4: the prototype allowed this, with 0 lives
      game.newRun({ seed: 't2' }); out.newRun = { phase: game.phase, lives: game.run.lives, level: game.level.number, runs: storage.records.runs };
      return out; }""")
    assert got['title'] == 'title' and got['hudOnTitle']['level'] == 1 and got['hudOnTitle']['target'] == 65 and got['hudOnTitle']['patrols'] == 1
    assert got['started'] == {'phase': 'playing', 'lives': 3, 'level': 1, 'runs': 1}
    assert got['afterTwoHits'] == {'phase': 'playing', 'lives': 1}
    assert got['afterThree']['phase'] == 'over' and got['afterThree']['lives'] == 0
    assert got['afterThree']['report']['level'] == 1
    assert got['restartAfterGameOver'] is False
    assert got['newRun'] == {'phase': 'playing', 'lives': 3, 'level': 1, 'runs': 2}


def test_capture_claims_the_side_without_a_patrol(page):
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const { game } = fresh(); game.newRun({ seed: 'cap' });
      game.level.patrols.length = 0;
      const { makePatrol } = await import('/js/physics.js');
      game.level.patrols.push(makePatrol(60, 10, 0, 0));                 // upper half
      const before = game.grid.countField(); const total = game.level.initialPlayable;
      const result = game.commitCapture(rowCells(game, 36));             // a full-width cut across the middle
      const g = game.grid;
      return { before, total, result, upperOpen: g.get(120, 20) === FIELD, lowerClaimed: g.get(120, 120) === WALL, cutIsWall: g.get(120, 72) === WALL,
               consistent: Math.abs(game.level.cleared - (1 - g.countField() / total) * 100) < 1e-9, phase: game.phase, best: game.storage.records.bestClear }; }""")
    assert got['before'] == got['total']
    assert got['upperOpen'] and got['lowerClaimed'] and got['cutIsWall'] and got['consistent']
    assert 40 < got['result']['percent'] < 55 and got['result']['gained'] == pytest.approx(got['result']['percent'])
    assert got['phase'] == 'playing'                                       # 47 % is below the 65 % target
    assert got['best'] == pytest.approx(got['result']['percent'])


def test_win_banner_cannot_be_restarted_or_outlived_by_a_pause(page):
    """D5: the prototype's setTimeout-based win could be restarted into a phantom win, and could override a pause."""
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const out = {}; const { LEVEL_CLEAR_DELAY: D } = await import('/js/config.js');
      // a) restart is refused while the banner shows, so nothing stale can fire
      let { game, storage } = fresh(); game.newRun({ seed: 'w1' }); game.level.patrols.length = 0; game.commitCapture(rowCells(game, 36));
      out.a = { phase: game.phase, pending: game.clock.pending, restart: game.restartLevel(), phaseAfter: game.phase, wins: storage.records.wins };
      run(game, D - 0.1); out.aEarly = game.phase; run(game, 0.2);              // just before the delay it is still the win screen
      out.aNext = { phase: game.phase, level: game.level.number, wins: storage.records.wins, cleared: game.level.cleared };
      // b) a pause freezes the win timer; resuming continues it
      ({ game, storage } = fresh()); game.newRun({ seed: 'w2' }); game.level.patrols.length = 0; game.commitCapture(rowCells(game, 36));
      out.bPause = game.pause('manual'); const frozenAt = game.clock.now; run(game, 3);
      out.b = { phase: game.phase, level: game.level.number, clockMoved: game.clock.now !== frozenAt, pending: game.clock.pending };
      game.resume(); out.bResumed = game.phase; run(game, D + 0.05); out.bNext = { phase: game.phase, level: game.level.number };
      // c) restarting a normal level resets the clock, so a task from the old level can never fire
      ({ game, storage } = fresh()); game.newRun({ seed: 'w3' }); game.clock.after(0.5, () => { game.__stale = true; });
      game.restartLevel(); run(game, 1); out.c = { stale: !!game.__stale, pending: game.clock.pending, phase: game.phase };
      return out; }""")
    assert got['a']['phase'] == 'clear' and got['a']['pending'] == 1 and got['a']['restart'] is False
    assert got['a']['phaseAfter'] == 'clear' and got['a']['wins'] == 1
    assert got['aEarly'] == 'clear' and got['aNext'] == {'phase': 'playing', 'level': 2, 'wins': 1, 'cleared': 0}
    assert got['bPause'] is True and got['b'] == {'phase': 'paused', 'level': 1, 'clockMoved': False, 'pending': 1}
    assert got['bResumed'] == 'clear' and got['bNext'] == {'phase': 'playing', 'level': 2}
    assert got['c'] == {'stale': False, 'pending': 0, 'phase': 'playing'}


def test_pause_resume_and_automatic_countdown(page):
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const { game } = fresh(); game.newRun({ seed: 'p' }); const out = {};
      const x0 = game.level.patrols[0].x; run(game, 0.5); const moved = game.level.patrols[0].x !== x0;
      out.pausedFromTitle = (() => { const g2 = fresh().game; return g2.pause(); })();
      out.pause = game.pause('manual'); const xp = game.level.patrols[0].x; run(game, 1); out.frozen = game.level.patrols[0].x === xp;
      out.manualResume = (game.resume(), game.phase);
      out.autoPause = game.pause('auto'); game.resume(); out.countdown = { phase: game.phase, remaining: game.countdown };
      game.tick(1); const afterOne = { phase: game.phase, remaining: game.countdown }; game.tick(1.5); const afterTwoHalf = game.phase; game.tick(1); out.done = { afterOne, afterTwoHalf, phase: game.phase };
      game.pause('auto'); game.resume(); game.resume(); out.skipped = game.phase;         // a second press skips the countdown
      game.togglePause(); out.toggled = game.phase; game.togglePause(); out.toggledBack = game.phase;
      out.moved = moved; return out; }""")
    assert got['moved'] and got['pausedFromTitle'] is False and got['pause'] is True and got['frozen']
    assert got['manualResume'] == 'playing'
    assert got['autoPause'] is True and got['countdown']['phase'] == 'countdown' and got['countdown']['remaining'] == 3
    assert got['done']['afterOne'] == {'phase': 'countdown', 'remaining': 2}
    assert got['done']['afterTwoHalf'] == 'countdown' and got['done']['phase'] == 'playing'
    assert got['skipped'] == 'playing' and got['toggled'] == 'paused' and got['toggledBack'] == 'playing'


def test_crash_stops_the_game(page):
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const { game } = fresh(); game.newRun({ seed: 'c' }); const events = []; game.on('crash', (e) => events.push(String(e.error)));
      const x0 = game.level.patrols[0].x; game.crash(new Error('boom')); game.crash(new Error('again')); run(game, 1);
      return { phase: game.phase, events, frozen: game.level.patrols[0].x === x0, stepping: game.isStepping() }; }""")
    assert got == {'phase': 'crashed', 'events': ['Error: boom'], 'frozen': True, 'stepping': False}


def test_patrols_are_never_claimed_even_when_a_wall_covers_their_centre(page):
    got = page.evaluate("async () => {" + GAME_PRELUDE + """
      const { game } = fresh(); game.newRun({ seed: 'seed-fallback' }); game.level.patrols.length = 0;
      const { makePatrol } = await import('/js/physics.js');
      const p = makePatrol(60, 36, 0, 0); game.level.patrols.push(p);
      const g = game.grid; const cx = Math.floor(p.x * 2), cy = Math.floor(p.y * 2);
      g.set(cx, cy, WALL);                                              // a fresh wall lands on the patrol's own cell
      const result = game.commitCapture(rowCells(game, 10));           // an unrelated cut far above
      const seeds = game._patrolSeeds();
      return { seedCount: seeds.length, everySeedIsOpen: seeds.every((i) => g.cells[i] === FIELD), nearbyStillOpen: g.get(cx + 1, cy) === FIELD, cleared: game.level.cleared }; }""")
    assert got['seedCount'] > 0 and got['everySeedIsOpen'] and got['nearbyStillOpen']
    assert 0 < got['cleared'] < 100
