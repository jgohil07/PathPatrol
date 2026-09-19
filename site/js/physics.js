/* Patrol physics.

   A patrol is a disc moving at constant speed. It bounces off the cell grid like a billiard ball: off the
   frame, the obstacles and every wall the player has built, including the staircase a freehand curve
   leaves behind. How:

   - The contact normal comes from every cell the disc overlaps (each cell's closest point to the centre,
     weighted by how deep it is), so a diagonal staircase reflects like a smooth diagonal and a convex
     corner like a single point.
   - The disc is pushed out along that normal by the penetration and its velocity is mirrored about it, but
     only if it is moving into the wall. For a flat wall that is the exact billiard path, not an
     approximation: the push-back is the mirror image of the overshoot.
   - Patrols collide with each other: an elastic collision between equal masses along the line of centres.
   - Every patrol's speed is held at its level speed, and at a bounce a direction closer than 12 degrees to
     a screen axis is turned away from it, so nothing settles into an endless horizontal or vertical shuttle.

   The prototype flipped x and y separately: right on straight walls, wrong on every diagonal, and patrols
   passed straight through each other. */
import { PATROL_RADIUS, CELLS_PER_UNIT, MIN_BOUNCE_ANGLE, HEADING_TAU } from './config.js';
import { SOLID_MASK } from './grid.js';

export const TRAIL_LENGTH = 9;

/* Diagnostics for the tests, a couple of increments a step: how many sub-steps were made, and how many
   depenetration passes each contact needed (passes[n] contacts took n passes). */
export const stats = { substeps: 0, passes: new Array(13).fill(0) };

const MAX_MOVE = 0.25;            // of the radius, per sub-step: nothing can tunnel through a wall
const MAX_ITERATIONS = 12;         // depenetration passes per patrol per sub-step

export function makePatrol(x, y, vx, vy) {
  return {
    x, y, vx, vy,
    px: x, py: y,                                  // position one step ago, for interpolated drawing
    r: PATROL_RADIUS,
    speed: Math.hypot(vx, vy),                     // held constant by the physics; the level sets it
    heading: Math.atan2(vy, vx),                   // the drawn direction: eases towards the velocity's
    trail: new Float32Array(TRAIL_LENGTH * 2),     // ring buffer of recent positions
    trailHead: 0, trailLen: 0, trailTick: 0,
  };
}

function pushTrail(p) {
  const i = p.trailHead;
  p.trail[i * 2] = p.x;
  p.trail[i * 2 + 1] = p.y;
  p.trailHead = (i + 1) % TRAIL_LENGTH;
  if (p.trailLen < TRAIL_LENGTH) p.trailLen++;
}

/* --- directions ------------------------------------------------------------------------------ */

/* The unit direction (ux, uy), turned away from the screen axes if it is within `minAngle` of one. A
   component that is exactly zero is turned the way (biasX, biasY) points. Writes into `out`. */
export function awayFromAxes(ux, uy, minAngle = MIN_BOUNCE_ANGLE, biasX = 1, biasY = 1, out = { x: 0, y: 0 }) {
  const lo = Math.sin(minAngle), hi = Math.cos(minAngle);
  const side = (v, bias) => (v !== 0 ? Math.sign(v) : Math.sign(bias) || 1);
  if (Math.abs(uy) < lo) { out.y = side(uy, biasY) * lo; out.x = side(ux, biasX) * hi; }
  else if (Math.abs(ux) < lo) { out.x = side(ux, biasX) * lo; out.y = side(uy, biasY) * hi; }
  else { out.x = ux; out.y = uy; }
  return out;
}

const TURNED = { x: 0, y: 0 };

/* Put a patrol's velocity back at its own speed (a collision changes it) and, if `minAngle` > 0, keep it
   off the axes. (nx, ny) is the contact normal: a patrol left at rest leaves along it. */
function steer(p, nx, ny, minAngle) {
  if (p.speed === 0) { p.vx = 0; p.vy = 0; return; }
  let ux, uy, len = Math.hypot(p.vx, p.vy);
  if (len < 1e-9) {
    len = Math.hypot(nx, ny) || 1;
    ux = (nx || 1) / len; uy = ny / len;
  } else {
    ux = p.vx / len; uy = p.vy / len;
  }
  if (minAngle > 0) { awayFromAxes(ux, uy, minAngle, nx, ny, TURNED); ux = TURNED.x; uy = TURNED.y; }
  p.vx = ux * p.speed;
  p.vy = uy * p.speed;
}

