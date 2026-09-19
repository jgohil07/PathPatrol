/* Builds a level from (number, seed): the frame, the obstacle blocks and the patrols' starting
   positions and headings. Only the layout stream is used, so the same (seed, number) always gives
   the same level, whatever the player did in earlier levels. */
import { BOARD_W, BOARD_H, CELLS_PER_UNIT as S, FRAME_UNITS, levelInfo } from './config.js';
import { BORDER } from './grid.js';
import { makePatrol, awayFromAxes } from './physics.js';
import { layoutRng } from './rng.js';

const CLEARANCE = 3;       // units of open ground kept around each obstacle
const OBSTACLE_ATTEMPTS = 100;
const SPAWN_ATTEMPTS = 300;

export function buildLevel(number, seed, grid) {
  const info = levelInfo(number);
  const rng = layoutRng(seed, number);
  grid.clear();
  grid.frame(FRAME_UNITS * S);
  const obstacles = placeObstacles(grid, rng, info.obstacles);
  const initialPlayable = grid.countField();
  const patrols = placePatrols(grid, rng, info);
  return { number, info, obstacles, initialPlayable, patrols, cleared: 0, routes: [] };
}

function placeObstacles(grid, rng, quantity) {
  const placed = [];
  for (let attempt = 0; placed.length < quantity && attempt < OBSTACLE_ATTEMPTS; attempt++) {
    const w = rng.int(4, 9), h = rng.int(3, 6);
    const x = rng.int(14, BOARD_W - w - 14), y = rng.int(12, BOARD_H - h - 12);
    const near = grid.rectHasSolid((x - CLEARANCE) * S, (y - CLEARANCE) * S, (x + w + CLEARANCE) * S, (y + h + CLEARANCE) * S);
    if (near) continue;
    grid.fillRect(x * S, y * S, (x + w) * S, (y + h) * S, BORDER);
    placed.push({ x, y, w, h });                   // world units
  }
  return placed;
}

function placePatrols(grid, rng, info) {
  const patrols = [];
  for (let i = 0; i < info.patrols; i++) {
    let x = 0, y = 0, found = false;
    for (let tries = 0; tries < SPAWN_ATTEMPTS && !found; tries++) {
      x = rng.range(5, BOARD_W - 5);
      y = rng.range(5, BOARD_H - 5);
      found = !grid.circleHitsSolid(x, y, 2.2) && patrols.every((p) => Math.hypot(p.x - x, p.y - y) > 8);
    }
    if (!found) continue;
    const angle = rng.range(0, Math.PI * 2);
    const heading = awayFromAxes(Math.cos(angle), Math.sin(angle));           // the same 12 degree rule as at a bounce
    patrols.push(makePatrol(x, y, heading.x * info.speed, heading.y * info.speed));
  }
  return patrols;
}
