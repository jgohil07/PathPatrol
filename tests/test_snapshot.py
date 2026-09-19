"""Resuming an interrupted run: the grid encoding, validation of whatever storage holds, an exact restore that
plays on identically, when a run is saved and forgotten, and the whole path a player takes (hide the page, come
back, tap Resume)."""
import json

import pytest

KEY = 'pathpatrol:v2:run'

PRELUDE = """
  const snap = await import('/js/snapshot.js');
  const { Game, PHASE } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP, GRID_W, GRID_H, SNAPSHOT_KEY } = await import('/js/config.js');
  const { FIELD, WALL, BORDER, ROUTE } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const backendOf = (initial = {}) => { const map = new Map(Object.entries(initial));
    return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: (k) => { map.delete(k); } }; };
  const fresh = (backend = backendOf(), seed = 'snap', patrols = [[100, 60, 6, 4]]) => {
    const storage = createStorage(backend); const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed });
    game.level.patrols.length = 0; for (const [x, y, vx, vy] of patrols) game.level.patrols.push(makePatrol(x, y, vx, vy));
    return { game, storage, backend }; };
  const reload = (backend) => { const game = new Game({ storage: createStorage(backend) }); game.enterTitle(); return game; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  const colCells = (game, unitX) => { const g = game.grid, x = Math.floor(unitX * 2), cells = []; for (let y = 0; y < g.h; y++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); return cells; };
  const stored = (backend) => { const raw = backend.map.get(SNAPSHOT_KEY); return raw ? JSON.parse(raw) : null; };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "\n}", arg)      # the newline: a comment on the body's last line must not swallow the brace


@pytest.fixture
def page(open_page):
    return open_page()


# ---- the grid, run-length encoded --------------------------------------------------------------------
def test_the_grid_encoding_round_trips_and_is_compact(page):
    got = js(page, """
      let seed = 12345; const rnd = () => (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296;
      const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
      const out = { random: [], edges: {} };
      for (let t = 0; t < 30; t++) {                                     // random grids with runs of every length
        const cells = new Uint8Array(GRID_W * GRID_H); let i = 0;
        while (i < cells.length) { const k = Math.floor(rnd() * 3), n = 1 + Math.floor(rnd() ** 3 * 4000); cells.fill(k, i, i + n); i += n; }
        const back = new Uint8Array(cells.length).fill(9);
        out.random.push(snap.decodeGrid(snap.encodeGrid(cells), back) && same(cells, back));
      }
      const all = (k) => { const c = new Uint8Array(GRID_W * GRID_H).fill(k); const back = new Uint8Array(c.length);
        return { ok: snap.decodeGrid(snap.encodeGrid(c), back) && same(c, back), pairs: snap.encodeGrid(c).length / 2 }; };
      out.edges = { field: all(FIELD), wall: all(WALL), border: all(BORDER) };
      const worst = new Uint8Array(GRID_W * GRID_H); for (let i = 0; i < worst.length; i++) worst[i] = i % 2;      // no runs at all
      const back = new Uint8Array(worst.length); out.worst = { ok: snap.decodeGrid(snap.encodeGrid(worst), back) && same(worst, back), numbers: snap.encodeGrid(worst).length };
      const { game } = fresh(); out.level1 = snap.encodeGrid(game.grid.cells).length;
      for (const x of [20, 40, 60]) game.commitCapture(colCells(game, x)); out.afterCaptures = snap.encodeGrid(game.grid.cells).length;
      const withRoute = game.grid.cells.slice(); withRoute[withRoute.findIndex((v) => v === FIELD)] = ROUTE;
      const enc = snap.encodeGrid(withRoute); const dec = new Uint8Array(withRoute.length); snap.decodeGrid(enc, dec);
      out.routeBecomesField = dec.every((v) => v !== ROUTE) && dec.filter((v) => v === FIELD).length === game.grid.cells.filter((v) => v === FIELD).length;
      return out;""")
    assert all(got['random'])
    assert all(got['edges'][k]['ok'] and got['edges'][k]['pairs'] == 1 for k in ('field', 'wall', 'border'))
    assert got['worst']['ok'] and got['worst']['numbers'] == 240 * 144 * 2                                # even the worst case is only ~69k numbers
    # A fresh board, row by row: one run for the frame's top four rows plus the first left edge, then for each of the 136 open
    # rows a FIELD run and a BORDER run (this row's right edge joined to the next row's left edge), the last joined to the
    # bottom frame: 1 + 136 x 2 = 273 runs = 546 numbers. Captured ground adds a few runs a row, not more.
    assert got['level1'] == 546 and 546 < got['afterCaptures'] < 2000
    assert got['routeBecomesField'] is True


def test_decoding_rejects_anything_that_is_not_a_whole_valid_grid_and_touches_nothing(page):
    got = js(page, """
      const bad = { 'null': null, 'empty': [], 'string': 'abc', 'odd length': [0, 10, 1], 'total too small': [0, 10], 'total too big': [0, 10, 1, 11],
        'a route cell': [0, 10, 3, 10], 'unknown kind': [4, 20], 'kind as text': ['0', 20], 'zero run': [0, 0, 0, 20], 'negative run': [0, -5, 0, 25],
        'fractional run': [0, 1.5, 0, 18.5], 'NaN run': [0, NaN, 0, 20], 'overflow': [0, 20, 1, 5], 'object': { length: 4 } };
      const out = {};
      for (const [name, rle] of Object.entries(bad)) {
        const target = new Uint8Array(20).fill(7);
        out[name] = { ok: snap.decodeGrid(rle, target), untouched: target.every((v) => v === 7) };
      }
      return out;""")
    for name, result in got.items():
        assert result == {'ok': False, 'untouched': True}, name


# ---- validation: everything read back is untrusted ---------------------------------------------------------
def test_a_snapshot_is_accepted_only_when_every_field_is_sound(page):
    got = js(page, """
      const now = Date.UTC(2026, 8, 19, 12, 0, 0), HOUR = 3600 * 1000;
      const { game } = fresh(backendOf(), 'validate', [[100, 60, 6, 4], [30, 20, -7, 6]]);
      game.commitCapture(colCells(game, 20), { polyline: [10, 1, 10, 71] }); game.commitCapture(colCells(game, 40));
      const good = JSON.parse(JSON.stringify(snap.takeSnapshot(game, now)));
      const edit = (fn) => { const c = JSON.parse(JSON.stringify(good)); fn(c); return c; };
      const opts = { now, today: '2026-09-19' };
      const accepts = (raw, o = opts) => snap.validateSnapshot(raw, o) !== null;
      const out = { good: accepts(good), rejected: {}, accepted: {} };
      const bad = {
        'version': (c) => { c.v = 2; }, 'app major': (c) => { c.app = '2.0.0'; }, 'app not text': (c) => { c.app = 5; },
        'older than 24 h': (c) => { c.savedAt = now - 24 * HOUR - 1; }, 'from the future': (c) => { c.savedAt = now + HOUR + 1; }, 'no time': (c) => { c.savedAt = NaN; },
        'unknown mode': (c) => { c.mode = 'x'; }, 'the tutorial': (c) => { c.mode = 'tutorial'; }, 'empty seed': (c) => { c.seed = ''; }, 'numeric seed': (c) => { c.seed = 12; },
        'daily without a day': (c) => { c.mode = 'daily'; c.dayKey = null; }, 'daily from another day': (c) => { c.mode = 'daily'; c.dayKey = '2026-09-18'; },
        'level 0': (c) => { c.level = 0; }, 'level 1.5': (c) => { c.level = 1.5; }, 'level 10000': (c) => { c.level = 10000; }, 'fresh as text': (c) => { c.fresh = 'no'; },
        'no run': (c) => { delete c.run; }, 'zero lives': (c) => { c.run.lives = 0; }, 'six lives': (c) => { c.run.lives = 6; }, 'half a life': (c) => { c.run.lives = 2.5; },
        'negative score': (c) => { c.run.score = -1; }, 'fractional score': (c) => { c.run.score = 1.5; }, 'life threshold behind the score': (c) => { c.run.nextLifeAt = c.run.score; },
        'combo 1.1': (c) => { c.run.combo = 1.1; }, 'combo 0.5': (c) => { c.run.combo = 0.5; }, 'combo 3.25': (c) => { c.run.combo = 3.25; }, 'combo as text': (c) => { c.run.combo = '2'; },
        'no stats': (c) => { delete c.run.stats; }, 'negative stats': (c) => { c.run.stats.captures = -1; }, 'no best0': (c) => { delete c.run.best0; }, 'best clear over 100': (c) => { c.run.best0.clear = 101; },
        'no patrols': (c) => { c.patrols = []; }, 'nine patrols': (c) => { c.patrols = Array(9).fill(c.patrols[0]); }, 'NaN patrol': (c) => { c.patrols[0][2] = NaN; },
        'patrol off the board': (c) => { c.patrols[0][0] = 500; }, 'short patrol': (c) => { c.patrols[0] = [1, 2, 3]; }, 'patrol as text': (c) => { c.patrols[0][1] = '5'; },
        'odd route': (c) => { c.routes[0] = [1, 2, 3]; }, 'route with NaN': (c) => { c.routes[0][1] = NaN; }, 'far too many routes': (c) => { c.routes = Array(201).fill([1, 1, 2, 2]); },
        'grid not a list': (c) => { c.grid = 'x'; }, 'grid absurdly long': (c) => { c.grid = Array(GRID_W * GRID_H * 2 + 2).fill(0); },
        'negative clock': (c) => { c.clock = -1; }, 'clock of a week': (c) => { c.clock = 7 * 24 * 3600; },
        'level start score above the score': (c) => { c.scoreAtStart = c.run.score + 1; }, 'no level start stats': (c) => { delete c.statsAtStart; },
      };
      for (const [name, fn] of Object.entries(bad)) out.rejected[name] = accepts(edit(fn));
      out.accepted = {
        'exactly 24 h old': accepts(edit((c) => { c.savedAt = now - 24 * HOUR })), 'just under an hour ahead': accepts(edit((c) => { c.savedAt = now + HOUR - 1 })),
        'a daily on its own day': accepts(edit((c) => { c.mode = 'daily'; c.dayKey = '2026-09-19'; })),
        'a win-screen save needs no grid': accepts(edit((c) => { c.fresh = true; delete c.grid; delete c.patrols; delete c.routes; delete c.clock; delete c.scoreAtStart; delete c.statsAtStart; })),
      };
      // the result is a clean copy: unknown keys are dropped and the input is left alone
      const dirty = edit((c) => { c.evil = 1; c.run.evil = 2; c.patrols[0].push(99); }); out.dirtyRejected = !accepts(dirty);   // an extra patrol number is malformed
      const withExtras = edit((c) => { c.evil = 1; c.run.evil = 2; }); const cleaned = snap.validateSnapshot(withExtras, opts);
      out.clean = { noEvil: cleaned.evil === undefined && cleaned.run.evil === undefined, copy: cleaned !== withExtras && cleaned.run !== withExtras.run && cleaned.patrols !== withExtras.patrols };
      return out;""")
    assert got['good'] is True
    accepted_by_mistake = [name for name, ok in got['rejected'].items() if ok]
    assert accepted_by_mistake == [], f'these damaged snapshots were accepted: {accepted_by_mistake}'
    assert len(got['rejected']) >= 46                                                                     # the table itself must not be quietly shortened
    assert got['accepted'] == {'exactly 24 h old': True, 'just under an hour ahead': True, 'a daily on its own day': True, 'a win-screen save needs no grid': True}
    assert got['dirtyRejected'] is True and got['clean'] == {'noEvil': True, 'copy': True}


# ---- restoring ------------------------------------------------------------------------------------------------
def test_a_restored_game_is_the_same_game_and_plays_on_identically(page):
    got = js(page, """
      const backend = backendOf();
      const a = fresh(backend, 'fidelity', [[100, 60, 9, 5], [30, 20, -7, 6], [60, 40, 4, -8]]);
      const A = a.game;
      A.commitCapture(colCells(A, 8), { polyline: [8, 1, 8, 71] }); run(A, 1.5);
      A.loseLife(); run(A, 0.7);
      A.commitCapture(colCells(A, 14), { polyline: [14, 1, 13, 40, 14, 71] }); run(A, 2.3);
      A.persist();
      const B = reload(backend);                                          // a fresh page on the same storage
      const offered = B.saved && { level: B.saved.level, score: B.saved.run.score, lives: B.saved.run.lives };
      const resumed = B.resumeRun();
      const out = { offered, resumed, phase: B.phase, reason: B.pauseReason, savedAfter: B.saved };
      const patrols = (g) => g.level.patrols.map((p) => [p.x, p.y, p.vx, p.vy, p.heading, p.speed]);
      out.grid = A.grid.cells.length === B.grid.cells.length && A.grid.cells.every((v, i) => v === B.grid.cells[i]);
      out.patrols = JSON.stringify(patrols(A)) === JSON.stringify(patrols(B));
      const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === 'object' && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort()) : x));     // the order keys were added in is not part of a run
      const runOf = (g) => canon({ ...g.run, dayKey: undefined });
      out.run = runOf(A) === runOf(B);
      out.level = JSON.stringify([A.level.number, A.level.cleared, A.level.scoreAtStart, A.level.statsAtStart, A.level.routes, A.level.initialPlayable, A.clock.now]) ===
                  JSON.stringify([B.level.number, B.level.cleared, B.level.scoreAtStart, B.level.statsAtStart, B.level.routes, B.level.initialPlayable, B.clock.now]);
      out.obstaclesAndFrame = JSON.stringify(A.level.obstacles) === JSON.stringify(B.level.obstacles);
      B.tick(3.1); out.afterCountdown = B.phase;                           // the 3-2-1 runs on real time
      run(A, 2); run(B, 2);                                                 // and from here both games must stay in lock step
      out.stillSame = JSON.stringify(patrols(A)) === JSON.stringify(patrols(B));
      const before = B.level.cleared; B.commitCapture(colCells(B, 30)); A.commitCapture(colCells(A, 30));
      out.captureSame = A.run.score === B.run.score && A.level.cleared === B.level.cleared && before < B.level.cleared;
      return out;""")
    assert got['offered']['level'] == 1 and got['offered']['lives'] == 2 and got['offered']['score'] > 0
    assert got['resumed'] is True and got['phase'] == 'countdown' and got['reason'] == 'restored' and got['savedAfter'] is None
    assert got['grid'] and got['patrols'] and got['run'] and got['level'] and got['obstaclesAndFrame']
    assert got['afterCountdown'] == 'playing' and got['stillSame'] and got['captureSame']


def test_new_best_flags_are_judged_against_the_records_the_run_began_with_even_after_a_resume(page):
    got = js(page, """
      const finish = (before) => {                                               // start with these records, score 3,927, get interrupted, resume, lose
        const backend = backendOf(); const storage = createStorage(backend); storage.updateRecords((r) => Object.assign(r, before));
        const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed: 'best' });
        game.level.patrols.length = 0; game.level.patrols.push(makePatrol(100, 60, 0, 0));
        game.commitCapture(colCells(game, 40));                                   // 3,927 points, 33.19%
        const B = reload(backend); B.resumeRun(); B.tick(3.1);
        B.loseLife(); B.loseLife(); B.loseLife();
        return { newBest: B.report.newBest, kept: { ...B.run.best0 } };
      };
      return { beatenBefore: finish({ bestScore: 1000, bestClear: 10, bestLevel: 0 }),      // this run beat them before the interruption: still a record after it
               notBeaten: finish({ bestScore: 5000, bestClear: 50, bestLevel: 0 }) };       // this run did not: no record, whatever the live records say now""")
    assert got['beatenBefore']['newBest'] == {'score': True, 'clear': True, 'level': False}
    assert got['beatenBefore']['kept'] == {'score': 1000, 'clear': 10, 'level': 0}
    assert got['notBeaten']['newBest'] == {'score': False, 'clear': False, 'level': False}
    assert got['notBeaten']['kept'] == {'score': 5000, 'clear': 50, 'level': 0}


