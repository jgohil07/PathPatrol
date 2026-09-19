/* Effects: particles, score popups, rings, a glow along a closed route, and a screen shake.

   Everything is pooled and capped, so a burst of captures can never grow memory or slow a frame, and nothing here
   allocates in the drawing loop. Effects use real time (performance.now), not the game clock: they are decoration, they
   never affect play, and they finish by themselves.

   Reduced motion: no particles, rings, glow or shake. Popups still appear (they carry the points) but hold still and
   just fade. The renderer also tones the red hit flash down.

   Board-space effects are drawn under the board transform, so they are right on the rotated portrait board. Popups
   are text and must stay upright, so they are placed with view.toCanvas and drawn in screen space. */

const SHAKE_MS = 320;
const BOARD_CENTRE = { x: 60, y: 36 };
const MAX_PARTICLES = 240;
const MAX_POPUPS = 8;
const MAX_RINGS = 6;
const MAX_GLOWS = 3;

const ease = (t) => 1 - (1 - t) ** 3;
const number = (n) => Math.round(n).toLocaleString('en-US');

const TINT = { aqua: '#72f4d1', white: '#e8f1ee', coral: '#ff765f', amber: '#ffb36a' };

export class Fx {
  constructor({ game, view }) {
    this.game = game;
    this.view = view;
    this.reducedMotion = false;
    this.last = performance.now();
    this._seed = 20260919;
    // Particles: parallel arrays, swap-removed. Positions are board units.
    this.n = 0;
    this.x = new Float32Array(MAX_PARTICLES);
    this.y = new Float32Array(MAX_PARTICLES);
    this.vx = new Float32Array(MAX_PARTICLES);
    this.vy = new Float32Array(MAX_PARTICLES);
    this.age = new Float32Array(MAX_PARTICLES);
    this.life = new Float32Array(MAX_PARTICLES);
    this.size = new Float32Array(MAX_PARTICLES);
    this.tint = new Array(MAX_PARTICLES).fill('aqua');
    this.popups = [];
    this.rings = [];
    this.glows = [];
    this.shakeAt = -Infinity;
    this.shakeAmp = 0;
    this.shown = [];                       // where popups were drawn last frame, in device pixels (for tests)

    game.on('capture', (result) => this._onCapture(result));
    game.on('route', (event) => this._onRoute(event));
    game.on('extraLife', () => this.popup('+1 LIFE', BOARD_CENTRE.x, 14, 'amber'));
    game.on('clear', (tally) => this._onClear(tally));
    game.on('level', () => this.clear());
  }

  _random() { this._seed = (Math.imul(this._seed, 1664525) + 1013904223) >>> 0; return this._seed / 4294967296; }

  clear() {
    this.n = 0;
    this.popups.length = 0;
    this.rings.length = 0;
    this.glows.length = 0;
    this.shakeAt = -Infinity;
  }

  /* Anything still alive: the renderer keeps drawing while this is true, even on a paused or finished screen. */
  get active() {
    return this.n > 0 || this.popups.length > 0 || this.rings.length > 0 || this.glows.length > 0 || performance.now() - this.shakeAt < SHAKE_MS;
  }

  stats() { return { particles: this.n, popups: this.popups.length, rings: this.rings.length, glows: this.glows.length, shaking: performance.now() - this.shakeAt < SHAKE_MS }; }

  /* --- spawning --------------------------------------------------------------------------------- */

  burst(x, y, count, tint, { speed = 10, spread = 1, life = 0.7, size = 0.55 } = {}) {
    if (this.reducedMotion) return;
    for (let i = 0; i < count && this.n < MAX_PARTICLES; i++) {
      const k = this.n++;
      const angle = this._random() * Math.PI * 2;
      const v = speed * (0.35 + this._random() * 0.65);
      this.x[k] = x + (this._random() - 0.5) * spread;
      this.y[k] = y + (this._random() - 0.5) * spread;
      this.vx[k] = Math.cos(angle) * v;
      this.vy[k] = Math.sin(angle) * v;
      this.age[k] = 0;
      this.life[k] = life * (0.6 + this._random() * 0.6);
      this.size[k] = size * (0.6 + this._random() * 0.8);
      this.tint[k] = tint;
    }
  }

