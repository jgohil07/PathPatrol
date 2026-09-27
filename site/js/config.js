/* Constants and tuning knobs. Anything a designer might want to adjust lives here. */

export const APP_VERSION = '1.2.0';

/* The board is 120 x 72 world units. Physics and drawing work in units; the cell grid that stores
   claimed territory is CELLS_PER_UNIT times finer, which keeps freehand edges smooth. */
export const BOARD_W = 120;
export const BOARD_H = 72;
export const CELLS_PER_UNIT = 2;
export const GRID_W = BOARD_W * CELLS_PER_UNIT;
export const GRID_H = BOARD_H * CELLS_PER_UNIT;
export const FRAME_UNITS = 2;                  // thickness of the outer frame

export const PATROL_RADIUS = 1.35;                     // a standard patrol's; each kind has its own (KINDS)

/* Patrol kinds. `radius` in units, `speed` a multiple of the level's speed. A hunter (and the boss) steers towards the tip
   of a route being drawn, after a visible wind-up, and never turns faster than `turn` radians a second: a confident swipe
   outruns it, a hesitant one is caught (steering.js). Everything else about a patrol is the same for every kind. */
const DEG = Math.PI / 180;
export const KINDS = Object.freeze({
  standard: Object.freeze({ radius: PATROL_RADIUS, speed: 1 }),
  scout: Object.freeze({ radius: 1.0, speed: 1.35 }),
  bomber: Object.freeze({ radius: 2.1, speed: 0.7 }),
  hunter: Object.freeze({ radius: PATROL_RADIUS, speed: 0.9, turn: 50 * DEG, windup: 0.4 }),
  boss: Object.freeze({ radius: 3.5, speed: 0.6, turn: 30 * DEG, windup: 0.8 }),         // every tenth level: see levelInfo
});
export const KIND_NAMES = Object.freeze(Object.keys(KINDS));
/* What the message line says the first time a player meets each kind (once per device). */
export const KIND_INTRO = Object.freeze({
  scout: 'New · scouts: small and fast',
  bomber: 'New · bombers: big and slow, easy to trap',
  hunter: 'New · hunters chase a slow pen: swipe fast',
  boss: 'Boss · trap it in 12% or less to win at once',
});
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

/* Trapping: a capture that leaves a patrol shut in a pocket of open ground no bigger than maxShare of the level's playable
   area grounds it. The pocket is claimed, the patrol leaves the level, and it pays `points` x combo. Each patrol trapped
   also raises the run's trap multiplier on every later capture by multStep, up to multCap (Qix's split bonus compounds the
   same way). Trapping the last patrol claims the whole board. The boss is trapped in a pocket of up to bossShare, pays
   bossPoints x combo, and trapping it clears the level at once (the rest of the board is claimed with it). */
export const TRAP = Object.freeze({ maxShare: 0.04, points: 1500, multStep: 0.25, multCap: 2, bossShare: 0.12, bossPoints: 5000 });
/* Stars on the win screen: one for clearing the level, two for clearing it without losing a life on it (a restart gives a
   fresh chance), three for that and either claiming at least `overshoot` points over the target or trapping a patrol on
   it. Kept per level (the campaign's boards: ordinary runs and level-select replays, not the daily), the best of each. */
export const STARS = Object.freeze({ overshoot: 8, maxLevel: 99 });
export const starsFor = ({ lifeLost, overshoot, trapped }) => (lifeLost ? 1 : overshoot >= STARS.overshoot || trapped > 0 ? 3 : 2);
export const trapMultiplier = (traps) => Math.min(TRAP.multCap, 1 + TRAP.multStep * traps);

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
export const EXPERT_SNAPSHOT_KEY = 'pathpatrol:v2:expert';      // expert's run in progress, in a slot of its own
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
    kinds: kindsFor(Math.min(6, 1 + Math.floor((l - 1) / 5)), l, CAMPAIGN_ARRIVALS, specialFor(l)),
    special: specialFor(l),
    valley: l > 5 && l % 5 === 1,                  // the level after a special: an early pickup (powerups.js)
  };
}

/* Every fifth level is special, and they alternate: an odd-shaped board (5, 15, 25...: level.js), then a boss (10, 20,
   30...). The special stays special past the curve's ceiling. The numbers of the level itself are the curve's. */
function specialFor(level) {
  if (level % 5 !== 0) return null;
  return (level / 5) % 2 === 1 ? 'shape' : 'boss';
}

/* Which kinds a level's patrols are, in order: new kinds join one at a time (in the campaign a scout from level 8, a bomber
   from 12, a hunter from 18) and replace standard patrols, so the count of patrols is the curve's as before. Levels 1-7 are
   all standard. No kind arrives on a level where the count itself rises (6, 11, 16, 21, 26). Measured with the bots
   (research/difficulty-curve-20260927-kinds): each arrival moves the lives lost per level by less than 0.1, and a second
   scout, tried at 26 and at 29, made the top of the curve harder than the ceiling tuned on 2026-09-21, so there is none. */
const CAMPAIGN_ARRIVALS = [['scout', 8], ['bomber', 12], ['hunter', 18]];

function kindsFor(count, level, arrivals, special) {
  const extra = arrivals.filter(([, from]) => level >= from).map(([kind]) => kind);
  const kinds = new Array(Math.max(0, count - extra.length)).fill('standard').concat(extra);
  if (special === 'boss' || special === 'finale') kinds[0] = 'boss';          // the boss takes the place of a standard patrol (there is always one)
  return kinds.slice(0, count);
}

/* Expert mode: the 1.0.0 curve in 15 levels, in straight lines (floored: no knob goes down) from 1.0.0's level 6 to its peak.
   Kinds arrive early, never where the count rises; 5 is an odd board, 10 a boss, 15 both. Bots: research/expert-curve-*. */
export const EXPERT = Object.freeze({ levels: 15 });
const EXPERT_ARRIVALS = [['scout', 2], ['bomber', 6], ['hunter', 8]];
const EXPERT_SPECIALS = { 5: 'shape', 10: 'boss', 15: 'finale' };

export function expertInfo(level) {
  const e = Math.min(EXPERT.levels, Math.max(1, Math.floor(level)));
  const k = e - 1;
  const patrols = 3 + Math.floor((k * 5) / 14);
  const special = EXPERT_SPECIALS[e] || null;
  return {
    level: e,
    patrols,
    speed: Math.round((18.9 + (k * 11.1) / 14) * 10) / 10,
    target: 69 + Math.floor((k * 6) / 14),
    obstacles: 2 + Math.floor((k * 4) / 14),
    tracers: 1 + Math.floor((k * 3) / 14),
    powerups: true,
    kinds: kindsFor(patrols, e, EXPERT_ARRIVALS, special),
    special,
    valley: e === 6 || e === 11,                   // after a special: an early pickup
  };
}

/* Level n's numbers in a run of this mode. */
export const infoFor = (mode, level) => (mode === 'expert' ? expertInfo(level) : levelInfo(level));
