/* Saving and restoring a run in progress, so a phone call, a swiped-away tab or a reload does not cost a run.

   What is saved is only what cannot be rebuilt: the level itself (frame, obstacles) is regenerated from
   (seed, number), so the snapshot holds the claimed territory (run-length encoded), the patrols, the finished
   routes, the clock and the score state. A route being drawn is never saved: it is erased by the pause that
   precedes every save, and encodeGrid turns any stray route cell back into open ground.

   Everything read back is untrusted (localStorage can hold anything), so validateSnapshot rebuilds a clean
   object field by field and returns null for the smallest doubt. A run that cannot be trusted is dropped. */
import { GRID_W, GRID_H, BOARD_W, BOARD_H, APP_VERSION, MAX_LIVES, SCORE, levelInfo } from './config.js';
import { FIELD, WALL, BORDER, ROUTE } from './grid.js';

export const SNAPSHOT_VERSION = 1;
export const SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const CLOCK_SKEW_MS = 60 * 60 * 1000;         // a save stamped further ahead than this is not believed
const MAX_PATROLS = 8;
const MAX_LEVEL = 9999;
const MAX_ROUTES = 200;
const MAX_ROUTE_POINTS = 4000;

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isCount = (v, max = Number.MAX_SAFE_INTEGER) => Number.isInteger(v) && v >= 0 && v <= max;
const isCoordinate = (v, max) => Number.isFinite(v) && v >= -1 && v <= max + 1;

/* --- the grid, run-length encoded ---------------------------------------------------------------------- */

/* [kind, length, kind, length, ...] over the whole grid in row order. ROUTE is saved as FIELD. */
export function encodeGrid(cells) {
  const out = [];
  let kind = -1, length = 0;
  for (let i = 0; i < cells.length; i++) {
    const v = cells[i] === ROUTE ? FIELD : cells[i];
    if (v === kind) { length++; continue; }
    if (length) out.push(kind, length);
    kind = v;
    length = 1;
  }
  if (length) out.push(kind, length);
  return out;
}

/* Writes the decoded grid into `cells` and returns true, or returns false and leaves `cells` untouched. */
export function decodeGrid(rle, cells) {
  if (!Array.isArray(rle) || rle.length === 0 || rle.length % 2 !== 0 || rle.length > cells.length * 2) return false;
  let total = 0;
  for (let i = 0; i < rle.length; i += 2) {
    const kind = rle[i], length = rle[i + 1];
    if (kind !== FIELD && kind !== WALL && kind !== BORDER) return false;      // never ROUTE: a route is not resumed
    if (!Number.isInteger(length) || length < 1) return false;
    total += length;
    if (total > cells.length) return false;
  }
  if (total !== cells.length) return false;
  let at = 0;
  for (let i = 0; i < rle.length; i += 2) {
    cells.fill(rle[i], at, at + rle[i + 1]);
    at += rle[i + 1];
  }
  return true;
}

/* --- taking a snapshot ------------------------------------------------------------------------------------ */

/* null when there is nothing worth resuming: no run, the tutorial, or a run that has ended. */
export function takeSnapshot(game, now = Date.now()) {
  const { run, level, phase } = game;
  if (!run || !level || run.mode === 'tutorial') return null;
  if (phase !== 'playing' && phase !== 'paused' && phase !== 'countdown' && phase !== 'clear') return null;
  const base = {
    v: SNAPSHOT_VERSION, app: APP_VERSION, savedAt: now,
    mode: run.mode, seed: run.seed, dayKey: run.dayKey || null,
    run: { lives: run.lives, score: run.score, combo: run.combo, nextLifeAt: run.nextLifeAt, stats: { ...run.stats }, best0: { ...run.best0 } },
  };
  // On the win screen the level is done: come back to the next one, from its start.
  if (phase === 'clear') return { ...base, level: level.number + 1, fresh: true };
  return {
    ...base, level: level.number, fresh: false,
    scoreAtStart: level.scoreAtStart, statsAtStart: { ...level.statsAtStart }, clock: game.clock.now,
    grid: encodeGrid(game.grid.cells),
    patrols: level.patrols.map((p) => [p.x, p.y, p.vx, p.vy, p.heading]),
    tracers: game.tracers.toJSON(),
    routes: level.routes.map((r) => Array.from(r)),
  };
}

/* --- validating one --------------------------------------------------------------------------------------- */