/* --- walls ----------------------------------------------------------------------------------- */

/* How far beyond the radius (world units) the wall is examined: three neighbourhoods, narrowest first.
   Exported so tests can vary them. */
export const tuning = { reach: [0.75, 1.75, 3.0], scatter: 0.32 };
const AXIS_SNAP = Math.cos((3 * Math.PI) / 180);        // a normal this close to an axis is made exact
const ACC = new Float64Array(3 * 6);                     // per neighbourhood: weight, sum x, sum y, sum xx, sum xy, sum yy

/* Where a disc at (x, y) overlaps the cells whose kind is in `mask`. Writes into `out` the contact normal
   (a unit vector pointing out of the wall) and the depth of the deepest overlap; returns false if the disc
   is clear.

   The normal is not taken from any one cell. A staircase is not a surface: the closest cell corner would
   give a normal that jitters with every step, and a thin wall's cells scatter a quarter of a unit either
   side of the line it was drawn along. Instead a straight line is fitted to the wall's surface cells
   around the contact (their principal axis), and the normal is perpendicular to it, on the disc's side.
   How much wall to fit is decided by how straight it is: the largest of three neighbourhoods whose cells
   lie within a third of a unit of their line. A wide one averages the staircase out; near a corner it
   would also include the other wall, so its scatter is large and a narrower one is used instead. Only
   cells connected to the ones touching the disc count, so a separate wall nearby cannot skew the fit. A
   normal within 3 degrees of an axis is snapped to it, which makes the frame, the obstacles and every
   straight vertical or horizontal route bounce exactly. */