def test_a_route_in_progress_is_never_saved(page):
    got = js(page, """
      const { game, backend } = fresh(backendOf(), 'route');
      const r = game.route; r.begin(40, 1); r.move(40, 30);                 // half a route, live in the grid
      const live = game.grid.cells.filter((v) => v === ROUTE).length;
      game.persist();
      const cells = new Uint8Array(GRID_W * GRID_H); snap.decodeGrid(stored(backend).grid, cells);
      return { live, savedRouteCells: cells.filter((v) => v === ROUTE).length, savedField: cells.filter((v) => v === FIELD).length, fieldNow: game.grid.cells.filter((v) => v === FIELD).length + live };""")
    assert got['live'] > 30 and got['savedRouteCells'] == 0 and got['savedField'] == got['fieldNow']


def test_the_win_screen_resumes_into_the_next_level_from_its_start(page):
    got = js(page, """
      const backend = backendOf(); const { game } = fresh(backend, 'win', []);
      game.commitCapture(colCells(game, 40));                               // no patrol: the whole field, so a win
      const wasWin = game.phase; const score = game.run.score, lives = game.run.lives;
      const s = stored(backend);
      const B = reload(backend); B.resumeRun(); const out = { wasWin, saved: { level: s.level, fresh: s.fresh, hasGrid: 'grid' in s } };
      B.tick(3.1);
      out.resumed = { phase: B.phase, level: B.level.number, score: B.run.score, lives: B.run.lives, cleared: B.level.cleared, field: B.grid.countField() === B.level.initialPlayable, scoreAtStart: B.level.scoreAtStart, combo: B.run.combo };
      out.expected = { score, lives };
      return out;""")
    assert got['wasWin'] == 'clear' and got['saved'] == {'level': 2, 'fresh': True, 'hasGrid': False}
    assert got['resumed']['phase'] == 'playing' and got['resumed']['level'] == 2 and got['resumed']['cleared'] == 0 and got['resumed']['field'] is True
    assert got['resumed']['score'] == got['expected']['score'] and got['resumed']['lives'] == got['expected']['lives']
    assert got['resumed']['scoreAtStart'] == got['resumed']['score'] and got['resumed']['combo'] == 1


