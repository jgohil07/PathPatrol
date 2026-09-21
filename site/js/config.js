/* Constants and tuning knobs. Anything a designer might want to adjust lives here. */

export const APP_VERSION = '1.0.0';

/* The board is 120 x 72 world units. Physics and drawing work in units; the cell grid that stores
   claimed territory is CELLS_PER_UNIT times finer, which keeps freehand edges smooth. */
export const BOARD_W = 120;
export const BOARD_H = 72;
export const CELLS_PER_UNIT = 2;
export const GRID_W = BOARD_W * CELLS_PER_UNIT;
export const GRID_H = BOARD_H * CELLS_PER_UNIT;
export const FRAME_UNITS = 2;                  // thickness of the outer frame

export const PATROL_RADIUS = 1.35;
export const MIN_BOUNCE_ANGLE = (12 * Math.PI) / 180;   // a bounce turns a direction at least this far from a screen axis
export const HEADING_TAU = 0.07;                         // seconds for a drawn sprite to catch up with a change of direction

export const STEP = 1 / 120;                   // fixed physics timestep, in seconds
export const MAX_STEPS_PER_FRAME = 8;          // beyond this a slow frame drops time instead of spiralling

export const START_LIVES = 3;
export const MAX_LIVES = 5;
export const LEVEL_CLEAR_DELAY = 3.4;          // game-clock seconds the tally shows before the next level starts by itself
export const CLEAR_SKIP_AFTER = 0.6;           // ...and how long before a tap may skip it (the tap that closed the route must not)
export const RESUME_COUNTDOWN = 3;             // real seconds after an automatic pause

/* Scoring. Points are counted in board units squared (a grid cell is a quarter of one), so the numbers mean
   the same whatever the grid resolution. Starting values; tuned in Phase 5.6. */
export const SCORE = Object.freeze({
  combo: { step: 0.25, max: 3, minGain: 0.5 },          // +step per capture of at least minGain percentage points; resets on a cancel or a hit
  bigCapture: { percent: 10, multiplier: 1.5 },         // a single capture this large is worth half as much again
  closeCall: { points: 250, distance: 3.5 },            // a patrol this close (units) to the live route, banked when the route closes
  clear: { overshootPerPercent: 100, perLife: 500, timePar: 75, perSecond: 10 },
  extraLifeEvery: 25000,
});

/* The tutorial: one slow patrol on level 1's board and three coached steps. */
/* Drawing with the keyboard: the cursor moves 4-directionally at this speed, through the same route engine as a pointer.
   A swipe crosses the board in a fraction of a second; this takes a few seconds, which is what makes it the slower way. */
export const KEYBOARD = Object.freeze({
  speed: 30,                 // units per second
});

/* The daily challenge: the day puzzle #1 was, where a shared result points, and how the shared pattern is drawn. */
export const DAILY = Object.freeze({
  epoch: '2026-09-19',
  shareUrl: 'https://jgohil07.github.io/PathPatrol/',
  pathGlyphs: 11,            // levels shown in the shared pattern before it is shortened with an ellipsis
  barLength: 4,              // blocks in the shared progress bar
});

export const TUTORIAL = Object.freeze({
  speedScale: 0.45,          // the patrol moves at this fraction of level 1's speed
  minCapture: 5,             // percent: a smaller capture does not finish it (draw across the whole board)
  dragCells: 20,             // a live route this long counts as "dragged into the field"
  ghostX: 34,                // where the ghost finger draws, in board units: the left third, away from the patrol
});

export const STORAGE_KEY = 'pathpatrol:v2';
export const SNAPSHOT_KEY = 'pathpatrol:v2:run';      // a run in progress, separate from settings and records
export const LEGACY_KEY = 'color-divide-records-v1';

/* The difficulty curve: level n is always the same, for every player. Every knob moves a little at a time, so each level is
   a touch harder than the one before: speed rises a little every level, the clear target a point every three, and a patrol
   or an obstacle every five levels (edge tracers from level 5, a second at 14, a third at 23). It reaches its ceiling at level
   31 (6 patrols at 26 u/s among 5 obstacles and 3 tracers, 75 % to clear) and stays there: hard, but a skilled player
   can still clear it. Measured with bots (research/difficulty-curve-*): the chance of losing a route rises from about 0 on
   level 1 to about 2 lives a level on level 30, without a jump anywhere on the way. */
export function levelInfo(level) {
  const l = Math.max(1, Math.floor(level));
  return {
    level: l,
    patrols: Math.min(6, 1 + Math.floor((l - 1) / 5)),
    speed: Math.min(26, 14 + 0.4 * (l - 1)),
    target: Math.min(75, 65 + Math.floor((l - 1) / 3)),
    obstacles: Math.min(5, Math.floor((l - 1) / 5)),
    tracers: l < 5 ? 0 : Math.min(3, 1 + Math.floor((l - 5) / 9)),
    powerups: l >= 3,
  };
}
