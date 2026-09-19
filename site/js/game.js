/* Game state: the phase machine, the game clock, lives, captures and level progression.

   No DOM, no timers, no drawing. The UI and renderer listen to events; the loop calls step()/tick().
   Every delayed action goes through the Scheduler below, which only advances while the game is
   actually running, so pausing freezes it and restarting cancels it. The prototype used setTimeout and
   paid for it: a restarted level could "win itself" and a pause could be overridden. */
import { START_LIVES, MAX_LIVES, LEVEL_CLEAR_DELAY, CLEAR_SKIP_AFTER, RESUME_COUNTDOWN, CELLS_PER_UNIT, SCORE, TUTORIAL, levelInfo } from './config.js';
import { Grid, FIELD, WALL, ROUTE, SOLID_MASK, ROUTE_MASK, toCell } from './grid.js';
import { buildLevel } from './level.js';
import { advance, settle, makePatrol } from './physics.js';
import { RouteEngine } from './route.js';
import { Tutorial } from './tutorial.js';
import { Tracers } from './tracers.js';
import { Powerups } from './powerups.js';
import { randomSeed, dayKey } from './rng.js';
import { takeSnapshot, validateSnapshot, decodeGrid } from './snapshot.js';

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

/* Why a route was erased. Only these are the player abandoning it (a lift, a cancelled touch, Backspace) and
   break the combo; a pause, a restart or a jitter-sized route are not. */
const COMBO_BREAKERS = new Set(['lift', 'cancel', 'backspace']);