export function findContact(grid, x, y, r, mask, out) {
  const S = CELLS_PER_UNIT, W = grid.w, H = grid.h;
  const rr = r * r;
  const { cells, _queue: queue, _mark: mark } = grid;
  const stamp = ++grid._markId;
  let best = 0, deepX = 0, deepY = 0, tail = 0;
  const x0 = Math.floor((x - r) * S), x1 = Math.floor((x + r) * S);
  const y0 = Math.floor((y - r) * S), y1 = Math.floor((y + r) * S);
  for (let cy = y0; cy <= y1; cy++) {
    for (let cx = x0; cx <= x1; cx++) {
      if (((mask >> grid.get(cx, cy)) & 1) === 0) continue;
      const left = cx / S, right = (cx + 1) / S, top = cy / S, bottom = (cy + 1) / S;
      const qx = x < left ? left : x > right ? right : x;      // the point of the cell nearest the centre
      const qy = y < top ? top : y > bottom ? bottom : y;
      let dx = x - qx, dy = y - qy;
      const d2 = dx * dx + dy * dy;
      if (d2 >= rr) continue;
      let pen;
      if (d2 > 1e-18) {
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        pen = r - d;
      } else {                                                 // the centre is inside the cell: leave by the nearest face
        const toLeft = x - left, toRight = right - x, toTop = y - top, toBottom = bottom - y;
        const m = Math.min(toLeft, toRight, toTop, toBottom);
        if (m === toLeft) { dx = -1; dy = 0; } else if (m === toRight) { dx = 1; dy = 0; } else if (m === toTop) { dx = 0; dy = -1; } else { dx = 0; dy = 1; }
        pen = r + m;
      }
      if (pen > best) { best = pen; deepX = dx; deepY = dy; }
      if (grid.inBounds(cx, cy)) { const i = cy * W + cx; if (mark[i] !== stamp) { mark[i] = stamp; queue[tail++] = i; } }
    }
  }
  if (best === 0) return false;

  // Walk outwards from the touching cells through connected solid cells. Each surface cell (one with an
  // open neighbour) is added to every neighbourhood it falls in.
  const reaches = tuning.reach, reachSq = [0, 0, 0];
  for (let k = 0; k < 3; k++) { const q = r + reaches[k]; reachSq[k] = q * q; }
  const widest = reachSq[2];
  ACC.fill(0);
  for (let head = 0; head < tail; head++) {
    const i = queue[head], cx = i % W, cy = (i / W) | 0;
    const px = (cx + 0.5) / S, py = (cy + 0.5) / S, dx = px - x, dy = py - y, d2 = dx * dx + dy * dy;
    let surface = false;
    for (let k = 0; k < 4; k++) {
      const nx2 = k === 0 ? cx - 1 : k === 1 ? cx + 1 : cx, ny2 = k === 2 ? cy - 1 : k === 3 ? cy + 1 : cy;
      if (nx2 < 0 || ny2 < 0 || nx2 >= W || ny2 >= H) continue;                       // off the board counts as solid
      const j = ny2 * W + nx2;
      if (((mask >> cells[j]) & 1) === 0) surface = true;
      else if (mark[j] !== stamp) {
        const ex = (nx2 + 0.5) / S - x, ey = (ny2 + 0.5) / S - y;
        if (ex * ex + ey * ey < widest) { mark[j] = stamp; queue[tail++] = j; }
      }
    }
    if (!surface) continue;
    for (let n = 0; n < 3; n++) {
      if (d2 >= reachSq[n]) continue;
      const w = 1 - d2 / reachSq[n], o = n * 6;
      ACC[o] += w; ACC[o + 1] += w * px; ACC[o + 2] += w * py;
      ACC[o + 3] += w * px * px; ACC[o + 4] += w * px * py; ACC[o + 5] += w * py * py;
    }
  }

  let nx = deepX, ny = deepY;                                   // if no neighbourhood is a straight wall, the touching cell decides
  for (let n = 2; n >= 0; n--) {
    const o = n * 6, wsum = ACC[o];
    if (wsum < 1e-9) continue;
    const mx = ACC[o + 1] / wsum, my = ACC[o + 2] / wsum;
    const cxx = ACC[o + 3] / wsum - mx * mx, cxy = ACC[o + 4] / wsum - mx * my, cyy = ACC[o + 5] / wsum - my * my;
    const mean = (cxx + cyy) / 2, spread = Math.sqrt(Math.max(0, mean * mean - (cxx * cyy - cxy * cxy)));
    const major = mean + spread, minor = Math.max(0, mean - spread);
    if (Math.sqrt(minor) > tuning.scatter || Math.sqrt(major) < 0.35) continue;      // not straight, or too few cells to say
    let tx, ty;                                                 // the wall's direction: the major axis
    if (Math.abs(cxy) > 1e-12) { tx = major - cyy; ty = cxy; } else if (cxx >= cyy) { tx = 1; ty = 0; } else { tx = 0; ty = 1; }
    const tl = Math.hypot(tx, ty); tx /= tl; ty /= tl;
    nx = -ty; ny = tx;
    if (nx * (x - mx) + ny * (y - my) < 0) { nx = -nx; ny = -ny; }                   // on the disc's side of the wall
    break;
  }
  // A surface normal is never more than 90 degrees from the direction out of the cell that is touching. If
  // the fit is far from it (the disc is inside a thick wall, say), trust the cell: pushing along a wrong-way
  // normal would drive the disc through the wall.
  if (nx * deepX + ny * deepY < 0.5) { nx = deepX; ny = deepY; }
  if (Math.abs(nx) > AXIS_SNAP) { nx = Math.sign(nx); ny = 0; }
  else if (Math.abs(ny) > AXIS_SNAP) { ny = Math.sign(ny); nx = 0; }
  // `best` is the overlap along the touching cell's own direction. Moving along the normal clears it only
  // by the cosine of the angle between them, so the distance to move is larger (by at most 2x).
  out.nx = nx; out.ny = ny;
  out.pen = best / Math.max(nx * deepX + ny * deepY, 0.5);
  return true;
}

const CONTACT = { nx: 0, ny: 0, pen: 0 };

/* Push a patrol out of any wall it overlaps, and mirror its velocity if it was moving into it. The mirror
   uses the first contact only: pushing out may take a few passes on a staircase, but it is one bounce, not
   one per stair.

   `h` is the time the patrol just moved for. When it bounces, the overlap is the part of that move made
   after it met the wall, and the true path spends that time going away again, so the patrol is pushed out
   twice as far: once to undo the overshoot and once for the mirrored travel. That puts it exactly where a
   real ball would be (for a flat wall, to rounding error). The extra push is capped by how far the patrol
   actually moved into the wall, so an overlap that motion did not cause (a wall built on a patrol) gets
   the plain push. Returns whether it bounced. */