  ring(x, y, tint, { from = 1.5, to = 6, ms = 420 } = {}) {
    if (this.reducedMotion) return;
    if (this.rings.length >= MAX_RINGS) this.rings.shift();
    this.rings.push({ x, y, tint, from, to, ms, born: performance.now() });
  }

  popup(text, x, y, tint = 'aqua') {
    if (this.popups.length >= MAX_POPUPS) this.popups.shift();
    this.popups.push({ text, x, y, tint, born: performance.now(), ms: this.reducedMotion ? 900 : 1150 });
  }

  glow(route) {
    if (this.reducedMotion || !route || route.length < 4) return;
    if (this.glows.length >= MAX_GLOWS) this.glows.shift();
    this.glows.push({ route, born: performance.now(), ms: 200 });
  }

  shake(amp = 5) {
    if (this.reducedMotion) return;
    this.shakeAt = performance.now();
    this.shakeAmp = amp;
  }

  /* --- reacting to the game --------------------------------------------------------------------- */

  _onCapture(result) {
    const route = result.route;
    this.glow(route);
    if (route && route.length >= 4) {
      const count = Math.min(60, Math.round(10 + result.gained * 1.4));
      const spots = Math.min(count, route.length / 2);
      for (let i = 0; i < spots; i++) {                                      // along the route, evenly
        const at = Math.floor((i / spots) * (route.length / 2 - 1)) * 2;
        this.burst(route[at], route[at + 1], Math.ceil(count / spots), i % 3 === 0 ? 'white' : 'aqua', { speed: 8, spread: 0.6, life: 0.65 });
      }
    }
    if (result.points > 0) {                                                 // the tutorial's practice captures score nothing
      const middle = route && route.length >= 4 ? [route[(route.length / 4 | 0) * 2], route[(route.length / 4 | 0) * 2 + 1]] : [BOARD_CENTRE.x, BOARD_CENTRE.y];
      this.popup(`+${number(result.points)}${result.combo > 1 ? `  x${result.combo.toFixed(2)}` : ''}`, middle[0], middle[1], 'aqua');
    }
  }

  _onRoute(event) {
    const { game } = this;
    if (event.type === 'hit') {
      const tip = game.route.tip;
      this.burst(tip.x, tip.y, 28, 'coral', { speed: 16, life: 0.55 });
      this.ring(tip.x, tip.y, 'coral', { from: 1.2, to: 5, ms: 360 });
      this.shake(5);
    } else if (event.type === 'closecall') {
      const p = game.level.patrols[event.patrol];
      if (p) { this.ring(p.x, p.y, 'amber', { from: 1.8, to: 6.5, ms: 460 }); this.popup('CLOSE', p.x, p.y - 2.5, 'amber'); }
    }
  }

  _onClear() { for (let i = 0; i < 4; i++) this.burst(15 + i * 30, 36, 22, i % 2 ? 'amber' : 'aqua', { speed: 14, spread: 20, life: 1, size: 0.5 }); }

  /* --- per frame ------------------------------------------------------------------------------------ */

  update(now) {
    const dt = Math.min(0.05, Math.max(0, (now - this.last) / 1000));
    this.last = now;
    for (let i = 0; i < this.n; i++) {
      this.age[i] += dt;
      if (this.age[i] >= this.life[i]) {                                     // swap-remove: the last one takes this slot
        const last = --this.n;
        this.x[i] = this.x[last]; this.y[i] = this.y[last]; this.vx[i] = this.vx[last]; this.vy[i] = this.vy[last];
        this.age[i] = this.age[last]; this.life[i] = this.life[last]; this.size[i] = this.size[last]; this.tint[i] = this.tint[last];
        i--;
        continue;
      }
      this.x[i] += this.vx[i] * dt;
      this.y[i] += this.vy[i] * dt;
      const drag = 1 - 2.2 * dt;
      this.vx[i] *= drag;
      this.vy[i] *= drag;
    }
    this.popups = this.popups.filter((p) => now - p.born < p.ms);
    this.rings = this.rings.filter((r) => now - r.born < r.ms);
    this.glows = this.glows.filter((g) => now - g.born < g.ms);
  }

