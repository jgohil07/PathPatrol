/* Steering: hunters (and the boss) go after the pen.

   While a route is being drawn, a patrol whose kind can turn (KINDS[kind].turn) first winds up for KINDS[kind].windup
   seconds, flying on exactly as before while it shows that it has noticed (render.js draws the wind-up), and then turns
   towards the tip of the route, never faster than its turn rate, keeping its speed. The moment the route ends (it closed,
   was lifted, was hit), it forgets and flies straight on. A confident swipe outruns it; a hesitant one is caught. Qix's
   Fuse punishes hesitation the same way.

   It runs in the game's step, before the physics moves anyone, and only touches a steering patrol's velocity, so physics.js
   knows nothing about routes. Bounces keep their 12 degree rule: a steering patrol may point along an axis, and its next
   bounce turns it off again. */
import { KINDS } from './config.js';

export const IDLE = -1;                    // a patrol's `windup` when no route is being drawn

/* dt: the seconds the patrols move this step (already slowed by a power-up; 0 while frozen). */
export function steer(patrols, route, dt) {
  const drawing = route.mode === 'drawing';
  for (const p of patrols) {
    const kind = KINDS[p.kind];
    if (!kind || !kind.turn) continue;
    if (!drawing) { p.windup = IDLE; p.chasing = false; continue; }
    if (!p.chasing && (p.windup === undefined || p.windup === IDLE)) p.windup = kind.windup;          // it has just noticed
    if (!p.chasing) {
      p.windup -= dt;
      if (p.windup > 0) continue;
      p.windup = 0;
      p.chasing = true;
    }
    if (dt <= 0 || p.speed === 0) continue;
    const want = Math.atan2(route.tip.y - p.y, route.tip.x - p.x);
    const now = Math.atan2(p.vy, p.vx);
    let turn = want - now;
    turn -= Math.PI * 2 * Math.round(turn / (Math.PI * 2));                                         // the short way round
    const most = kind.turn * dt;
    const a = now + Math.max(-most, Math.min(most, turn));
    p.vx = Math.cos(a) * p.speed;
    p.vy = Math.sin(a) * p.speed;
  }
}

/* Where a patrol is in its steering, for drawing and tests: 'idle', 'windup' (with how far through, 0..1) or 'chase'. */
export function steeringOf(p) {
  const kind = KINDS[p.kind];
  if (!kind || !kind.turn) return { state: 'none', t: 0 };
  if (p.chasing) return { state: 'chase', t: 1 };
  if (p.windup !== undefined && p.windup !== IDLE) return { state: 'windup', t: Math.max(0, Math.min(1, 1 - p.windup / kind.windup)) };
  return { state: 'idle', t: 0 };
}