/* With the shield power-up the route being drawn is solid to patrols, so they bounce off it. */
const SHIELDED = { mask: SOLID_MASK | ROUTE_MASK };

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
    this.level = null;         // { number, info, obstacles, initialPlayable, patrols, cleared, scoreAtStart, statsAtStart }
    this.run = null;           // { seed, mode, lives, score, combo, nextLifeAt, stats, best0 }
    this.flash = 0;            // seconds left of the red "life lost" flash
    this.report = null;        // summary of the run that just ended
    this.tally = null;         // the level-clear breakdown while the win screen shows
    this.saved = null;         // a validated snapshot of an interrupted run, offered on the title screen
    this._clearAt = 0;         // game-clock time the win screen appeared
    this.route = new RouteEngine(this);
    this.tutorial = new Tutorial(this);
    this.tracers = new Tracers(this);
    this.powerups = new Powerups(this);
    this.on('route', (event) => this._onRoute(event));
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
    this.tracers.reset(this.level, seed);
    this.clock.reset();
    this.powerups.reset(this.level, seed);              // after the clock: its first pickup is timed from zero
    this.flash = 0;
    this.emit('level', this.level);
  }

  /* --- flow ------------------------------------------------------------------------------- */

  /* The title screen: a decorative board that keeps moving behind the start button. */
  enterTitle() {
    this.run = null;
    this.tutorial.stop();
    this._build(6, 'attract');
    this._loadSaved();                       // before the phase changes: the title decides what to focus from it
    this._setPhase(PHASE.TITLE);
    this.emit('hud');
  }

  /* --- an interrupted run ------------------------------------------------------------------------ */

  /* Reads the saved run, if any. Anything stale or damaged is dropped, not offered. */
  _loadSaved() {
    const raw = this.storage.loadSnapshot();
    this.saved = raw ? validateSnapshot(raw, { today: dayKey(new Date()) }) : null;
    if (raw && !this.saved) this.storage.clearSnapshot();
    this.emit('saved', this.saved);
  }

  /* Saves the run if there is something to resume. Called at every point the run changes for good (a capture,
     a lost life, a level start), not only when the page is hidden: it survives a hard kill, and a life lost
     cannot be undone by reloading the page. It never clears anything: hiding the tab on the title screen
     must not delete the saved run on offer there. Clearing is explicit (game over, an unusable save). */
  persist() {
    const snapshot = takeSnapshot(this);
    if (snapshot) this.storage.saveSnapshot(snapshot);
  }

  /* Rebuilds the level from (seed, number), lays the saved state over it and goes straight into the 3-2-1
     countdown. False if there is nothing to resume or what was saved turns out to be unusable. */
  resumeRun() {
    const snap = this.saved;
    if (!snap || this.phase !== PHASE.TITLE) return false;
    this.saved = null;
    this.report = null;
    this.tally = null;
    this.run = { seed: snap.seed, mode: snap.mode, dayKey: snap.dayKey, ...snap.run };
    if (snap.fresh) {
      this.startLevel(snap.level);
    } else {
      this._build(snap.level, snap.seed);
      const { level, grid } = this;
      if (!decodeGrid(snap.grid, grid.cells)) {                 // valid in shape, wrong in size: not trusted after all
        this.storage.clearSnapshot();
        this.enterTitle();
        return false;
      }
      level.patrols.length = 0;
      for (const [x, y, vx, vy, heading] of snap.patrols) {
        const patrol = makePatrol(x, y, vx, vy);
        patrol.heading = heading;
        level.patrols.push(patrol);
      }
      settle(level.patrols, grid);
      if (!this.tracers.restore(snap.tracers)) this.tracers.reset(level, snap.seed);      // they no longer fit the board: start them afresh
      level.routes = snap.routes;
      level.cleared = ((level.initialPlayable - grid.countField()) / level.initialPlayable) * 100;
      level.scoreAtStart = snap.scoreAtStart;
      level.statsAtStart = snap.statsAtStart;
      this.clock.now = snap.clock;
      this.powerups.restore(level, snap.seed, snap.powerups);
      this._setPhase(PHASE.PLAYING);
    }
    this.pause('restored');
    this.emit('hud');
    this.resume();
    return true;
  }

  newRun({ mode = 'normal', seed = randomSeed() } = {}) {
    const records = this.storage.records;
    this.run = {
      seed, mode, lives: START_LIVES, score: 0, combo: 1, nextLifeAt: SCORE.extraLifeEvery,
      stats: { captures: 0, closeCalls: 0, levelsCleared: 0 },
      best0: { score: records.bestScore, clear: records.bestClear, level: records.bestLevel },   // for the "new best" flags
    };
    this.report = null;
    this.tally = null;
    this.saved = null;
    this.tutorial.stop();
    this.storage.updateRecords((r) => { r.runs++; });
    this.startLevel(1);
  }

  /* --- the tutorial ------------------------------------------------------------------------------ */

  /* Level 1's board with one slow patrol and the coach. A run that was in progress stays saved on disk (it is
     saved at every capture, life and level start) and resumable from the title; the tutorial itself is never
     saved and never touches the score or the records. */
  startTutorial({ origin = 'start' } = {}) {
    const records = this.storage.records;
    this.run = {
      seed: 'tutorial', mode: 'tutorial', lives: START_LIVES, score: 0, combo: 1, nextLifeAt: SCORE.extraLifeEvery,
      stats: { captures: 0, closeCalls: 0, levelsCleared: 0 },
      best0: { score: records.bestScore, clear: records.bestClear, level: records.bestLevel },
    };
    this.report = null;
    this.tally = null;
    this._build(1, 'tutorial');
    const info = levelInfo(1);
    this.level.patrols.length = 0;
    const speed = info.speed * TUTORIAL.speedScale;
    this.level.patrols.push(makePatrol(96, 30, -speed * 0.6, speed * 0.8));       // on the right, well away from the ghost's path
    this._markLevelStart();
    this._setPhase(PHASE.PLAYING);
    this.tutorial.start(origin);
    this.emit('hud');
  }

  /* The coached capture happened: the tutorial is over, and the player chooses to play. */
  finishTutorial(result) {
    this.tutorial.stop();
    this.storage.updateSettings({ tutorialDone: true });
    this.tally = { tutorial: true, cleared: result.percent, origin: this.tutorial.origin };
    this._clearAt = this.clock.now;
    this._setPhase(PHASE.CLEAR);
    this.emit('clear', this.tally);
  }

  /* The header's Skip button. A first launch goes on to a real run; a replay goes back to the title. */
  skipTutorial() {
    if (!this.tutorial.active) return false;
    const origin = this.tutorial.origin;
    this.tutorial.stop();
    this.storage.updateSettings({ tutorialDone: true });
    if (origin === 'start') this.newRun();
    else this.enterTitle();
    return true;
  }

  /* A level is (re)started: remember where the score and stats stood, and begin at x1. */
  _markLevelStart() {
    this.level.scoreAtStart = this.run.score;
    this.level.statsAtStart = { ...this.run.stats };
    this.run.combo = 1;
  }

  startLevel(number) {
    this._build(number, this.run.seed);
    this._markLevelStart();
    this.tally = null;
    this._setPhase(PHASE.PLAYING);
    this.toast(`Level ${pad2(number)} · clear ${this.level.info.target}%`, 1400);
    this.emit('levelStart', { level: number, target: this.level.info.target, lives: this.run.lives });
    this.emit('hud');
    this.persist();
  }

  /* Same layout, same lives. The attempt's points are forgotten, so a restart cannot bank score; the life
     threshold is left where it is, so it cannot earn the same extra life twice. Not available on game over
     (that is what New run is for). */
  restartLevel() {
    const ok = this.phase === PHASE.PLAYING || this.phase === PHASE.PAUSED || this.phase === PHASE.COUNTDOWN;
    if (!ok || !this.run || this.run.mode === 'daily' || this.run.mode === 'tutorial') return false;
    const { scoreAtStart, statsAtStart } = this.level;
    this._build(this.level.number, this.run.seed);
    this.run.score = scoreAtStart;
    this.run.stats = { ...statsAtStart };
    this._markLevelStart();
    this._setPhase(PHASE.PLAYING);
    this.toast('Level restarted', 900);
    this.emit('levelStart', { level: this.level.number, target: this.level.info.target, lives: this.run.lives, restarted: true });
    this.emit('hud');
    this.persist();
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
      if (this.pauseReason === 'auto' || this.pauseReason === 'restored') {
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
    if (this.run.mode === 'tutorial') { this.flash = 0.34; return; }          // practice: the red flash, and nothing lost
    this.run.lives--;
    this.run.combo = 1;
    this.flash = 0.34;
    this.emit('life', { lives: this.run.lives });
    this.emit('hud');
    if (this.run.lives > 0) {
      this.toast('Route intercepted — try again', 1200);
      this.persist();
    } else {
      this._gameOver();
    }
  }

  _gameOver() {
    const { run, level } = this;
    const records = this.storage.records;
    this.report = {
      level: level.number, cleared: level.cleared, mode: run.mode,
      score: run.score, stats: { ...run.stats },
      newBest: {                                         // against the records as they stood when the run began
        score: run.score > run.best0.score,
        clear: records.bestClear > run.best0.clear,
        level: records.bestLevel > run.best0.level,
      },
    };
    this.flash = 0;                        // the game-over card replaces the flash; nothing left to animate
    this.storage.clearSnapshot();          // a finished run is not resumable
    this._setPhase(PHASE.OVER);
    this.emit('over', this.report);
  }

  crash(error) {
    if (this.phase === PHASE.CRASHED) return;
    this._setPhase(PHASE.CRASHED);
    this.emit('crash', { error });
  }

  /* --- captures --------------------------------------------------------------------------- */

  /* The route engine reports every erased route; abandoning one costs the combo. */
  _onRoute(event) {
    if (this.run && event.type === 'cancel' && COMBO_BREAKERS.has(event.reason) && this.run.combo > 1) {
      this.run.combo = 1;
      this.emit('combo', { combo: 1, broken: true });
      this.emit('hud');
    }
  }

  /* Points are banked here and nowhere else, so a route that is cancelled or hit never scores. Returns the
     breakdown for the popup and the announcer. */
  _scoreCapture(run, gained, closeCalls) {
    const { level } = this;
    const units = ((gained / 100) * level.initialPlayable) / (CELLS_PER_UNIT * CELLS_PER_UNIT);
    const combo = run.combo;
    const size = gained >= SCORE.bigCapture.percent ? SCORE.bigCapture.multiplier : 1;
    const capturePoints = Math.round(units * combo * size);
    const closePoints = Math.round(closeCalls * SCORE.closeCall.points * combo);
    run.stats.captures++;
    run.stats.closeCalls += closeCalls;
    if (gained >= SCORE.combo.minGain) run.combo = Math.min(SCORE.combo.max, combo + SCORE.combo.step);
    return { combo, nextCombo: run.combo, capturePoints, closePoints, points: capturePoints + closePoints };
  }

  /* Adds points, keeps the best score, and grants an extra life at every threshold (none beyond MAX_LIVES,
     but the threshold still moves on). */
  _addScore(points) {
    const { run } = this;
    if (!run || points <= 0) return;
    run.score += points;
    this.storage.updateRecords((r) => { r.bestScore = Math.max(r.bestScore, run.score); });
    while (run.score >= run.nextLifeAt) {
      run.nextLifeAt += SCORE.extraLifeEvery;
      if (run.lives < MAX_LIVES) {
        run.lives++;
        this.emit('extraLife', { lives: run.lives });
        this.toast(`Extra life · ${run.lives} ${run.lives === 1 ? 'life' : 'lives'}`, 1400);      // spoken once, by the announcer, through the toast
      }
    }
  }

  /* Called by the route engine when a route is closed. The route's cells become wall and every open
     area with no patrol in it is claimed. `routeCells` are grid indices; `polyline` (flat x, y, ...) is
     kept so the finished route can be drawn as a runway or road; `closeCalls` is how many patrols just
     missed it. */
  commitCapture(routeCells, { polyline, closeCalls = 0 } = {}) {
    if (this.phase !== PHASE.PLAYING) return null;
    const { grid, level } = this;
    for (const i of routeCells) {
      const v = grid.cells[i];
      if (v === FIELD || v === ROUTE) grid.cells[i] = WALL;
    }
    const before = grid.countField();
    grid.claimUnreachable(this._patrolSeeds());
    settle(level.patrols, grid);                 // a patrol brushing the new wall is moved clear of it
    this.tracers.refresh();                      // the boundary moved: trace it again and put each tracer back on it
    this.powerups.afterCapture();                // ground that swallowed a pickup takes it
    const after = grid.countField();
    const previous = level.cleared;
    if (polyline) level.routes.push(polyline);
    level.cleared = ((level.initialPlayable - after) / level.initialPlayable) * 100;
    const gained = level.cleared - previous;
    const result = { percent: level.cleared, gained, cellsClaimed: before - after, points: 0, capturePoints: 0, closePoints: 0, closeCalls, combo: 1, nextCombo: 1, route: polyline || null };
    const real = !!this.run && this.run.mode !== 'tutorial';                 // the tutorial is practice: no score, no records, no save
    if (real) Object.assign(result, this._scoreCapture(this.run, gained, closeCalls));
    if (real) this.storage.updateRecords((r) => { r.bestClear = Math.max(r.bestClear, level.cleared); });
    this.emit('capture', result);
    if (real) this._addScore(result.points);
    this.emit('hud');
    if (real && level.cleared >= level.info.target) this._levelWon();
    if (real) this.persist();
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

  /* The win screen: what the level's captures scored, then bonuses for finishing above the target, for the
     lives still held and for finishing quickly (game-clock seconds, so a pause does not count). */
  _levelWon() {
    const { level, run } = this;
    const number = level.number;
    const c = SCORE.clear;
    const seconds = this.clock.now;
    const overshoot = Math.max(0, level.cleared - level.info.target);
    const tally = {
      level: number, cleared: level.cleared, target: level.info.target,
      capturePoints: run.score - level.scoreAtStart,
      overshoot, overshootBonus: Math.round(overshoot * c.overshootPerPercent),
      lives: run.lives, livesBonus: run.lives * c.perLife,
      seconds, timeBonus: Math.max(0, Math.round((c.timePar - seconds) * c.perSecond)),
    };
    tally.bonus = tally.overshootBonus + tally.livesBonus + tally.timeBonus;
    tally.total = tally.capturePoints + tally.bonus;
    run.stats.levelsCleared++;
    this._addScore(tally.bonus);
    this.tally = tally;
    this._setPhase(PHASE.CLEAR);
    this.storage.updateRecords((r) => { r.wins++; r.bestLevel = Math.max(r.bestLevel, number); });
    this._clearAt = this.clock.now;
    this.clock.after(LEVEL_CLEAR_DELAY, () => this.startLevel(number + 1));
    this.emit('clear', tally);
    this.emit('hud');
  }

  /* A tap, Enter or the Next button on the win screen moves on at once, but not within CLEAR_SKIP_AFTER of
     the win: the tap that closed the winning route must not skip the tally nobody has seen yet. */
  skipClear() {
    if (this.phase !== PHASE.CLEAR) return false;
    if (this.clock.now - this._clearAt < CLEAR_SKIP_AFTER) return false;
    if (this.tally && this.tally.tutorial) this.newRun();       // the tutorial's finish screen: Play
    else this.startLevel(this.level.number + 1);                 // building the level resets the clock, which drops the automatic advance
    return true;
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
          this.powerups.update();             // a pickup may appear or expire, an effect may end
          const scale = this.powerups.scale();
          if (scale.patrols > 0) advance(this.level.patrols, dt * scale.patrols, this.grid, this.powerups.shielded ? SHIELDED : undefined);
          else for (const p of this.level.patrols) { p.px = p.x; p.py = p.y; }      // frozen: drawn where they are, not shimmering back
          this.route.afterStep();             // a patrol may have flown into the route being drawn
          this.tracers.update(dt, scale.tracers);       // tracers crawl the boundary, and may chase the route
          this.tutorial.update();
        }
        break;
      case PHASE.CLEAR:
        this.flash = Math.max(0, this.flash - dt);
        this.clock.advance(dt);              // patrols stay frozen while the win banner shows
        break;
      case PHASE.TITLE:
        advance(this.level.patrols, dt, this.grid);
        this.tracers.update(dt);
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
      score: this.run ? this.run.score : 0,
      combo: this.run ? this.run.combo : 1,
      target: level ? level.info.target : first.target,
      cleared: level ? level.cleared : 0,
      patrols: level ? level.patrols.length : first.patrols,
      phase: this.phase,
      mode: this.run ? this.run.mode : null,
    };
  }
}
