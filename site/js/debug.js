/* Test hooks, loaded only when the URL has ?debug=1. They expose the game's internals as window.__pp so
   automated tests can put the game into a known state and read it back. Nothing here ships in normal play. */
import { STEP } from './config.js';
import { FIELD, ROUTE, toCell } from './grid.js';
import { boardToFraction } from './view.js';
import { makePatrol } from './physics.js';

export function install({ game, view, renderer, ui, storage, loop, sound, haptics }) {
  const pp = {
    game, view, renderer, ui, storage, loop, sound, haptics, fx: renderer.fx,

    /* Plain-data snapshot of everything a test usually asserts on. */
    state() {
      const level = game.level;
      return {
        phase: game.phase,
        pauseReason: game.pauseReason,
        countdown: game.countdown,
        lives: game.run ? game.run.lives : null,
        mode: game.run ? game.run.mode : null,
        level: level ? level.number : null,
        cleared: level ? level.cleared : null,
        target: level ? level.info.target : null,
        patrols: level ? level.patrols.map((p) => ({ x: p.x, y: p.y, vx: p.vx, vy: p.vy })) : [],
        obstacles: level ? level.obstacles.map((o) => ({ ...o })) : [],
        openCells: game.grid.countField(),
        clock: { now: game.clock.now, pending: game.clock.pending, epoch: game.clock.epoch },
        flash: game.flash,
        frames: renderer.frames,
        persistent: storage.persistent,
        fit: view.fit && { rotated: view.fit.rotated, cssW: view.fit.cssW, cssH: view.fit.cssH, pxW: view.fit.pxW, pxH: view.fit.pxH },
      };
    },

    cell: (x, y) => game.grid.get(x, y),

    /* The route engine's state, and how many ROUTE cells the grid really holds (they must agree). */
    route() {
      const r = game.route;
      return { mode: r.mode, down: r.down, cells: r.cells.length, points: r.points.length / 2, gridRouteCells: game.grid.count(ROUTE),
               anchor: { ...r.anchor }, tip: { ...r.tip }, polylines: game.level ? game.level.routes.length : 0 };
    },

    /* Board units -> viewport pixels, whatever the rotation: where a test should press to hit that spot. */
    toClient(x, y) {
      const f = boardToFraction(view.fit.rotated, x, y);
      const r = view.canvas.getBoundingClientRect();
      return { x: r.left + f.u * r.width, y: r.top + f.v * r.height };
    },

    /* Hold the simulation still (the loop keeps drawing) and advance it by hand. */
    freeze(on = true) { loop.frozen = on; },
    step(n = 1) { for (let i = 0; i < n; i++) game.step(STEP); renderer.invalidate(); },

    /* Replace the patrols with exactly these: [{ x, y, vx, vy }, ...] in world units. */
    setPatrols(list) {
      game.level.patrols.length = 0;
      for (const p of list) game.level.patrols.push(makePatrol(p.x, p.y, p.vx || 0, p.vy || 0));
      game.emit('hud');
    },

    /* Claim everything on one side of a full-width straight cut: axis 'h' at y, or 'v' at x (world units). */
    cutLine(axis, at) {
      const cells = [];
      const g = game.grid;
      if (axis === 'h') { const y = toCell(at); for (let x = 0; x < g.w; x++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); }
      else { const x = toCell(at); for (let y = 0; y < g.h; y++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); }
      return game.commitCapture(cells);
    },

    /* Win the level as if the last route had just closed. */
    forceWin() {
      game.level.patrols.length = 0;                 // no patrol left to protect, so the cut claims it all
      return pp.cutLine('h', 36);
    },
  };
  window.__pp = pp;
  document.documentElement.dataset.ppReady = '1';
}
