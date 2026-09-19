/* Power-ups: one pickup at a time appears on open ground, and drawing through it or claiming the ground it sits on
   takes it. Three kinds, each a timed effect on the game clock (so a pause stops the timer):

     freeze  patrols and tracers stop for 3 s (a frozen patrol still hurts a route that touches it)
     shield  for 5 s the route being drawn is solid: patrols bounce off it instead of hurting it (tracers still can)
     slow    for 5 s patrols move at half speed

   From level 3, a pickup appears every 12-20 s of game time and lasts 10 s. Which kind and when come from the seeded
   event stream, and where from a second stream: the kinds and timings are then the same for everyone on the same
   (seed, level) whatever they do on the board, and only the positions depend on the board. */
import { CELLS_PER_UNIT as S, BOARD_W, BOARD_H, levelInfo } from './config.js';
import { FIELD, toCell } from './grid.js';
import { Rng, eventRng } from './rng.js';

export const POWER = Object.freeze({
  kinds: ['freeze', 'shield', 'slow'],
  spawn: [12, 20],           // seconds between one pickup appearing and the next
  lifetime: 10,              // seconds a pickup waits
  freeze: 3,
  shield: 5,
  slow: 5,
  slowScale: 0.5,
  radius: 1.8,               // units: a route cell this close to a pickup takes it
  keepAway: { patrol: 12, wall: 3, tracer: 8 },     // units: where a pickup may appear
  retry: 2,                  // seconds before trying again when nowhere suitable was found
});

const TRIES = 80;

export class Powerups {
  constructor(game) {
    this.game = game;
    this._clear();
  }

  _clear() {
    this.enabled = false;
    this.pickup = null;              // { kind, x, y, expires } on the board
    this.until = {};                 // kind -> game-clock time its effect ends
    this.nextAt = Infinity;
    this.kind = null;                // the kind waiting to appear (drawn when the previous one appeared)
    this.draws = { seq: 0, pos: 0 }; // how many values each stream has given, so a restore can catch up
    this._seq = null;
    this._pos = null;
  }

  /* A new level. Only levels from 3 have power-ups. */
  reset(level, seed) {
    this._clear();
    this.enabled = levelInfo(level.number).powerups;
    if (!this.enabled) return;
    this._seq = eventRng(seed, level.number);
    this._pos = new Rng(`${seed}|events|${level.number}|where`);
    this.nextAt = this.game.clock.now + this._draw('range', POWER.spawn[0], POWER.spawn[1]);
    this.kind = this._draw('pick', POWER.kinds);
  }

  _draw(how, a, b) {
    this.draws.seq++;
    return how === 'pick' ? this._seq.pick(a) : this._seq.range(a, b);
  }

  get now() { return this.game.clock.now; }
  active(kind) { return (this.until[kind] || 0) > this.now; }
  get shielded() { return this.active('shield'); }
  remaining(kind) { return Math.max(0, (this.until[kind] || 0) - this.now); }

  /* How fast patrols and tracers should move right now (0 = stopped). */
  scale() {
    if (this.active('freeze')) return { patrols: 0, tracers: 0 };
    return { patrols: this.active('slow') ? POWER.slowScale : 1, tracers: 1 };
  }

  /* --- per physics step ----------------------------------------------------------------------- */

  update() {
    if (!this.enabled) return;
    const now = this.now;
    for (const kind of POWER.kinds) {
      if (this.until[kind] && this.until[kind] <= now) {
        delete this.until[kind];
        this.game.emit('power', { type: 'end', kind });
      }
    }
    if (this.pickup && this.pickup.expires <= now) {
      this.game.emit('power', { type: 'expire', kind: this.pickup.kind, x: this.pickup.x, y: this.pickup.y });
      this.pickup = null;
    }
    if (!this.pickup && now >= this.nextAt) this._spawn();
  }

