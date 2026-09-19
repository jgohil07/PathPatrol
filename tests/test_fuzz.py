"""Fuzz the whole game. A bot plays for a few minutes of game time per seed: it draws random freehand routes
from random points on the frame (some close, some are lifted early, some run into patrols, some cross
themselves), pauses, restarts levels, loses lives and starts new runs, while every step and every action is
checked against the invariants of the system. Deterministic: the same seeds give the same games."""
import pytest

FUZZ = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { FIELD, ROUTE, SOLID_MASK } = await import('/js/grid.js');
  const { STEP, PATROL_RADIUS: R, START_LIVES, MAX_LIVES, SCORE, levelInfo } = await import('/js/config.js');
  const { traceContours } = await import('/js/contour.js');
  const { POWER } = await import('/js/powerups.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const rngOf = (seed) => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const out = { games: 0, steps: 0, actions: 0, routesStarted: 0, closed: 0, lifted: 0, hits: 0, captures: 0, restarts: 0, pauses: 0,
                levelsCleared: 0, gameOvers: 0, shallow: 0, extraLives: 0, skips: 0, combosBroken: 0, tracerChases: 0, tracerCatches: 0, tracerLevels: 0, contourChecks: 0, saves: 0, dailyGames: 0, dailyOvers: 0, dailyCounted: 0, dailyPractice: 0,
                spawns: 0, expired: 0, freeze: 0, shield: 0, slow: 0, frozenChecks: 0, shieldedChecks: 0, slowChecks: 0, problems: [] };
  const note = (m) => { if (out.problems.length < 6) out.problems.push(m); };

  for (const seed of arg.seeds) {
    const rnd = rngOf(seed * 7919 + 13);
    const game = new Game({ storage: createStorage(memoryBackend()) });
    const isDaily = seed % 3 === 0;                                   // a third of the games are dailies, each on its own pinned day
    if (isDaily) { game.today = () => '2026-09-' + String(10 + (seed % 15)); out.dailyGames++; }
    const begin = (tag) => { if (isDaily) game.startDaily(); else game.newRun({ seed: 'fuzz-' + seed + tag }); };      // (a second daily on the same day is practice)
    game.enterTitle(); begin(''); game.startLevel(1 + ((seed * 7) % 24));           // levels 1-24: the whole curve, up to 8 patrols at 30 u/s
    out.games++;
    const save = game.persist.bind(game);                             // whatever the game writes, its own check must accept: a save it cannot read back loses the run
    game.persist = () => { save(); const raw = game.storage.loadSnapshot(); if (raw) { out.saves++; if (validateSnapshot(raw, { today: game.today() }) === null) note(`seed ${seed}: the game wrote a snapshot that its own check rejects`); } };
    const route = game.route; let clearedInLevel = 0, lastLevel = game.level;
    let lastRun = null, granted = 0, lastScore = 0;                  // extra lives granted in this run; the score a level has reached
    game.on('extraLife', () => { granted++; out.extraLives++; });
    game.on('combo', (c) => { if (c.broken) out.combosBroken++; });
    let frozenFor = null;                                             // patrol and tracer positions while a freeze holds (between captures)
    game.on('power', (e) => { if (e.type === 'spawn') out.spawns++; else if (e.type === 'expire') out.expired++; else if (e.type === 'start') out[e.kind]++; });
    if (seed % 2 === 0) {                                             // even seeds: a stress setting, pickups every few seconds instead of every 12-20
      const hurry = () => { game.powerups.nextAt = Math.min(game.powerups.nextAt, game.clock.now + 2 + rnd() * 3); };
      game.on('level', hurry);
      game.on('power', (e) => { if (e.type === 'spawn' || e.type === 'expire' || e.type === 'start') hurry(); });
      hurry();
    }
    game.on('tracer', (e) => { if (e.type === 'chase') out.tracerChases++; else if (e.type === 'caught') out.tracerCatches++; });
    game.on('route', (e) => { if (e.type === 'cancel') out.lifted++; else if (e.type === 'hit') out.hits++; else if (e.type === 'start') out.routesStarted++; });
    game.on('capture', (c) => {
      out.captures++; frozenFor = null;                               // a capture moves the boundary and settles patrols off the new walls: not what a freeze forbids
      // every open cell must be reachable from some patrol: an area with no patrol in it is always claimed
      const g = game.grid, seen = new Uint8Array(g.w * g.h), queue = []; for (const i of game._patrolSeeds()) if (g.cells[i] === FIELD && !seen[i]) { seen[i] = 1; queue.push(i); }
      for (let h = 0; h < queue.length; h++) { const i = queue[h], cx = i % g.w; for (const j of [cx > 0 ? i - 1 : -1, cx < g.w - 1 ? i + 1 : -1, i - g.w, i + g.w]) if (j >= 0 && j < g.cells.length && !seen[j] && g.cells[j] === FIELD) { seen[j] = 1; queue.push(j); } }
      if (queue.length !== g.countField()) note(`seed ${seed}: ${g.countField() - queue.length} open cells have no patrol to reach them after a capture`);
      const expect = (1 - g.countField() / game.level.initialPlayable) * 100; if (Math.abs(expect - game.level.cleared) > 1e-6) note(`seed ${seed}: cleared % is stale`);
      // the boundary the tracers crawl: every open-to-solid cell side is in exactly one loop, and the loops are what the game holds
      let sides = 0; const w = g.w, h = g.h; const solid = (x, y) => x < 0 || y < 0 || x >= w || y >= h || g.isSolid(x, y);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (!g.isSolid(x, y)) sides += solid(x, y - 1) + solid(x + 1, y) + solid(x, y + 1) + solid(x - 1, y);
      const traced = traceContours(g); out.contourChecks++;
      if (traced.edges !== sides || traced.loops.reduce((n, l) => n + l.n, 0) !== sides) note(`seed ${seed}: the contour has ${traced.edges} edges but the boundary has ${sides} sides`);
      if (game.tracers.loops.reduce((n, l) => n + l.n, 0) !== sides) note(`seed ${seed}: the tracers' loops are stale after a capture`);
    });
    game.on('clear', () => { out.levelsCleared++; });
    game.on('over', (report) => {
      out.gameOvers++;
      if (report.mode !== 'daily') { if (report.daily) note(`seed ${seed}: an ordinary run has a daily report`); return; }
      out.dailyOvers++;
      const d = report.daily, rec = game.storage.records.daily;
      if (!d) { note(`seed ${seed}: a daily ended with no daily report`); return; }
      if (d.counted !== (d.text !== null) || d.counted === d.practice) note(`seed ${seed}: the daily report contradicts itself (${JSON.stringify({ counted: d.counted, practice: d.practice, text: d.text !== null })})`);
      if (d.counted) { out.dailyCounted++; if (JSON.stringify(rec.result) !== JSON.stringify(d.result)) note(`seed ${seed}: the counted result was not kept`); } else out.dailyPractice++;
      if (!d.counted && d.result !== null) note(`seed ${seed}: a practice run has a result`);
      if (rec.best < rec.streak || (rec.result && !rec.last)) note(`seed ${seed}: the daily record is inconsistent ${JSON.stringify(rec)}`);
    });

    const check = (where) => {
      const g = game.grid, level = game.level;
      if (g.count(ROUTE) !== route.cells.length) note(`seed ${seed} ${where}: ${g.count(ROUTE)} ROUTE cells in the grid, engine has ${route.cells.length}`);
      const run = game.run;
      if (run !== lastRun) { lastRun = run; granted = 0; lastScore = 0; }                // a new run starts its own count
      if (run) {
        // lives only ever rise through an extra life, and never past the cap
        if (run.lives < 0 || run.lives > MAX_LIVES || run.lives > START_LIVES + granted) note(`seed ${seed} ${where}: lives ${run.lives} with ${granted} extra granted`);
        if (!Number.isInteger(run.score) || run.score < 0) note(`seed ${seed} ${where}: score ${run.score}`);
        if (level === lastLevel && run.score < lastScore) note(`seed ${seed} ${where}: score fell ${lastScore} -> ${run.score} inside a level`);
        lastScore = level === lastLevel ? Math.max(lastScore, run.score) : run.score;
        if (run.combo < 1 || run.combo > SCORE.combo.max || (run.combo * 4) % 1 !== 0) note(`seed ${seed} ${where}: combo ${run.combo}`);
        if (run.score >= run.nextLifeAt) note(`seed ${seed} ${where}: score ${run.score} is past the next life threshold ${run.nextLifeAt}`);
        if (game.storage.records.bestScore < run.score) note(`seed ${seed} ${where}: best score ${game.storage.records.bestScore} is below the score ${run.score}`);
        if (run.stats.captures < 0 || run.stats.closeCalls < 0 || run.stats.levelsCleared < 0) note(`seed ${seed} ${where}: negative stats`);
      }
      if (!['playing', 'paused', 'clear', 'over', 'countdown'].includes(game.phase)) note(`seed ${seed} ${where}: phase ${game.phase}`);
      // power-ups: one pickup at most, on open ground, and no timer longer than its duration
      const pu = game.powerups, now = game.clock.now;
      if (pu.pickup && (game.grid.get(Math.floor(pu.pickup.x * 2), Math.floor(pu.pickup.y * 2)) !== FIELD || pu.pickup.expires - now > POWER.lifetime + 1e-9)) note(`seed ${seed} ${where}: a pickup is on ground it cannot be on, or lives too long`);
      if (pu.pickup && !levelInfo(level.number).powerups) note(`seed ${seed} ${where}: a pickup on level ${level.number}`);
      for (const kind of POWER.kinds) if (pu.until[kind] !== undefined && pu.until[kind] - now > POWER[kind] + 1e-9) note(`seed ${seed} ${where}: ${kind} has ${pu.until[kind] - now} s left`);
      // a freeze really stops patrols and tracers (checked step to step while it holds)
      if (pu.active('freeze') && game.phase === 'playing') {
        const here = JSON.stringify([level.number, level.patrols.map((p) => [p.x, p.y]), game.tracers.list.map((t) => [t.x, t.y])]);
        out.frozenChecks++;
        if (frozenFor !== null && frozenFor.level === level && frozenFor.snapshot !== here) note(`seed ${seed} ${where}: something moved during a freeze`);
        frozenFor = { level, snapshot: here };
      } else frozenFor = null;
      if (pu.shielded) out.shieldedChecks++;
      if (pu.active('slow')) out.slowChecks++;
      // tracers: as many as the level has, each on a real loop and finite
      if (game.tracers.list.length !== levelInfo(level.number).tracers) note(`seed ${seed} ${where}: ${game.tracers.list.length} tracers on level ${level.number}`);
      for (const t of game.tracers.list) {
        const loop = game.tracers.loops[t.loop];
        if (!Number.isFinite(t.x + t.y + t.t)) note(`seed ${seed} ${where}: a tracer is not finite`);
        else if (loop ? !(t.t >= 0 && t.t < loop.n) : t.loop !== -1) note(`seed ${seed} ${where}: a tracer is on loop ${t.loop} at ${t.t}`);
      }
      if (level !== lastLevel) { lastLevel = level; clearedInLevel = 0; }                 // a new level or a restart: the tally starts again
      if (level.cleared < clearedInLevel - 1e-9 || level.cleared > 100 + 1e-9) note(`seed ${seed} ${where}: cleared went ${clearedInLevel} -> ${level.cleared}`);
      clearedInLevel = Math.max(clearedInLevel, level.cleared);
      for (const p of level.patrols) {
        if (!Number.isFinite(p.x + p.y + p.vx + p.vy)) { note(`seed ${seed} ${where}: a patrol is not finite`); continue; }
        if (Math.abs(Math.hypot(p.vx, p.vy) - p.speed) > 1e-9) note(`seed ${seed} ${where}: a patrol's speed drifted`);
        if (g.circleHitsSolid(p.x, p.y, R - 0.02)) note(`seed ${seed} ${where}: a patrol is inside a wall by more than 0.02`);
        else if (g.circleHitsSolid(p.x, p.y, R - 0.001)) out.shallow++;
        if (g.isSolid(Math.floor(p.x * 2), Math.floor(p.y * 2))) note(`seed ${seed} ${where}: a patrol's centre is inside a wall`);
      }
    };

    let bot = null;
    const corners = () => { const side = Math.floor(rnd() * 4), t = 4 + rnd() * 60; return side === 0 ? [4 + t * 1.7, 1] : side === 1 ? [4 + t * 1.7, 71] : side === 2 ? [1, t] : [119, t]; };
    const startBot = () => {
      const [x, y] = corners(); const targets = []; for (let k = 0, n = Math.floor(rnd() * 3); k < n; k++) targets.push([10 + rnd() * 100, 8 + rnd() * 56]);
      if (game.powerups.pickup && rnd() < 0.7) targets.unshift([game.powerups.pickup.x, game.powerups.pickup.y]);        // often, go and take a pickup
      targets.push(corners());
      route.begin(x, y, rnd() < 0.3 ? 2 : 0); bot = { x, y, targets, lifeAt: rnd() < 0.3 ? 4 + Math.floor(rnd() * 25) : 1e9, moves: 0, slow: rnd() < 0.2 };   // some routes are drawn slowly: tracers can catch those
    };
    for (let i = 0; i < 2400; i++) {                                   // 20 seconds of game time
      const n = 1 + Math.floor(rnd() * 3); for (let k = 0; k < n; k++) { game.step(STEP); out.steps++; }
      check('after a step');
      if (game.phase === 'over') { begin('-' + i); game.startLevel(1 + Math.floor(rnd() * 24)); route.end('cancel'); bot = null; continue; }
      const roll = rnd();
      if (game.tracers.list.length) out.tracerLevels++;
      if (roll < 0.004 && game.isPlaying()) { game.pause('manual'); out.pauses++; check('after a pause'); game.resume(); if (game.phase === 'countdown') game.resume(); bot = null; }
      else if (roll < 0.006) { const restarted = game.restartLevel(); if (restarted && game.run.mode === 'daily') note(`seed ${seed}: a daily was restarted`); if (restarted) { out.restarts++; bot = null; check('after a restart'); } }
      else if (game.phase === 'clear' && roll < 0.05) { if (game.skipClear()) out.skips++; check('after a skip'); }
      else if (bot === null) { if (rnd() < 0.09 && game.isPlaying()) startBot(); }
      else {
        out.actions++;
        const [tx, ty] = bot.targets[0]; const dx = tx - bot.x, dy = ty - bot.y, d = Math.hypot(dx, dy), step = bot.slow ? 0.03 + rnd() * 0.1 : 1 + rnd() * 5;
        if (d < step) { bot.targets.shift(); if (!bot.targets.length) { route.move(tx, ty); route.move(tx + (rnd() - 0.5) * 3, ty + (rnd() - 0.5) * 3); bot = null; route.end('lift'); out.closed++; check('after a route'); continue; } }
        else { bot.x += (dx / d) * step + (rnd() - 0.5) * 1.6; bot.y += (dy / d) * step + (rnd() - 0.5) * 1.6; route.move(bot.x, bot.y); }
        if (++bot.moves >= bot.lifeAt) { route.end('lift'); bot = null; }
        check('after a bot move');
      }
    }
  }
  return out;
