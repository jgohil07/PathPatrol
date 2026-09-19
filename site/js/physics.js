/* Patrol motion.

   This is the prototype's behaviour carried over unchanged so the rebuild can be checked against it:
   each axis bounces on its own. Phase 3 replaces stepPatrol with real physics (surface normals,
   patrol-vs-patrol collisions, constant speed). */
import { PATROL_RADIUS } from './config.js';

export const TRAIL_LENGTH = 9;

export function makePatrol(x, y, vx, vy) {
  return {
    x, y, vx, vy,
    px: x, py: y,                                  // position one step ago, for interpolated drawing
    r: PATROL_RADIUS,
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

export function stepPatrol(p, dt, grid) {
  p.px = p.x;
  p.py = p.y;
  const distance = Math.hypot(p.vx, p.vy) * dt;
  const steps = Math.max(1, Math.ceil(distance / 0.38));
  const h = dt / steps;
  for (let i = 0; i < steps; i++) {
    const nx = p.x + p.vx * h;
    if (grid.circleHitsSolid(nx, p.y, p.r)) p.vx = -p.vx; else p.x = nx;
    const ny = p.y + p.vy * h;
    if (grid.circleHitsSolid(p.x, ny, p.r)) p.vy = -p.vy; else p.y = ny;
  }
  if ((p.trailTick++ & 1) === 0) pushTrail(p);     // every second step: a 60 Hz trail, as before
}