def test_a_save_that_looks_valid_but_has_the_wrong_grid_size_is_dropped_not_trusted(page):
    got = js(page, """
      const backend = backendOf(); const { game } = fresh(backend, 'size'); game.persist();
      const s = stored(backend); s.grid = [0, 100];                          // right shape, nowhere near a full grid
      backend.map.set(SNAPSHOT_KEY, JSON.stringify(s));
      const B = reload(backend); const offered = !!B.saved; const resumed = B.resumeRun();
      return { offered, resumed, phase: B.phase, left: backend.map.has(SNAPSHOT_KEY), run: B.run };""")
    assert got == {'offered': True, 'resumed': False, 'phase': 'title', 'left': False, 'run': None}


# ---- when a run is saved and forgotten -------------------------------------------------------------------------------
def test_a_run_is_saved_whenever_it_changes_for_good_and_forgotten_when_it_ends(page):
    got = js(page, """
      const backend = backendOf(); const out = {};
      const { game } = fresh(backend, 'events', [[100, 60, 0, 0]]);
      game.persist(); out.started = stored(backend) && { level: stored(backend).level, score: stored(backend).run.score };
      game.commitCapture(colCells(game, 40)); out.afterCapture = stored(backend).run.score;
      game.loseLife(); out.afterHit = stored(backend).run.lives;             // a hit is saved at once: reloading cannot undo it
      const ledger = stored(backend).run.lives;
      const B = reload(backend); out.reloadedLives = B.saved.run.lives;      // ...so the life is not handed back
      game.restartLevel(); out.afterRestart = { score: stored(backend).run.score, lives: stored(backend).run.lives, grid: stored(backend).grid.length };
      game.loseLife(); game.loseLife(); out.afterGameOver = { phase: game.phase, kept: backend.map.has(SNAPSHOT_KEY) };
      game.persist(); out.persistAfterOver = backend.map.has(SNAPSHOT_KEY);   // saving a finished run must not bring it back
      game.newRun({ seed: 'again' }); out.newRun = stored(backend) && stored(backend).seed;
      return out;""")
    assert got['started'] == {'level': 1, 'score': 0}
    assert got['afterCapture'] > 0 and got['afterHit'] == 2 and got['reloadedLives'] == 2
    assert got['afterRestart']['lives'] == 2 and got['afterRestart']['score'] == 0
    assert got['afterGameOver'] == {'phase': 'over', 'kept': False} and got['persistAfterOver'] is False
    assert got['newRun'] == 'again'


