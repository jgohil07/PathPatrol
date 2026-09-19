/* Game state: the phase machine, the game clock, lives, captures and level progression.

   No DOM, no timers, no drawing. The UI and renderer listen to events; the loop calls step()/tick().
   Every delayed action goes through the Scheduler below, which only advances while the game is
   actually running, so pausing freezes it and restarting cancels it. The prototype used setTimeout and
   paid for it: a restarted level could "win itself" and a pause could be overridden. */
import { START_LIVES, LEVEL_CLEAR_DELAY, RESUME_COUNTDOWN, CELLS_PER_UNIT, levelInfo } from './config.js';
import { Grid, FIELD, WALL, ROUTE, toCell } from './grid.js';
import { buildLevel } from './level.js';
import { advance, settle } from './physics.js';
import { RouteEngine } from './route.js';
import { randomSeed } from './rng.js';

export const PHASE = Object.freeze({
  BOOT: 'boot',
  TITLE: 'title',            // a live board behind the start screen
  PLAYING: 'playing',
  PAUSED: 'paused',
  COUNTDOWN: 'countdown',    // 3-2-1 after an automatic pause
  CLEAR: 'clear',            // level won; the next one starts when the clock says so
  OVER: 'over',
  CRASHED: 'crashed',
});

class Emitter {
  constructor() { this._listeners = {}; }
  on(type, fn) {
    (this._listeners[type] ||= new Set()).add(fn);
    return () => this._listeners[type].delete(fn);
  }
  emit(type, payload) {
    const set = this._listeners[type];
    if (set) for (const fn of [...set]) fn(payload);
  }
}

/* A clock that only moves when the game does. reset() invalidates everything scheduled before it. */
export class Scheduler {
  constructor() { this.now = 0; this.epoch = 0; this.tasks = []; this._seq = 0; }

  after(delay, fn) {
    const task = { at: this.now + delay, fn, epoch: this.epoch, seq: this._seq++ };
    this.tasks.push(task);
    this.tasks.sort((a, b) => a.at - b.at || a.seq - b.seq);
    return task;
  }
  cancel(task) {
    const i = this.tasks.indexOf(task);
    if (i >= 0) this.tasks.splice(i, 1);
  }
  reset() { this.epoch++; this.tasks.length = 0; this.now = 0; }
  advance(dt) {
    this.now += dt;
    while (this.tasks.length && this.tasks[0].at <= this.now) {
      const task = this.tasks.shift();
      if (task.epoch === this.epoch) task.fn();
    }
  }
  get pending() { return this.tasks.length; }
}

const pad2 = (n) => String(n).padStart(2, '0');

export class Game extends Emitter {
  constructor({ storage }) {
    super();
    this.storage = storage;
    this.grid = new Grid();
    this.clock = new Scheduler();
    this.phase = PHASE.BOOT;
    this.pausedFrom = null;
    this.pauseReason = null;
    this.countdown = 0;
    this.level = null;         // { number, info, obstacles, initialPlayable, patrols, cleared }
    this.run = null;           // { seed, mode, lives }
    this.flash = 0;            // seconds left of the red "life lost" flash
    this.report = null;        // summary of the run that just ended
    this.route = new RouteEngine(this);
  }

  toast(text, ms = 1200) { this.emit('toast', { text, ms }); }
  isPlaying() { return this.phase === PHASE.PLAYING; }

  _setPhase(next) {
    const prev = this.phase;
    this.phase = next;
    this.emit('phase', { phase: next, prev });
  }

  _build(number, seed) {
    this.level = buildLevel(number, seed, this.grid);
    this.clock.reset();
    this.flash = 0;
    this.emit('level', this.level);
  }

  /* --- flow ------------------------------------------------------------------------------- */

  /* The title screen: a decorative board that keeps moving behind the start button. */
  enterTitle() {
    this.run = null;
    this._build(6, 'attract');
    this._setPhase(PHASE.TITLE);
    this.emit('hud');
  }

  newRun({ mode = 'normal', seed = randomSeed() } = {}) {
    this.run = { seed, mode, lives: START_LIVES };
    this.report = null;
    this.storage.updateRecords((r) => { r.runs++; });
    this.startLevel(1);
  }

  startLevel(number) {
    this._build(number, this.run.seed);
    this._setPhase(PHASE.PLAYING);
    this.toast(`Level ${pad2(number)} · clear ${this.level.info.target}%`, 1400);
    this.emit('levelStart', { level: number, target: this.level.info.target, lives: this.run.lives });
    this.emit('hud');
  }

  /* Same layout, same lives. Not available on game over (that is what New run is for). */
  restartLevel() {
    const ok = this.phase === PHASE.PLAYING || this.phase === PHASE.PAUSED || this.phase === PHASE.COUNTDOWN;
    if (!ok || !this.run || this.run.mode === 'daily') return false;
    this._build(this.level.number, this.run.seed);
    this._setPhase(PHASE.PLAYING);
    this.toast('Level restarted', 900);
    this.emit('levelStart', { level: this.level.number, target: this.level.info.target, lives: this.run.lives, restarted: true });
    this.emit('hud');
    return true;
  }

  pause(reason = 'manual') {
    if (this.phase !== PHASE.PLAYING && this.phase !== PHASE.CLEAR) return false;
    this.pausedFrom = this.phase;
    this.pauseReason = reason;
    this.countdown = 0;
    this._setPhase(PHASE.PAUSED);
    return true;
  }

  /* After an automatic pause (tab hidden, window blurred) play resumes after a short countdown;
     a second press skips it. */
  resume() {
    if (this.phase === PHASE.PAUSED) {
      if (this.pauseReason === 'auto') {
        this.countdown = RESUME_COUNTDOWN;
        this._setPhase(PHASE.COUNTDOWN);
        this.emit('countdown', Math.ceil(this.countdown));
      } else {
        this._setPhase(this.pausedFrom);
      }
      return true;
    }
    if (this.phase === PHASE.COUNTDOWN) { this._setPhase(this.pausedFrom); return true; }
    return false;
  }