"""


def test_a_bot_plays_hundreds_of_games_without_breaking_any_invariant(open_page):
    page = open_page()
    seeds = list(range(1, 25))
    got = page.evaluate("async (arg) => {" + FUZZ + "}", {'seeds': seeds})
    assert got['problems'] == [], got['problems']
    # the bot really did exercise the engine, not just idle
    assert got['games'] == 24 and got['steps'] > 100000
    assert got['routesStarted'] > 300 and got['captures'] > 100 and got['lifted'] > 30 and got['hits'] > 10
    assert got['restarts'] > 5 and got['pauses'] > 20 and got['gameOvers'] >= 1
    assert got['shallow'] < 40                                          # wedge residue (a hair inside a wall) stays rare
    assert got['combosBroken'] > 3                                      # abandoned routes broke combos, so that path was exercised too
    assert got['extraLives'] >= 1 and got['skips'] >= 1                 # and so were extra lives and skipping a win screen
    assert got['contourChecks'] == got['captures'] > 100                # every capture had its boundary checked against a brute-force count
    assert got['tracerLevels'] > 5000 and got['tracerChases'] >= 5 and got['tracerCatches'] >= 1     # tracers were on the board, noticed routes, and caught one
    assert got['spawns'] >= 20 and got['freeze'] >= 3 and got['shield'] >= 2 and got['slow'] >= 2        # every kind of power-up was taken...
    assert got['frozenChecks'] > 500 and got['shieldedChecks'] > 200 and got['slowChecks'] > 200          # ...and the invariants were checked while each held
    assert got['saves'] > 300                                           # and every save the games made was read back by the game's own check
    assert got['dailyGames'] == 8 and got['dailyOvers'] >= 4 and got['dailyCounted'] >= 2 and got['dailyPractice'] >= 2     # a third were dailies, and ended both ways
