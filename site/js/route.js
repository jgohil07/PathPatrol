/* The route engine: lays a route under the pointer, and closes, cancels or loses it.

   Input-agnostic: mouse, touch, pen and (later) keyboard all drive it through begin / move / end, in
   board units. Every bit of work happens inside those calls, with no timers. A route cell exists in the
   grid the moment the pointer passes over it, and a patrol touching one costs a life at that same
   moment. The prototype made you drag a preview, released, and then waited for a line to grow at a
   fixed speed; that wait is the latency this replaces.

   Modes
     idle     nothing armed: no pointer, or a pointer that has not touched safe ground yet
     armed    the pointer is on safe ground (wall, frame or obstacle) and slides along it
     drawing  the pointer has left safe ground; every open cell it crosses becomes ROUTE
     spent    a patrol hit the route; the pointer is ignored until it lifts

   A route closes when the pointer re-enters safe ground: its cells become wall and the game claims every
   area without a patrol in it. Lifting mid-field, a pointer cancel or a pause erases the route for free. */
import { CELLS_PER_UNIT as S, BOARD_W, BOARD_H, SCORE } from './config.js';
import { FIELD, ROUTE, toCell, cellDistanceSq, walkCells } from './grid.js';

export const MODE = Object.freeze({ IDLE: 'idle', ARMED: 'armed', DRAWING: 'drawing', SPENT: 'spent' });

export const MIN_ROUTE_CELLS = 3;       // a route this short that comes straight back is jitter, not a route
const SAMPLE_SPACING = 0.15;            // world units between stored polyline points
const OVERSHOOT = 1;                    // pointer positions are clamped this far outside the board
const SIMPLIFY_TOLERANCE = 0.1;         // world units, when a finished route is stored for drawing

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function segmentDistanceSq(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : clamp(((px - ax) * dx + (py - ay) * dy) / len, 0, 1);
  const x = ax + dx * t - px, y = ay + dy * t - py;
  return x * x + y * y;
}

