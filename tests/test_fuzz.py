"""Fuzz the whole game. A bot plays for a few minutes of game time per seed: it draws random freehand routes
from random points on the frame (some close, some are lifted early, some run into patrols, some cross
themselves), pauses, restarts levels, loses lives and starts new runs, while every step and every action is
checked against the invariants of the system. Deterministic: the same seeds give the same games."""
import pytest

FUZZ = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { FIELD, ROUTE, SOLID_MASK } = await import('/js/grid.js');
  const { STEP, PATROL_RADIUS: R } = await import('/js/config.js');
  const rngOf = (seed) => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const out = { games: 0, steps: 0, actions: 0, routesStarted: 0, closed: 0, lifted: 0, hits: 0, captures: 0, restarts: 0, pauses: 0,
                levelsCleared: 0, gameOvers: 0, shallow: 0, problems: [] };
  const note = (m) => { if (out.problems.length < 6) out.problems.push(m); };

  for (const seed of arg.seeds) {
    const rnd = rngOf(seed * 7919 + 13);
    const game = new Game({ storage: createStorage(memoryBackend()) });
    game.enterTitle(); game.newRun({ seed: 'fuzz-' + seed }); game.startLevel(1 + (seed % 9));
    out.games++;
    const route = game.route; let clearedInLevel = 0, lastLevel = game.level;
    game.on('route', (e) => { if (e.type === 'cancel') out.lifted++; else if (e.type === 'hit') out.hits++; else if (e.type === 'start') out.routesStarted++; });
    game.on('capture', (c) => {
      out.captures++;
      // every open cell must be reachable from some patrol: an area with no patrol in it is always claimed
      const g = game.grid, seen = new Uint8Array(g.w * g.h), queue = []; for (const i of game._patrolSeeds()) if (g.cells[i] === FIELD && !seen[i]) { seen[i] = 1; queue.push(i); }
      for (let h = 0; h < queue.length; h++) { const i = queue[h], cx = i % g.w; for (const j of [cx > 0 ? i - 1 : -1, cx < g.w - 1 ? i + 1 : -1, i - g.w, i + g.w]) if (j >= 0 && j < g.cells.length && !seen[j] && g.cells[j] === FIELD) { seen[j] = 1; queue.push(j); } }
      if (queue.length !== g.countField()) note(`seed ${seed}: ${g.countField() - queue.length} open cells have no patrol to reach them after a capture`);
      const expect = (1 - g.countField() / game.level.initialPlayable) * 100; if (Math.abs(expect - game.level.cleared) > 1e-6) note(`seed ${seed}: cleared % is stale`);
    });
    game.on('clear', () => { out.levelsCleared++; });
    game.on('over', () => { out.gameOvers++; });

    const check = (where) => {
      const g = game.grid, level = game.level;
      if (g.count(ROUTE) !== route.cells.length) note(`seed ${seed} ${where}: ${g.count(ROUTE)} ROUTE cells in the grid, engine has ${route.cells.length}`);
      if (game.run && (game.run.lives < 0 || game.run.lives > 3)) note(`seed ${seed} ${where}: lives ${game.run.lives}`);
      if (!['playing', 'paused', 'clear', 'over', 'countdown'].includes(game.phase)) note(`seed ${seed} ${where}: phase ${game.phase}`);
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
      const [x, y] = corners(); const targets = []; for (let k = 0, n = Math.floor(rnd() * 3); k < n; k++) targets.push([10 + rnd() * 100, 8 + rnd() * 56]); targets.push(corners());
      route.begin(x, y, rnd() < 0.3 ? 2 : 0); bot = { x, y, targets, lifeAt: rnd() < 0.3 ? 4 + Math.floor(rnd() * 25) : 1e9, moves: 0 };
    };
    for (let i = 0; i < 2400; i++) {                                   // 20 seconds of game time
      const n = 1 + Math.floor(rnd() * 3); for (let k = 0; k < n; k++) { game.step(STEP); out.steps++; }
      check('after a step');
      if (game.phase === 'over') { game.newRun({ seed: 'fuzz-' + seed + '-' + i }); game.startLevel(1 + Math.floor(rnd() * 8)); route.end('cancel'); bot = null; continue; }
      const roll = rnd();
      if (roll < 0.004 && game.isPlaying()) { game.pause('manual'); out.pauses++; check('after a pause'); game.resume(); if (game.phase === 'countdown') game.resume(); bot = null; }
      else if (roll < 0.006) { if (game.restartLevel()) { out.restarts++; bot = null; check('after a restart'); } }
      else if (bot === null) { if (rnd() < 0.09 && game.isPlaying()) startBot(); }
      else {
        out.actions++;
        const [tx, ty] = bot.targets[0]; const dx = tx - bot.x, dy = ty - bot.y, d = Math.hypot(dx, dy), step = 1 + rnd() * 5;
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