  /* The screen shake as a nudge in device pixels. */
  shakeOffset(now, ratio = 1, out = { x: 0, y: 0 }) {
    const t = (now - this.shakeAt) / SHAKE_MS;
    if (t < 0 || t >= 1) { out.x = out.y = 0; return out; }
    const amp = this.shakeAmp * ratio * (1 - t);
    out.x = Math.sin(t * 62) * amp;
    out.y = Math.cos(t * 79) * amp * 0.8;
    return out;
  }

  /* Board-space effects: call with the board transform applied. `scale` is CSS pixels per board unit. */
  drawBoard(ctx, now, scale) {
    for (const g of this.glows) {                                            // the closed route flashes and thins out
      const t = (now - g.born) / g.ms;
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = `rgba(170,255,235,${0.75 * (1 - t)})`;
      ctx.lineWidth = 1.8 + 2.2 * ease(t);                                  // a bright band that spreads and fades over ~200 ms
      ctx.beginPath();
      ctx.moveTo(g.route[0], g.route[1]);
      for (let i = 2; i < g.route.length; i += 2) ctx.lineTo(g.route[i], g.route[i + 1]);
      ctx.stroke();
      ctx.restore();
    }
    for (const r of this.rings) {
      const t = (now - r.born) / r.ms;
      ctx.strokeStyle = TINT[r.tint];
      ctx.globalAlpha = 0.9 * (1 - t);
      ctx.lineWidth = 2 / scale;
      ctx.beginPath();
      ctx.arc(r.x, r.y, r.from + (r.to - r.from) * ease(t), 0, Math.PI * 2);
      ctx.stroke();
    }
    for (const tint of ['aqua', 'white', 'coral', 'amber']) {                // one fill style at a time
      ctx.fillStyle = TINT[tint];
      for (let i = 0; i < this.n; i++) {
        if (this.tint[i] !== tint) continue;
        ctx.globalAlpha = 1 - this.age[i] / this.life[i];
        const s = this.size[i];
        ctx.fillRect(this.x[i] - s / 2, this.y[i] - s / 2, s, s);
      }
    }
    ctx.globalAlpha = 1;
  }

  /* Popups are text: drawn upright in screen space (identity transform), clamped inside the canvas. */
  drawPopups(ctx, now, ratio, dx = 0, dy = 0) {
    this.shown.length = 0;
    if (!this.popups.length) return;
    const { view } = this;
    const width = view.canvas.width, height = view.canvas.height;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    const px = Math.round(Math.max(18, Math.min(30, 2.6 * view.fit.scale)) * ratio);      // 18 px on a phone, ~23 px on a big desktop board
    ctx.font = `700 ${px}px "Space Grotesk", system-ui, sans-serif`;
    for (const p of this.popups) {
      const t = (now - p.born) / p.ms;
      const at = view.toCanvas(p.x, p.y);
      const half = ctx.measureText(p.text).width / 2 + 6 * ratio;
      const x = Math.max(half, Math.min(width - half, at.x)) + dx;
      const rise = this.reducedMotion ? 0 : ease(t) * 34 * ratio;             // floats up, unless motion is reduced
      const y = Math.max(px, Math.min(height - px, at.y - rise)) + dy;          // clamped after the rise, so it never floats off the canvas
      ctx.globalAlpha = t < 0.6 ? 1 : 1 - (t - 0.6) / 0.4;
      ctx.lineWidth = 4 * ratio;
      ctx.strokeStyle = 'rgba(4,8,14,0.85)';
      ctx.strokeText(p.text, x, y);
      ctx.fillStyle = TINT[p.tint];
      ctx.fillText(p.text, x, y);
      this.shown.push({ text: p.text, x, y, half, px });
    }
    ctx.restore();
  }
}