/* Ramer-Douglas-Peucker on a flat [x0, y0, x1, y1, ...] polyline. */
export function simplify(points, tolerance) {
  const n = points.length / 2;
  if (n <= 2) return points.slice();
  const keep = new Uint8Array(n);
  keep[0] = keep[n - 1] = 1;
  const limit = tolerance * tolerance;
  const stack = [[0, n - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let far = -1, farDist = limit;
    for (let i = a + 1; i < b; i++) {
      const d = segmentDistanceSq(points[i * 2], points[i * 2 + 1], points[a * 2], points[a * 2 + 1], points[b * 2], points[b * 2 + 1]);
      if (d > farDist) { far = i; farDist = d; }
    }
    if (far >= 0) { keep[far] = 1; stack.push([a, far], [far, b]); }
  }
  const out = [];
  for (let i = 0; i < n; i++) if (keep[i]) out.push(points[i * 2], points[i * 2 + 1]);
  return out;
}

export class RouteEngine {
  constructor(game) {
    this.game = game;
    this.down = false;                    // a pointer is down, whether or not it has drawn anything
    this.mode = MODE.IDLE;
    this.coarse = false;                  // finger (true) or mouse/pen (false): only sizes the on-screen ring
    this.cells = [];                      // grid indices of this route's ROUTE cells, in the order laid
    this.points = [];                     // flat [x, y, ...] polyline of the route so far, board units
    this.anchor = { cx: 0, cy: 0 };       // the safe cell the route grows from / the pointer slides along
    this.tip = { x: 0, y: 0 };            // where the pointer is now, board units
    this.closeCalls = new Set();          // patrols that came within SCORE.closeCall.distance of this route without hitting it; emptied when a route starts
    this._last = { x: 0, y: 0 };          // the previous sample: the walk between samples starts here
    game.on('phase', ({ phase }) => { if (phase !== 'playing') this.cancel('phase'); });
    game.on('level', () => this._forget());
  }

  /* --- input ------------------------------------------------------------------------------ */

  /* The pointer went down at (x, y). `snap` is how far (world units) from safe ground it may start and
     still be pulled onto it. Returns whether a route is armed; if not, nothing is lost. */
  begin(x, y, snap = 0) {
    if (!this.game.isPlaying()) return false;
    this.cancel('restart');
    this.down = true;
    this._last.x = this.tip.x = x;
    this._last.y = this.tip.y = y;
    const { grid } = this.game;
    const cx = toCell(x), cy = toCell(y);
    if (grid.isSolid(cx, cy)) { this._arm(cx, cy); return true; }
    const near = snap > 0 ? this._nearestSolid(x, y, snap) : null;
    if (near) {
      this._arm(near.cx, near.cy);
      this._last.x = (near.cx + 0.5) / S;            // the walk to the pointer starts from the safe cell:
      this._last.y = (near.cy + 0.5) / S;            // that is the connecting segment
      this.move(x, y);
      return true;
    }
    this.game.emit('route', { type: 'edge-hint' });
    return false;
  }

  move(x, y) {
    if (!this.down || !this.game.isPlaying()) return;
    x = clamp(x, -OVERSHOOT, BOARD_W + OVERSHOOT);
    y = clamp(y, -OVERSHOOT, BOARD_H + OVERSHOOT);
    if (this.mode !== MODE.SPENT) {
      walkCells(this._last.x * S, this._last.y * S, x * S, y * S, (cx, cy) => this._enter(cx, cy));
    }
    this._last.x = this.tip.x = x;
    this._last.y = this.tip.y = y;
    if (this.mode === MODE.DRAWING) this._sample(x, y);
  }

  /* The pointer lifted or was taken away. Mid-field, that erases the route without costing a life. */
  end(reason = 'lift') {
    this.cancel(reason);
    this.down = false;
  }

  /* Erase a route in progress and stand down. The pointer may still be down (a pause, a restart). */
  cancel(reason = 'cancel') {
    if (this.mode === MODE.DRAWING) this._erase(reason);
    this.mode = MODE.IDLE;
  }

  /* Called by the game after every physics step: a patrol may have flown into the route, or just missed it.
     A miss is remembered once per patrol per route and paid out only if the route closes (see _close), so
     drawing near a patrol and lifting again is not a way to farm points. */
  afterStep() {
    if (this.mode !== MODE.DRAWING) return;
    const { grid, level } = this.game;
    const near = SCORE.closeCall.distance;
    for (let i = 0; i < level.patrols.length; i++) {
      const p = level.patrols[i];
      if (grid.circleHitsRoute(p.x, p.y, p.r)) { this._hit(); return; }
      if (!this.closeCalls.has(i) && grid.circleHitsRoute(p.x, p.y, near)) {
        this.closeCalls.add(i);
        this.game.emit('route', { type: 'closecall', patrol: i });
      }
    }
  }

  /* --- internals -------------------------------------------------------------------------- */

  _arm(cx, cy) {
    this.mode = MODE.ARMED;
    this.anchor.cx = cx;
    this.anchor.cy = cy;
    this.points.length = 0;
  }

  /* One cell entered by the pointer's path. Returns true to stop walking. */
  _enter(cx, cy) {
    const v = this.game.grid.get(cx, cy);                     // out of bounds reads as BORDER
    switch (this.mode) {
      case MODE.IDLE:                                         // a touch that started away from any edge
        if (v !== FIELD && v !== ROUTE) this._arm(cx, cy);
        return false;
      case MODE.ARMED:
        if (v === FIELD) { this._startDrawing(); return this._lay(cx, cy); }
        if (v !== ROUTE) { this.anchor.cx = cx; this.anchor.cy = cy; }       // sliding along safe ground
        return false;
      case MODE.DRAWING:
        if (v === FIELD) return this._lay(cx, cy);
        if (v === ROUTE) return false;                        // crossing its own route is allowed
        return this._close(cx, cy);                           // safe ground: the route ends here
      default:
        return true;
    }
  }

  _startDrawing() {
    this.mode = MODE.DRAWING;
    this.cells.length = 0;
    this.points.length = 0;
    this.closeCalls.clear();
    this.points.push((this.anchor.cx + 0.5) / S, (this.anchor.cy + 0.5) / S);
    this.game.emit('route', { type: 'start' });
  }

  /* Turn one open cell into route, and check it against every patrol right now: drawing into a patrol
     counts. Returns true if that hit ended the route. */
  _lay(cx, cy) {
    const { grid, level } = this.game;
    const i = grid.index(cx, cy);
    grid.cells[i] = ROUTE;
    this.cells.push(i);
    for (const p of level.patrols) {
      if (cellDistanceSq(cx, cy, p.x, p.y) < p.r * p.r) { this._hit(); return true; }
    }
    return false;
  }

  _close(cx, cy) {
    if (this.cells.length < MIN_ROUTE_CELLS) {                // jitter at the edge, not a route
      this._erase('short');
      this._arm(cx, cy);
      return false;
    }
    const cells = this.cells;
    const path = this.points.slice();
    path.push((cx + 0.5) / S, (cy + 0.5) / S);
    const closeCalls = this.closeCalls.size;
    this.cells = [];
    this.points = [];
    this._arm(cx, cy);                                        // the pointer keeps sliding from where it landed
    this.game.commitCapture(cells, { polyline: simplify(path, SIMPLIFY_TOLERANCE), closeCalls });
    return !this.game.isPlaying();                            // the capture may have won the level
  }

  _hit() {
    this._erase('hit', true);
    this.mode = MODE.SPENT;
    this.game.emit('route', { type: 'hit' });
    this.game.loseLife();
  }

  _erase(reason, quiet = false) {
    const { grid } = this.game;
    const count = this.cells.length;
    for (const i of this.cells) if (grid.cells[i] === ROUTE) grid.cells[i] = FIELD;
    this.cells.length = 0;
    this.points.length = 0;
    if (!quiet && count > 0) this.game.emit('route', { type: 'cancel', reason, cells: count });
  }

  /* The level was rebuilt underneath us: the grid is already clean, so just forget. */
  _forget() {
    this.cells.length = 0;
    this.points.length = 0;
    this.mode = MODE.IDLE;
  }

  _sample(x, y) {
    const pts = this.points, n = pts.length;
    if (n >= 4) {
      const dx = x - pts[n - 2], dy = y - pts[n - 1];
      if (dx * dx + dy * dy < SAMPLE_SPACING * SAMPLE_SPACING) return;       // the tip carries the exact position
    }
    pts.push(x, y);
  }

  /* The closest safe cell to (x, y) within `radius` world units, if any. */
  _nearestSolid(x, y, radius) {
    const { grid } = this.game;
    const reach = Math.ceil(radius * S) + 1;
    const cx0 = toCell(x), cy0 = toCell(y);
    let best = null, bestSq = radius * radius;
    for (let dy = -reach; dy <= reach; dy++) {
      for (let dx = -reach; dx <= reach; dx++) {
        const cx = cx0 + dx, cy = cy0 + dy;
        if (!grid.isSolid(cx, cy)) continue;
        const d = cellDistanceSq(cx, cy, x, y);
        if (d < bestSq) { bestSq = d; best = { cx, cy }; }
      }
    }
    return best;
  }
}