export function resolveWalls(p, grid, mask = SOLID_MASK, minAngle = MIN_BOUNCE_ANGLE, h = 0) {
  let bounced = false, nx = 0, ny = 0, passes = 0;
  for (let i = 0; i < MAX_ITERATIONS; i++) {
    if (!findContact(grid, p.x, p.y, p.r, mask, CONTACT)) break;
    passes++;
    let push = CONTACT.pen;
    if (i === 0) {
      const vn = p.vx * CONTACT.nx + p.vy * CONTACT.ny;
      if (vn < 0) {
        push += Math.min(CONTACT.pen, -vn * h);
        p.vx -= 2 * vn * CONTACT.nx;
        p.vy -= 2 * vn * CONTACT.ny;
        bounced = true;
        nx = CONTACT.nx; ny = CONTACT.ny;
      }
    }
    p.x += CONTACT.nx * push;
    p.y += CONTACT.ny * push;
  }
  if (passes > 0) stats.passes[passes]++;
  if (bounced) steer(p, nx, ny, minAngle);
  return bounced;
}

/* --- patrols against each other ------------------------------------------------------------------ */

/* An elastic collision between two equal-mass discs, if they overlap: push them apart by half the overlap
   each, and if they are closing, exchange their velocity components along the line of centres. That
   conserves momentum and kinetic energy exactly. With `govern`, each patrol is then put back at its own
   speed and kept off the axes, as after a wall bounce. Returns whether they overlapped. */
export function collidePair(a, b, minAngle = MIN_BOUNCE_ANGLE, govern = true) {
  const dx = b.x - a.x, dy = b.y - a.y, reach = a.r + b.r;
  const d2 = dx * dx + dy * dy;
  if (d2 >= reach * reach) return false;
  const d = Math.sqrt(d2);
  const nx = d > 1e-9 ? dx / d : 1, ny = d > 1e-9 ? dy / d : 0;        // from a towards b
  const push = (reach - d) / 2;
  a.x -= nx * push; a.y -= ny * push;
  b.x += nx * push; b.y += ny * push;
  const closing = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
  if (closing > 0) {
    a.vx -= closing * nx; a.vy -= closing * ny;
    b.vx += closing * nx; b.vy += closing * ny;
    if (govern) { steer(a, -nx, -ny, minAngle); steer(b, nx, ny, minAngle); }
  }
  return true;
}

/* --- the step --------------------------------------------------------------------------------- */

/* Advance every patrol by dt seconds: move, bounce off walls, bounce off each other. Sub-steps keep any
   one move under a quarter of a radius. Returns the number of bounces (for tests and sound). */
export function advance(patrols, dt, grid, { mask = SOLID_MASK, minAngle = MIN_BOUNCE_ANGLE } = {}) {
  const n = patrols.length;
  let fastest = 0, bounces = 0;
  for (let i = 0; i < n; i++) {
    const p = patrols[i];
    p.px = p.x; p.py = p.y;
    if (p.speed > fastest) fastest = p.speed;
  }
  const steps = Math.max(1, Math.ceil((fastest * dt) / (MAX_MOVE * PATROL_RADIUS)));
  const h = dt / steps;
  for (let s = 0; s < steps; s++) {
    stats.substeps++;
    for (let i = 0; i < n; i++) { const p = patrols[i]; p.x += p.vx * h; p.y += p.vy * h; }
    for (let i = 0; i < n; i++) if (resolveWalls(patrols[i], grid, mask, minAngle, h)) bounces++;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        if (!collidePair(patrols[i], patrols[j], minAngle)) continue;
        bounces++;
        resolveWalls(patrols[i], grid, mask, minAngle);            // the shove may have pushed one into a wall
        resolveWalls(patrols[j], grid, mask, minAngle);
      }
    }
  }
  const catchUp = 1 - Math.exp(-dt / HEADING_TAU);
  for (let i = 0; i < n; i++) {
    const p = patrols[i];
    if (p.vx !== 0 || p.vy !== 0) {
      let turn = Math.atan2(p.vy, p.vx) - p.heading;
      turn -= Math.PI * 2 * Math.round(turn / (Math.PI * 2));      // the short way round
      p.heading += turn * catchUp;
    }
    if ((p.trailTick++ & 1) === 0) pushTrail(p);                   // every second step: a 60 Hz trail
  }
  return bounces;
}

/* After walls change (a capture): move any patrol clear of them. */
export function settle(patrols, grid) {
  for (const p of patrols) resolveWalls(p, grid, SOLID_MASK, 0);
}
