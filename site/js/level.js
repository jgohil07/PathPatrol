/* Builds a level from (number, seed): the frame, the obstacle blocks and the patrols' starting
   positions and headings. Only the layout stream is used, so the same (seed, number) always gives
   the same level, whatever the player did in earlier levels. */
import { BOARD_W, BOARD_H, CELLS_PER_UNIT as S, FRAME_UNITS, KINDS, levelInfo } from './config.js';
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
  const shape = info.special === 'shape' ? stampShape(grid, rng) : null;        // (only special levels draw from the stream for it)
  const obstacles = placeObstacles(grid, rng, info.obstacles);
  const initialPlayable = grid.countField();
  const patrols = placePatrols(grid, rng, info);
  return { number, info, shape, obstacles, initialPlayable, patrols, cleared: 0, routes: [] };
}

/* --- shaped boards ------------------------------------------------------------------------------------------------------

   Six outlines, each a list of solid pieces in board units (rectangles [x0, y0, x1, y1] and triangles [[x, y] x 3]), laid
   inside the frame before the obstacles. Every one leaves a single connected field with corridors at least 16 units wide,
   so patrols and routes pass everywhere; obstacles keep 3 units clear of any solid, so they cannot close a corridor. A
   seeded mirror in x and y gives each shape up to four orientations. */
export const SHAPES = Object.freeze({
  cross: [[2, 2, 32, 20], [88, 2, 118, 20], [2, 52, 32, 70], [88, 52, 118, 70]],
  ring: [[42, 24, 78, 48]],
  hourglass: [[[38, 2], [82, 2], [60, 28]], [[38, 70], [82, 70], [60, 44]]],
  ell: [[64, 2, 118, 32]],
  diamond: [[[2, 2], [36, 2], [2, 24]], [[118, 2], [84, 2], [118, 24]], [[2, 70], [36, 70], [2, 48]], [[118, 70], [84, 70], [118, 48]]],
  bays: [[56, 2, 64, 26], [56, 46, 64, 70]],
});
export const SHAPE_NAMES = Object.freeze(Object.keys(SHAPES));

function insideTriangle(px, py, [[ax, ay], [bx, by], [cx, cy]]) {
  const d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by);
  const d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy);
  const d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
}

function stampShape(grid, rng) {
  const name = rng.pick(SHAPE_NAMES);
  const flipX = rng.float() < 0.5, flipY = rng.float() < 0.5;
  for (let cy = 0; cy < grid.h; cy++) {
    for (let cx = 0; cx < grid.w; cx++) {
      let x = (cx + 0.5) / S, y = (cy + 0.5) / S;                       // the cell's centre, in board units
      if (flipX) x = BOARD_W - x;
      if (flipY) y = BOARD_H - y;
      for (const piece of SHAPES[name]) {
        const hit = piece.length === 4 && typeof piece[0] === 'number'
          ? x >= piece[0] && x < piece[2] && y >= piece[1] && y < piece[3]
          : insideTriangle(x, y, piece);
        if (hit) { grid.set(cx, cy, BORDER); break; }
      }
    }
  }
  return { name, flipX, flipY };
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

/* Clearance from walls and spacing between patrols grow with a patrol's size: SPAWN_CLEAR beyond its radius, and
   SPAWN_GAP between two discs. For two standard patrols that is exactly the 2.2 u and 8 u every level used before kinds
   existed, so levels made only of standard patrols are unchanged. */
const SPAWN_CLEAR = 0.85;
const SPAWN_GAP = 5.3;

function placePatrols(grid, rng, info) {
  const patrols = [];
  for (let i = 0; i < info.patrols; i++) {
    const kind = info.kinds[i] || 'standard', r = KINDS[kind].radius;
    let x = 0, y = 0, found = false;
    for (let tries = 0; tries < SPAWN_ATTEMPTS && !found; tries++) {
      x = rng.range(5, BOARD_W - 5);
      y = rng.range(5, BOARD_H - 5);
      found = !grid.circleHitsSolid(x, y, r + SPAWN_CLEAR) && patrols.every((p) => Math.hypot(p.x - x, p.y - y) > p.r + r + SPAWN_GAP);
    }
    if (!found) continue;
    const angle = rng.range(0, Math.PI * 2);
    const heading = awayFromAxes(Math.cos(angle), Math.sin(angle));           // the same 12 degree rule as at a bounce
    const speed = info.speed * KINDS[kind].speed;
    patrols.push(makePatrol(x, y, heading.x * speed, heading.y * speed, kind));
  }
  return patrols;
}
