/* Edge tracers: amber diamonds that crawl the boundary of the open field.

   They patrol the contour loops (see contour.js) at TRACER.speed. A finger resting on an edge is safe. But when a tracer
   reaches the cell a live route was started from, it chases along the route's own cells at TRACER.chase times its speed, and
   if it catches the tip that is a hit. A fast swipe outruns it; slow, hesitant drawing does not. If the route closes or is
   cancelled first, the tracer goes back to patrolling. After every capture the contours are traced again and each tracer
   is put on the nearest remaining edge.

   Spawning uses its own random stream, derived from (seed, level), so adding tracers changed no layout: the same board
   still gives the same obstacles and patrols, and the daily board is the same for everyone. */
import { CELLS_PER_UNIT as S } from './config.js';
import { Rng } from './rng.js';
import { traceContours, pointAt, nearestEdge } from './contour.js';

export const TRACER = Object.freeze({
  speed: 22,             // board units per second along the contour
  chase: 1.2,            // times that, while chasing a route
  reach: 2,              // cells: how near the route's start cell a tracer must come to notice it
  trailEvery: 3,         // physics steps between trail samples
  trailLength: 6,
});

const mod = (a, n) => ((a % n) + n) % n;

export class Tracers {
  constructor(game) {
    this.game = game;
    this.list = [];
    this.loops = [];
  }

  /* A new level: trace the contours and place this level's tracers, evenly around the outer boundary. */
  reset(level, seed) {
    this.list = [];
    this.loops = traceContours(this.game.grid).loops;
    const want = level.info.tracers;
    if (!want || !this.loops.length) return;
    const rng = new Rng(`${seed}|tracers|${level.number}`);
    const loop = this.loops[0];
    const offset = rng.float() * loop.n;
    for (let i = 0; i < want; i++) {
      const tracer = this._make(0, mod(offset + (i * loop.n) / want, loop.n), rng.float() < 0.5 ? 1 : -1);
      this.list.push(tracer);
    }
  }

  _make(loop, t, dir) {
    const tracer = { loop, t, dir, mode: 'patrol', chase: 0, x: 0, y: 0, px: 0, py: 0, trail: new Float32Array(TRACER.trailLength * 2), trailHead: 0, trailLen: 0, tick: 0 };
    this._place(tracer);
    tracer.px = tracer.x;
    tracer.py = tracer.y;
    return tracer;
  }

  _place(tracer) {
    const loop = this.loops[tracer.loop];
    if (!loop) return;
    const p = pointAt(loop, tracer.t);
    tracer.x = p.x;
    tracer.y = p.y;
  }

  /* After a capture (or a restore): the contours changed. Trace them again and put each tracer on the nearest edge. */
  refresh() {
    this.loops = traceContours(this.game.grid).loops;
    for (const tracer of this.list) {
      const spot = nearestEdge(this.loops, tracer.x, tracer.y);
      tracer.mode = 'patrol';
      if (!spot) { tracer.loop = -1; continue; }
      tracer.loop = spot.loop;
      tracer.t = spot.k;
      this._place(tracer);
      tracer.px = tracer.x;
      tracer.py = tracer.y;
    }
  }

  /* --- per physics step -------------------------------------------------------------------------- */

  update(dt, scale = 1) {
    const { game } = this;
    const route = game.route;
    const drawing = route.mode === 'drawing' && route.cells.length > 0;
    const step = TRACER.speed * S * scale * dt;                          // cells this step
    for (const tracer of this.list) {
      tracer.px = tracer.x;
      tracer.py = tracer.y;
      if (scale <= 0) continue;                                          // frozen: standing still, and it cannot catch anything either
      if (tracer.mode === 'chase') {
        if (!drawing) { this._endChase(tracer); continue; }
        this._chase(tracer, step * TRACER.chase, route);
      } else {
        const loop = this.loops[tracer.loop];
        if (!loop) continue;
        tracer.t = mod(tracer.t + tracer.dir * step, loop.n);
        this._place(tracer);
        if (drawing && this._atAnchor(loop, tracer, route)) this._startChase(tracer);
      }
      if (++tracer.tick % TRACER.trailEvery === 0) this._trail(tracer);
    }
  }

  _atAnchor(loop, tracer, route) {
    const cell = loop.solid[Math.floor(tracer.t) % loop.n];
    if (cell < 0) return false;
    const w = this.game.grid.w;
    return Math.abs((cell % w) - route.anchor.cx) <= TRACER.reach && Math.abs(Math.floor(cell / w) - route.anchor.cy) <= TRACER.reach;
  }

  _startChase(tracer) {
    tracer.mode = 'chase';
    tracer.chase = 0;
    this.game.emit('tracer', { type: 'chase', x: tracer.x, y: tracer.y });
  }

  /* Back to patrolling. Its place along the loop was never changed by the chase (only where it is drawn), so it simply
     carries on from where it noticed the route. */
  _endChase(tracer) {
    tracer.mode = 'patrol';
    this._place(tracer);
    tracer.px = tracer.x;
    tracer.py = tracer.y;
  }

  /* Along the route's cells, in the order they were laid. Reaching the tip is a hit. */
  _chase(tracer, cells, route) {
    const last = route.cells.length - 1;
    tracer.chase = Math.min(last, tracer.chase + cells);
    const w = this.game.grid.w;
    const i = Math.floor(tracer.chase), f = tracer.chase - i;
    const a = route.cells[i], b = route.cells[Math.min(last, i + 1)];
    tracer.x = ((a % w) + ((b % w) - (a % w)) * f + 0.5) / S;
    tracer.y = (Math.floor(a / w) + (Math.floor(b / w) - Math.floor(a / w)) * f + 0.5) / S;
    if (tracer.chase >= last) {
      this.game.emit('tracer', { type: 'caught', x: tracer.x, y: tracer.y });
      route.hitByTracer();
      this._endChase(tracer);
    }
  }

  _trail(tracer) {
    const i = tracer.trailHead;
    tracer.trail[i * 2] = tracer.x;
    tracer.trail[i * 2 + 1] = tracer.y;
    tracer.trailHead = (i + 1) % TRACER.trailLength;
    if (tracer.trailLen < TRACER.trailLength) tracer.trailLen++;
  }

  /* --- saving ---------------------------------------------------------------------------------------- */

  /* [loop, position along it, direction] for each tracer. Only patrolling tracers are saved: a route is never resumed. */
  toJSON() { return this.list.map((t) => [Math.max(0, t.loop), t.t, t.dir]); }

  /* Put tracers back exactly where a snapshot had them. The loops are traced again from the restored grid, which is
     deterministic, so the same loop numbers come back. Returns false if they do not fit (the caller respawns). */
  restore(rows) {
    this.loops = traceContours(this.game.grid).loops;
    this.list = [];
    for (const [loop, t, dir] of rows) {
      if (!this.loops[loop] || t < 0 || t >= this.loops[loop].n) return false;
      this.list.push(this._make(loop, t, dir));
    }
    return true;
  }

  /* For tests: replace the tracers with these ({ x, y, dir }), each snapped to the nearest edge. */
  place(rows) {
    this.list = [];
    for (const { x, y, dir = 1 } of rows) {
      const spot = nearestEdge(this.loops, x, y);
      if (spot) this.list.push(this._make(spot.loop, spot.k, dir));
    }
  }
}