def test_the_title_screen_and_the_tutorial_never_delete_a_saved_run(page):
    got = js(page, """
      const backend = backendOf(); const { game } = fresh(backend, 'keep'); game.persist();
      const title = reload(backend); title.persist();                        // hiding the tab on the title screen saves what there is: nothing
      const still = backend.map.has(SNAPSHOT_KEY);
      const tut = fresh(backend, 'tutorial'); tut.game.run.mode = 'tutorial';
      const tutorialSnapshot = snap.takeSnapshot(tut.game);
      return { still, tutorialSnapshot, offered: !!title.saved };""")
    assert got == {'still': True, 'tutorialSnapshot': None, 'offered': True}


def test_a_hostile_or_damaged_store_cannot_break_saving_or_loading(page):
    got = js(page, """
      const out = {};
      const hostile = { getItem() { throw new Error('denied'); }, setItem() { throw new DOMException('full', 'QuotaExceededError'); }, removeItem() { throw new Error('denied'); } };
      const s = createStorage(hostile); const game = new Game({ storage: s }); game.enterTitle(); game.newRun({ seed: 'h' });
      game.commitCapture(colCells(game, 40)); game.persist();                // none of this may throw
      out.playedOn = game.phase; out.persistent = s.persistent; out.loaded = s.loadSnapshot();
      const damaged = backendOf({ [SNAPSHOT_KEY]: '{nope' }); const g2 = reload(damaged);
      out.damaged = { offered: g2.saved, stillThere: damaged.map.has(SNAPSHOT_KEY) };
      const alien = backendOf({ [SNAPSHOT_KEY]: JSON.stringify({ hello: 'world' }) }); const g3 = reload(alien);
      out.alien = { offered: g3.saved, stillThere: alien.map.has(SNAPSHOT_KEY) };
      const old = fresh(backendOf(), 'old'); old.game.persist(); const raw = stored(old.backend); raw.savedAt = Date.now() - 25 * 3600 * 1000;
      old.backend.map.set(SNAPSHOT_KEY, JSON.stringify(raw)); const g4 = reload(old.backend);
      out.stale = { offered: g4.saved, stillThere: old.backend.map.has(SNAPSHOT_KEY) };
      const dailyOld = fresh(backendOf(), 'daily'); dailyOld.game.run.mode = 'daily'; dailyOld.game.run.dayKey = '2001-01-01'; dailyOld.game.persist();
      const g5 = reload(dailyOld.backend); out.dailyOtherDay = { offered: g5.saved, stillThere: dailyOld.backend.map.has(SNAPSHOT_KEY) };
      return out;""")
    assert got['playedOn'] == 'playing' and got['persistent'] is False and got['loaded'] is None
    for case in ('damaged', 'alien', 'stale', 'dailyOtherDay'):
        assert got[case] == {'offered': None, 'stillThere': False}, case      # dropped from the title and from storage


