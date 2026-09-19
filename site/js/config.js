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

export const STEP = 1 / 120;                   // fixed physics timestep, in seconds
export const MAX_STEPS_PER_FRAME = 8;          // beyond this a slow frame drops time instead of spiralling

export const START_LIVES = 3;
export const MAX_LIVES = 5;
export const LEVEL_CLEAR_DELAY = 1.25;         // game-clock seconds between a win and the next level
export const RESUME_COUNTDOWN = 3;             // real seconds after an automatic pause

export const STORAGE_KEY = 'pathpatrol:v2';
export const LEGACY_KEY = 'color-divide-records-v1';

/* Difficulty curve. Speed is capped so a route is always outrunnable by a quick hand. */
export function levelInfo(level) {
  const l = Math.max(1, Math.floor(level));
  return {
    level: l,
    patrols: Math.min(6, 1 + Math.floor((l - 1) / 2)),
    speed: Math.min(26, 14 * (1 + 0.07 * (l - 1))),
    target: Math.min(70, 65 + Math.floor((l - 1) / 2) * 2),
    obstacles: Math.min(5, Math.floor((l - 1) / 2)),
    tracers: l >= 4 ? Math.min(3, Math.floor((l - 1) / 3)) : 0,
  };
}