function cleanStats(s) {
  if (!isObject(s) || !isCount(s.captures) || !isCount(s.closeCalls) || !isCount(s.levelsCleared)) return null;
  return { captures: s.captures, closeCalls: s.closeCalls, levelsCleared: s.levelsCleared };
}

/* A clean copy of `raw`, or null. `today` is the local date key, needed to accept a daily run. */
export function validateSnapshot(raw, { now = Date.now(), today = null } = {}) {
  if (!isObject(raw) || raw.v !== SNAPSHOT_VERSION) return null;
  if (typeof raw.app !== 'string' || raw.app.split('.')[0] !== APP_VERSION.split('.')[0]) return null;     // a new major version may change what a level is
  if (!Number.isFinite(raw.savedAt) || raw.savedAt > now + CLOCK_SKEW_MS || now - raw.savedAt > SNAPSHOT_MAX_AGE_MS) return null;
  if (raw.mode !== 'normal' && raw.mode !== 'daily') return null;
  if (typeof raw.seed !== 'string' || raw.seed.length === 0 || raw.seed.length > 120) return null;
  if (raw.mode === 'daily' && (typeof raw.dayKey !== 'string' || raw.dayKey !== today)) return null;         // a daily run belongs to its own day
  if (!Number.isInteger(raw.level) || raw.level < 1 || raw.level > MAX_LEVEL || typeof raw.fresh !== 'boolean') return null;

  const r = raw.run;
  if (!isObject(r) || !Number.isInteger(r.lives) || r.lives < 1 || r.lives > MAX_LIVES) return null;
  if (!isCount(r.score) || !isCount(r.nextLifeAt) || r.nextLifeAt <= r.score) return null;
  if (!Number.isFinite(r.combo) || r.combo < 1 || r.combo > SCORE.combo.max || (r.combo * 4) % 1 !== 0) return null;
  const stats = cleanStats(r.stats);
  const b = r.best0;
  if (!stats || !isObject(b) || !isCount(b.score) || !Number.isFinite(b.clear) || b.clear < 0 || b.clear > 100 || !isCount(b.level)) return null;

  const out = {
    v: SNAPSHOT_VERSION, app: raw.app, savedAt: raw.savedAt, mode: raw.mode, seed: raw.seed,
    dayKey: raw.mode === 'daily' ? raw.dayKey : null, level: raw.level, fresh: raw.fresh,
    run: { lives: r.lives, score: r.score, combo: r.combo, nextLifeAt: r.nextLifeAt, stats, best0: { score: b.score, clear: b.clear, level: b.level } },
  };
  if (raw.fresh) return out;

  const startStats = cleanStats(raw.statsAtStart);
  if (!startStats || !isCount(raw.scoreAtStart) || raw.scoreAtStart > r.score) return null;
  if (!Number.isFinite(raw.clock) || raw.clock < 0 || raw.clock > 24 * 3600) return null;
  if (!Array.isArray(raw.grid) || !Array.isArray(raw.patrols) || !Array.isArray(raw.routes)) return null;
  if (raw.patrols.length < 1 || raw.patrols.length > MAX_PATROLS) return null;
  const patrols = [];
  for (const p of raw.patrols) {
    if (!Array.isArray(p) || p.length !== 5 || !p.every(Number.isFinite)) return null;
    if (!isCoordinate(p[0], BOARD_W) || !isCoordinate(p[1], BOARD_H)) return null;
    patrols.push(p.slice());
  }
  // Tracers: exactly as many as this level has, each [loop number, position along the loop, direction].
  if (!Array.isArray(raw.tracers) || raw.tracers.length !== levelInfo(raw.level).tracers) return null;
  const tracers = [];
  for (const t of raw.tracers) {
    if (!Array.isArray(t) || t.length !== 3 || !t.every(Number.isFinite) || (t[2] !== 1 && t[2] !== -1)) return null;
    if (!Number.isInteger(t[0]) || t[0] < 0 || t[0] > 10000 || t[1] < 0 || t[1] > 1e6) return null;
    tracers.push(t.slice());
  }
  if (raw.routes.length > MAX_ROUTES) return null;
  const routes = [];
  for (const route of raw.routes) {
    if (!Array.isArray(route) || route.length % 2 !== 0 || route.length > MAX_ROUTE_POINTS || !route.every(Number.isFinite)) return null;
    routes.push(route.slice());
  }
  if (raw.grid.length > GRID_W * GRID_H * 2) return null;
  return { ...out, scoreAtStart: raw.scoreAtStart, statsAtStart: startStats, clock: raw.clock, grid: raw.grid.slice(), patrols, tracers, routes };
}