  _spawn() {
    const spot = this._findSpot();
    if (!spot) { this.nextAt = this.now + POWER.retry; return; }
    const kind = this.kind;
    this.pickup = { kind, x: spot.x, y: spot.y, expires: this.now + POWER.lifetime };
    this.nextAt = this.now + this._draw('range', POWER.spawn[0], POWER.spawn[1]);
    this.kind = this._draw('pick', POWER.kinds);
    this.game.emit('power', { type: 'spawn', kind, x: spot.x, y: spot.y });
  }

  /* Open ground, clear of walls, and well away from every patrol and tracer. */
  _findSpot() {
    const { game } = this;
    const { grid, level } = game;
    const { patrol, wall, tracer } = POWER.keepAway;
    for (let i = 0; i < TRIES; i++) {
      this.draws.pos += 2;
      const x = 4 + this._pos.float() * (BOARD_W - 8), y = 4 + this._pos.float() * (BOARD_H - 8);
      if (grid.get(toCell(x), toCell(y)) !== FIELD || grid.circleHitsSolid(x, y, wall)) continue;
      if (level.patrols.some((p) => Math.hypot(p.x - x, p.y - y) < patrol)) continue;
      if (game.tracers.list.some((t) => Math.hypot(t.x - x, t.y - y) < tracer)) continue;
      return { x, y };
    }
    return null;
  }

  /* --- collecting ------------------------------------------------------------------------------- */

  /* The route just laid cell (cx, cy): if it is close to the pickup, that takes it. */
  touch(cx, cy) {
    const p = this.pickup;
    if (!p) return;
    const dx = (cx + 0.5) / S - p.x, dy = (cy + 0.5) / S - p.y;
    if (dx * dx + dy * dy <= POWER.radius * POWER.radius) this._collect();
  }

  /* A capture just claimed ground: if that swallowed the pickup, it is collected too. */
  afterCapture() {
    const p = this.pickup;
    if (p && this.game.grid.get(toCell(p.x), toCell(p.y)) !== FIELD) this._collect();
  }

  _collect() {
    const { kind, x, y } = this.pickup;
    this.pickup = null;
    this.until[kind] = this.now + POWER[kind];                 // collecting the same kind again refreshes it, it does not stack
    this.game.emit('power', { type: 'start', kind, x, y, seconds: POWER[kind] });
  }

  /* --- saving ------------------------------------------------------------------------------------ */

  /* Times are saved as time left. (now + d) - now can come out a few femtoseconds over d, and a capture saves in the
     very step it collects a pickup, so the value is held to its range: the check on the way back in is exact. */
  toJSON() {
    const now = this.now;
    const left = (at, max) => Math.min(max, Math.max(0, at - now));
    const active = {};
    for (const kind of POWER.kinds) if (this.active(kind)) active[kind] = left(this.until[kind], POWER[kind]);
    return {
      pickup: this.pickup ? { kind: this.pickup.kind, x: this.pickup.x, y: this.pickup.y, left: left(this.pickup.expires, POWER.lifetime) } : null,
      nextIn: Number.isFinite(this.nextAt) ? Math.max(0, this.nextAt - now) : -1,
      kind: this.kind, active, draws: { ...this.draws },
    };
  }

  /* Put it all back. The streams are recreated and advanced by how many values they had given. */
  restore(level, seed, data) {
    this.reset(level, seed);
    if (!this.enabled || !data) return;
    const now = this.now;
    this._seq = eventRng(seed, level.number);
    this._pos = new Rng(`${seed}|events|${level.number}|where`);
    for (let i = 0; i < data.draws.seq; i++) this._seq.float();
    for (let i = 0; i < data.draws.pos; i++) this._pos.float();
    this.draws = { seq: data.draws.seq, pos: data.draws.pos };
    this.kind = data.kind;
    this.nextAt = data.nextIn >= 0 ? now + data.nextIn : Infinity;
    this.pickup = data.pickup ? { kind: data.pickup.kind, x: data.pickup.x, y: data.pickup.y, expires: now + data.pickup.left } : null;
    this.until = {};
    for (const [kind, left] of Object.entries(data.active)) this.until[kind] = now + left;
  }

  /* For tests: put a pickup on the board now. */
  place(kind, x, y) { this.pickup = { kind, x, y, expires: this.now + POWER.lifetime }; }
}