# ---- the whole path a player takes -----------------------------------------------------------------------------------------
def hide(page):
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'));")


def test_hiding_the_page_reloading_and_tapping_resume_puts_the_run_back(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate('__pp.game.newRun({ seed: "resume" }); __pp.setPatrols([{ x: 100, y: 60, vx: 6, vy: 4 }]); __pp.cutLine("v", 40)')
    page.evaluate('__pp.freeze(true); __pp.step(90)')            # the patrol moves on after the capture, so only saving on hide can keep where it is
    before = page.evaluate('({ ...__pp.state(), score: __pp.game.run.score })')
    assert before['cleared'] == pytest.approx(33.19, abs=0.01) and before['score'] == 3927
    hide(page)                                                    # a tab swiped away: paused, and saved
    assert page.evaluate('__pp.state().phase') == 'paused' and page.evaluate(f"localStorage.getItem('{KEY}')") is not None
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#resumeRunButton').is_visible() and page.locator('#savedLine').is_visible()
    assert page.locator('#savedLine').text_content().startswith('saved run: level 01 · 3,927 points · ')
    assert 'btn--primary' not in page.locator('#startButton').get_attribute('class')       # Resume leads, Start run steps back
    assert page.evaluate('document.activeElement.id') == 'resumeRunButton'                # and a keyboard user lands on it
    page.click('#resumeRunButton')
    assert page.evaluate('__pp.state().phase') == 'countdown' and page.locator('#pauseOverlay').is_visible()
    assert page.evaluate('__pp.state().patrols') == before['patrols']                       # exactly where it was when the page was hidden
    page.wait_for_function("__pp.state().phase === 'playing'", timeout=6000)
    after = page.evaluate('({ ...__pp.state(), score: __pp.game.run.score })')
    assert (after['level'], after['lives'], after['score']) == (before['level'], before['lives'], before['score'])
    assert after['cleared'] == pytest.approx(before['cleared'], abs=1e-9)
    assert page.locator('#scoreLabel').inner_text() == '3,927'
    page.reload()                                                 # the resumed run is still saved...
    page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#resumeRunButton').is_visible()
    page.click('#startButton')                                    # ...until a new run replaces it
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('__pp.game.run.score') == 0
    assert json.loads(page.evaluate(f"localStorage.getItem('{KEY}')"))['run']['score'] == 0
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#savedLine').text_content().startswith('saved run: level 01 · 0 points')


def test_a_finished_run_leaves_nothing_to_resume(open_page):
    page = open_page()
    page.evaluate('__pp.game.newRun({ seed: "over" })')
    for _ in range(3):
        page.evaluate('__pp.game.loseLife()')
    assert page.evaluate(f"localStorage.getItem('{KEY}')") is None
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#resumeRunButton').is_hidden() and page.locator('#savedLine').is_hidden()
    assert 'btn--primary' in page.locator('#startButton').get_attribute('class')