  togglePause() {
    return this.phase === PHASE.PLAYING || this.phase === PHASE.CLEAR ? this.pause('manual') : this.resume();
  }

  /* The route engine reports a patrol touching a route. */
  loseLife() {
    if (this.phase !== PHASE.PLAYING) return;
    this.run.lives--;
    this.flash = 0.34;
    this.emit('life', { lives: this.run.lives });
    this.emit('hud');
    if (this.run.lives > 0) this.toast('Route intercepted — try again', 1200);
    else this._gameOver();
  }

  _gameOver() {
    this.report = { level: this.level.number, cleared: this.level.cleared, mode: this.run.mode };
    this.flash = 0;                        // the game-over card replaces the flash; nothing left to animate
    this._setPhase(PHASE.OVER);
    this.emit('over', this.report);
  }

  crash(error) {
    if (this.phase === PHASE.CRASHED) return;
    this._setPhase(PHASE.CRASHED);
    this.emit('crash', { error });
  }

  /* --- captures --------------------------------------------------------------------------- */

  /* Called by the route engine when a route is closed. The route's cells become wall and every open
     area with no patrol in it is claimed. `routeCells` are grid indices; `polyline` (flat x, y, ...) is
     kept so the finished route can be drawn as a runway or road. */
  commitCapture(routeCells, { polyline } = {}) {
    if (this.phase !== PHASE.PLAYING) return null;
    const { grid, level } = this;
    for (const i of routeCells) {
      const v = grid.cells[i];
      if (v === FIELD || v === ROUTE) grid.cells[i] = WALL;
    }
    const before = grid.countField();
    grid.claimUnreachable(this._patrolSeeds());
    settle(level.patrols, grid);                 // a patrol brushing the new wall is moved clear of it
    const after = grid.countField();
    const previous = level.cleared;
    if (polyline) level.routes.push(polyline);
    level.cleared = ((level.initialPlayable - after) / level.initialPlayable) * 100;
    const result = { percent: level.cleared, gained: level.cleared - previous, cellsClaimed: before - after };
    this.storage.updateRecords((r) => { r.bestClear = Math.max(r.bestClear, level.cleared); });
    this.emit('capture', result);
    this.emit('hud');
    if (level.cleared >= level.info.target) this._levelWon();
    return result;
  }

  /* Open cells a patrol stands in. A patrol brushing a fresh wall may have its centre inside it, so
     fall back to every open cell under its disc; an area a patrol touches is never claimed. */
  _patrolSeeds() {
    const { grid } = this;
    const seeds = [];
    for (const p of this.level.patrols) {
      const cx = toCell(p.x), cy = toCell(p.y);
      if (grid.get(cx, cy) === FIELD) { seeds.push(grid.index(cx, cy)); continue; }
      const r = Math.ceil(p.r * CELLS_PER_UNIT);
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (dx * dx + dy * dy <= r * r && grid.get(cx + dx, cy + dy) === FIELD) seeds.push(grid.index(cx + dx, cy + dy));
        }
      }
    }
    return seeds;
  }

  _levelWon() {
    const number = this.level.number;
    this._setPhase(PHASE.CLEAR);
    this.storage.updateRecords((r) => { r.wins++; r.bestLevel = Math.max(r.bestLevel, number); });
    this.emit('clear', { level: number });
    this.clock.after(LEVEL_CLEAR_DELAY, () => this.startLevel(number + 1));
  }

  /* --- time ------------------------------------------------------------------------------- */

  /* Real-time housekeeping, once per frame: only the resume countdown runs on real time. */
  tick(dt) {
    if (this.phase !== PHASE.COUNTDOWN) return;
    const before = Math.ceil(this.countdown);
    this.countdown -= dt;
    if (this.countdown <= 0) this._setPhase(this.pausedFrom);
    else if (Math.ceil(this.countdown) !== before) this.emit('countdown', Math.ceil(this.countdown));
  }

  /* One fixed simulation step. */
  step(dt) {
    switch (this.phase) {
      case PHASE.PLAYING:
        this.flash = Math.max(0, this.flash - dt);
        this.clock.advance(dt);
        if (this.phase === PHASE.PLAYING) {
          advance(this.level.patrols, dt, this.grid);
          this.route.afterStep();             // a patrol may have flown into the route being drawn
        }
        break;
      case PHASE.CLEAR:
        this.flash = Math.max(0, this.flash - dt);
        this.clock.advance(dt);              // patrols stay frozen while the win banner shows
        break;
      case PHASE.TITLE:
        advance(this.level.patrols, dt, this.grid);
        break;
      default:
    }
  }

  isStepping() {
    return this.phase === PHASE.PLAYING || this.phase === PHASE.CLEAR || this.phase === PHASE.TITLE;
  }

  /* Does the picture change without any input? The renderer skips frames when it doesn't, so a paused
     or finished game costs almost nothing. */
  isAnimating() { return this.isStepping(); }

  /* What the HUD shows. On the title screen the board behind it is only decoration, so the HUD
     shows level 1's numbers rather than the decorative level's. */
  hud() {
    const level = this.run ? this.level : null;
    const first = levelInfo(1);
    return {
      level: level ? level.number : 1,
      lives: this.run ? this.run.lives : START_LIVES,
      target: level ? level.info.target : first.target,
      cleared: level ? level.cleared : 0,
      patrols: level ? level.patrols.length : first.patrols,
      phase: this.phase,
      mode: this.run ? this.run.mode : null,
    };
  }
}
