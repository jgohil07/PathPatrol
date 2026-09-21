/* Drawing. Two layers:

   - a static layer (field colour, texture, claimed territory, obstacles), rebuilt only when a level
     starts, ground is claimed, the theme changes or the canvas is resized;
   - a per-frame layer (patrols, trails, flash) drawn on top of a single drawImage of the static one.

   All drawing is in board units; view.applyTransform() maps them to device pixels, rotation included. */
import { BOARD_W, BOARD_H, GRID_W, GRID_H } from './config.js';
import { FIELD, WALL, BORDER } from './grid.js';
import { TRAIL_LENGTH } from './physics.js';
import { GLYPHS } from './glyphs.js';
import { POWER } from './powerups.js';
import { EXTRA } from './egg.js';

const PALETTES = {
  flight: [
    ['#147a79', '#20a998', '#75f0cd'], ['#174f90', '#287bd0', '#7bc5ff'], ['#742e75', '#b24aa4', '#ffb5e9'],
    ['#865126', '#d88435', '#ffd681'], ['#784234', '#bd584b', '#ffad8c'], ['#315c48', '#52a173', '#b9f1bd'],
  ],
  drive: [
    ['#526d62', '#7f9c7d', '#d9d88d'], ['#546979', '#8299a1', '#d8c799'], ['#735d67', '#a67e80', '#e0bc91'],
    ['#6d604e', '#9d895a', '#e3c978'], ['#4e6471', '#71969a', '#cad6a1'], ['#625967', '#927b91', '#e2c4ba'],
  ],
};
export const paletteFor = (theme, level) => {
  const list = PALETTES[theme] || PALETTES.flight;
  return list[(level - 1) % list.length];
};

/* Radius of the ring around the pointer, in CSS px. A fingertip covers roughly 10-16 mm, which is 60-100
   CSS px across on a phone, so the finger ring has to be large to stay visible around it. Tune on a
   real device; the mouse ring only needs to be findable. */
const TIP_RING_PX = { coarse: 34, fine: 13 };

const GLYPH_PATHS = Object.fromEntries(Object.entries(GLYPHS).map(([kind, d]) => [kind, new Path2D(d)]));

const INK = [11, 20, 34];                 // #0b1422: claimed ground and the frame
const DOT = [22, 40, 58];                 // a faint dot-matrix on claimed ground, every 4 units
const GLOW = [114, 244, 209];             // the aqua rim on open ground next to a wall: strong at one cell, fading at two

export class Renderer {
  constructor({ canvas, view, game, storage }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.view = view;
    this.game = game;
    this.theme = storage.settings.theme;
    this.sprites = { flight: new Image(), drive: new Image() };
    this.sprites.flight.src = 'assets/sprites/plane.svg';
    this.sprites.drive.src = 'assets/sprites/car.svg';

    this.layer = document.createElement('canvas');           // the static layer
    this.layerCtx = this.layer.getContext('2d', { alpha: false });
    this.territory = document.createElement('canvas');       // one pixel per grid cell
    this.territory.width = GRID_W;
    this.territory.height = GRID_H;
    this.territoryCtx = this.territory.getContext('2d');
    this.territoryImage = this.territoryCtx.createImageData(GRID_W, GRID_H);

    this.staticDirty = true;
    this.dirty = true;
    this.frames = 0;                                          // for tests: draws actually performed
    this.reducedMotion = false;                               // stops the dashes on a live route from running
    this.ghost = null;                                        // where the tutorial's ghost finger was drawn this frame (for tests)
    this.fx = null;                                           // particles, popups and shake (set by main.js)
    this.pickupDrawn = null;                                  // the power-up drawn this frame, if any (for tests)
    this.flashAlpha = 0;                                      // the red "life lost" tint drawn this frame (for tests)
    this._shake = { x: 0, y: 0 };

    game.on('level', () => this.invalidateStatic());
    game.on('capture', () => this.invalidateStatic());
    game.on('phase', () => this.invalidate());
  }

  invalidate() { this.dirty = true; }
  invalidateStatic() { this.staticDirty = true; this.dirty = true; }
  resize() { this.invalidateStatic(); }
  setTheme(theme) { this.theme = theme; this.invalidateStatic(); }
  setReducedMotion(on) {
    this.reducedMotion = !!on;
    if (this.fx) { this.fx.reducedMotion = !!on; if (on) this.fx.clear(); }
  }

  /* alpha: how far between the last two physics steps this frame falls (0..1). */
  draw(alpha = 1) {
    const { view, game, ctx, fx } = this;
    if (!view.fit || !game.level) return;
    const now = performance.now();
    if (fx) fx.update(now);
    if (this.staticDirty) this._buildStatic();
    const shake = fx ? fx.shakeOffset(now, view.fit.ratio, this._shake) : this._shake;      // device pixels; 0, 0 when still
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (shake.x !== 0 || shake.y !== 0) {                                                       // a shaken board leaves a sliver: fill it with the frame's colour
      ctx.fillStyle = '#0b1422';
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    ctx.drawImage(this.layer, shake.x, shake.y);
    ctx.save();
    view.applyTransform(ctx, shake.x, shake.y);
    this._drawLiveRoute();
    this._drawGhost();
    this._drawPickup(now);
    this._drawPatrols(alpha);
    this._drawTracers(alpha, now);
    if (game.powerups.active('freeze')) {                                                        // everything is still: a faint ice-blue cast
      ctx.fillStyle = 'rgba(160,225,255,0.07)';
      ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    }
    if (fx) fx.drawBoard(ctx, now, view.fit.scale);
    // The red tint for a lost life. With reduced motion it is a faint steady tint, not a flash.
    this.flashAlpha = game.flash > 0 ? Math.min(game.flash * 0.5, this.reducedMotion ? 0.12 : 0.5) : 0;
    if (this.flashAlpha > 0) {
      ctx.fillStyle = `rgba(255,92,77,${this.flashAlpha})`;
      ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    }
    ctx.restore();
    if (fx) fx.drawPopups(ctx, now, view.fit.ratio, shake.x, shake.y);
    this.dirty = false;
    this.frames++;
  }

  /* --- static layer ----------------------------------------------------------------------- */

  _buildStatic() {
    const { layer, layerCtx: ctx, view, game } = this;
    const { pxW, pxH } = view.fit;
    if (layer.width !== pxW) layer.width = pxW;
    if (layer.height !== pxH) layer.height = pxH;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#0b1422';
    ctx.fillRect(0, 0, pxW, pxH);
    ctx.save();
    view.applyTransform(ctx);
    const look = this._look();
    ctx.fillStyle = look ? look.field : paletteFor(this.theme, game.level.number)[0];
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    const shade = ctx.createLinearGradient(0, 0, BOARD_W, BOARD_H);
    shade.addColorStop(0, 'rgba(255,255,255,.08)');
    shade.addColorStop(0.55, 'rgba(255,255,255,0)');
    shade.addColorStop(1, 'rgba(0,0,0,.17)');
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    this._drawTexture(ctx);
    this._paintTerritory();
    ctx.imageSmoothingEnabled = false;                       // crisp cells: the pixel look is deliberate
    ctx.drawImage(this.territory, 0, 0, BOARD_W, BOARD_H);
    ctx.imageSmoothingEnabled = true;
    for (const points of game.level.routes) this._strokeRoute(ctx, points, null, false);
    for (const obstacle of game.level.obstacles) {
      if (this.theme === 'flight') drawMountain(ctx, obstacle); else drawCityBlock(ctx, obstacle);
    }
    ctx.restore();
    this.staticDirty = false;
  }

  /* The extra board has colours of its own; every other level takes its palette from the theme. */
  _look() {
    const { run } = this.game;
    return run && run.mode === 'extra' ? EXTRA.look : null;
  }

  /* Claimed ground and the frame in ink, with a dot-matrix on the claimed part; open ground next to a wall
     gets a two-cell rim, strong at the wall and fading out. */
  _paintTerritory() {
    const { cells, w, h } = this.game.grid;
    const look = this._look();
    const ink = look ? look.ink : INK, dots = look ? look.dot : DOT, glow = look ? look.glow : GLOW;
    const px = this.territoryImage.data;
    const solid = (v) => v === WALL || v === BORDER;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x, o = i * 4, v = cells[i];
        if (solid(v)) {
          const dot = v === WALL && (x & 7) === 4 && (y & 7) === 4;
          const c = dot ? dots : ink;
          px[o] = c[0]; px[o + 1] = c[1]; px[o + 2] = c[2]; px[o + 3] = 255;
        } else if (v === FIELD) {
          let alpha = 0;
          if ((x > 0 && solid(cells[i - 1])) || (x < w - 1 && solid(cells[i + 1])) || (y > 0 && solid(cells[i - w])) || (y < h - 1 && solid(cells[i + w]))) alpha = 66;
          else if ((x > 1 && solid(cells[i - 2])) || (x < w - 2 && solid(cells[i + 2])) || (y > 1 && solid(cells[i - 2 * w])) || (y < h - 2 && solid(cells[i + 2 * w]))) alpha = 26;
          px[o] = glow[0]; px[o + 1] = glow[1]; px[o + 2] = glow[2]; px[o + 3] = alpha;
        } else {
          px[o + 3] = 0;
        }
      }
    }
    this.territoryCtx.putImageData(this.territoryImage, 0, 0);
  }

  _drawTexture(ctx) {
    ctx.save();
    if (this.theme === 'flight') {
      ctx.fillStyle = 'rgba(230,255,247,.08)';
      for (let i = 0; i < 7; i++) {
        const x = (i * 23 + 9) % 112 + 3, y = (i * 17 + 11) % 64 + 3;
        ctx.fillRect(x, y, 7, 0.38);
        ctx.fillRect(x + 1.4, y - 0.4, 3.6, 0.35);
      }
    } else {
      ctx.strokeStyle = 'rgba(246,230,180,.075)';
      ctx.lineWidth = 0.12;
      for (let x = 8; x < BOARD_W; x += 12) { ctx.beginPath(); ctx.moveTo(x, 2); ctx.lineTo(x, BOARD_H - 2); ctx.stroke(); }
      for (let y = 8; y < BOARD_H; y += 12) { ctx.beginPath(); ctx.moveTo(2, y); ctx.lineTo(BOARD_W - 2, y); ctx.stroke(); }
    }
    ctx.restore();
  }

  /* --- routes ------------------------------------------------------------------------------ */

  /* A route as a runway (Flight) or a road (Drive): a dark bed, a lighter surface and a dashed centre
     line. `points` is a flat [x, y, ...] polyline; `tip` an optional final point [x, y]. `live` animates
     the dashes. The polyline is drawn exactly, not smoothed: the wall is made of the cells along these
     same segments, and a smoothed road would cut corners the wall does not. */
  _strokeRoute(ctx, points, tip, live) {
    const n = points.length / 2;
    if (n === 0 || (n === 1 && !tip)) return;
    ctx.beginPath();
    ctx.moveTo(points[0], points[1]);
    for (let i = 1; i < n; i++) ctx.lineTo(points[i * 2], points[i * 2 + 1]);
    if (tip) ctx.lineTo(tip[0], tip[1]);
    const flight = this.theme === 'flight';
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 1.55; ctx.strokeStyle = flight ? '#2b3a46' : '#27303a'; ctx.stroke();
    ctx.lineWidth = 1.02; ctx.strokeStyle = flight ? '#687c82' : '#4d5962'; ctx.stroke();
    ctx.setLineDash([1.25, 1.1]);
    ctx.lineDashOffset = live && !this.reducedMotion ? -performance.now() / 55 : 0;
    ctx.lineWidth = 0.15; ctx.strokeStyle = flight ? '#e9fff7' : '#ffd36e'; ctx.stroke();
    ctx.restore();
  }

  /* The route being drawn, and a ring around the pointer that stays visible around a fingertip. */
  _drawLiveRoute() {
    const { ctx, game, view } = this;
    const route = game.route;
    if (!route.down) return;
    const drawing = route.mode === 'drawing';
    if (drawing && game.powerups.shielded) this._shieldGlow(route);
    if (drawing) this._strokeRoute(ctx, route.points, [route.tip.x, route.tip.y], true);
    if (!drawing && route.mode !== 'armed') return;
    const scale = view.fit.scale;                              // CSS px per world unit
    const flight = this.theme === 'flight';
    ctx.save();
    ctx.lineWidth = 2.2 / scale;
    ctx.strokeStyle = flight ? '#c4fff0' : '#ffe0a1';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.globalAlpha = drawing ? 0.95 : 0.5;
    ctx.beginPath();
    ctx.arc(route.tip.x, route.tip.y, (route.coarse ? TIP_RING_PX.coarse : TIP_RING_PX.fine) / scale, 0, Math.PI * 2);
    ctx.stroke();
    if (drawing) {
      ctx.beginPath();
      ctx.arc(route.tip.x, route.tip.y, 3 / scale, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  /* The tutorial's ghost finger: a translucent fingertip ring sweeping the gesture to make, with the path it has
     covered. It is drawn in board units, so it is right on the rotated portrait board too. With reduced motion it
     does not sweep: it stays at the end of the gesture with the whole path shown. */
  _drawGhost() {
    const { ctx, game, view } = this;
    this.ghost = null;
    if (!game.tutorial.active || game.phase !== 'playing') return;
    const g = game.tutorial.ghostAt(performance.now());
    const y = this.reducedMotion ? g.toY : g.y;
    const pulse = this.reducedMotion ? 0.5 : g.pulse;
    this.ghost = { x: g.x, y };
    const scale = view.fit.scale;                              // CSS px per board unit
    const colour = this.theme === 'flight' ? '196,255,240' : '255,224,161';
    ctx.save();
    if (g.moving || this.reducedMotion) {
      ctx.setLineDash([6 / scale, 5 / scale]);
      ctx.lineWidth = 3 / scale;
      ctx.lineCap = 'round';
      ctx.strokeStyle = `rgba(${colour},0.55)`;
      ctx.beginPath();
      ctx.moveTo(g.x, g.fromY);
      ctx.lineTo(g.x, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    const ring = (TIP_RING_PX.coarse * (0.8 + 0.3 * pulse)) / scale;      // a fingertip-sized ring, like the real one
    ctx.lineWidth = 2.4 / scale;
    ctx.strokeStyle = `rgba(${colour},0.9)`;
    ctx.fillStyle = `rgba(${colour},${0.22 + 0.18 * pulse})`;
    ctx.beginPath();
    ctx.arc(g.x, y, ring, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(g.x, y, 3.5 / scale, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${colour},0.95)`;
    ctx.fill();
    ctx.restore();
  }

  /* The shield power-up: an aqua glow around the route being drawn, because patrols bounce off it. */
  _shieldGlow(route) {
    const { ctx } = this;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3.4;
    ctx.strokeStyle = 'rgba(114,244,209,0.32)';
    ctx.beginPath();
    ctx.moveTo(route.points[0], route.points[1]);
    for (let i = 2; i < route.points.length; i += 2) ctx.lineTo(route.points[i], route.points[i + 1]);
    ctx.lineTo(route.tip.x, route.tip.y);
    ctx.stroke();
    ctx.restore();
  }

  /* The pickup waiting on the board: a dark badge with its glyph and a ring that drains as it runs out. */
  _drawPickup(now) {
    const { ctx, game, view } = this;
    const p = game.powerups.pickup;
    this.pickupDrawn = null;
    if (!p) return;
    this.pickupDrawn = { x: p.x, y: p.y, kind: p.kind };
    const left = Math.max(0, Math.min(1, (p.expires - game.clock.now) / POWER.lifetime));
    const r = 2.1 * (this.reducedMotion ? 1 : 1 + 0.1 * Math.sin(now / 240));
    ctx.save();
    ctx.translate(p.x, p.y);
    if (view.fit.rotated) ctx.rotate(-Math.PI / 2);                 // the portrait board is turned a quarter: turn the badge back so its glyph reads upright
    ctx.fillStyle = 'rgba(4,8,14,0.82)';
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,179,106,0.28)';
    ctx.lineWidth = 0.3;
    ctx.stroke();
    ctx.strokeStyle = '#ffb36a';
    ctx.lineWidth = 0.34;
    ctx.beginPath();
    ctx.arc(0, 0, r, -Math.PI / 2, -Math.PI / 2 + left * Math.PI * 2);
    ctx.stroke();
    const k = (r * 0.62) / 12;                                      // the glyph is drawn on a 24-unit grid
    ctx.scale(k, k);
    ctx.translate(-12, -12);
    ctx.strokeStyle = '#f4fbf8';
    ctx.lineWidth = 1.8;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke(GLYPH_PATHS[p.kind]);
    ctx.restore();
  }

  /* Edge tracers: a pulsing amber diamond with a short fading trail; coral and quicker while chasing a route. */
  _drawTracers(alpha, now) {
    const { ctx, game } = this;
    this.tracersDrawn = game.tracers.list.length;
    for (const tracer of game.tracers.list) {
      const chasing = tracer.mode === 'chase';
      const colour = chasing ? '#ff765f' : '#ffb36a';
      ctx.fillStyle = colour;
      for (let k = 0; k < tracer.trailLen; k++) {                         // newest first
        const j = (tracer.trailHead - 1 - k + tracer.trail.length / 2) % (tracer.trail.length / 2);
        ctx.globalAlpha = ((tracer.trailLen - k) / tracer.trailLen) * 0.22;
        ctx.fillRect(tracer.trail[j * 2] - 0.25, tracer.trail[j * 2 + 1] - 0.25, 0.5, 0.5);
      }
      ctx.globalAlpha = 1;
      const pulse = this.reducedMotion ? 1 : 1 + 0.14 * Math.sin(now / (chasing ? 90 : 220));
      const size = 0.95 * pulse;
      ctx.save();
      ctx.translate(tracer.px + (tracer.x - tracer.px) * alpha, tracer.py + (tracer.y - tracer.py) * alpha);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = 'rgba(4,8,14,0.85)';
      ctx.fillRect(-size - 0.22, -size - 0.22, 2 * size + 0.44, 2 * size + 0.44);       // a dark outline so it reads on any floor
      ctx.fillStyle = colour;
      ctx.fillRect(-size, -size, 2 * size, 2 * size);
      ctx.restore();
    }
  }

  /* --- per-frame layer -------------------------------------------------------------------- */

  _drawPatrols(alpha) {
    const { ctx, theme } = this;
    const sprite = this.sprites[theme];
    const ready = sprite.complete && sprite.naturalWidth > 0;
    const k = this.view.fit.k;                               // device px per unit: canvas shadows are in device px
    for (const p of this.game.level.patrols) {
      ctx.fillStyle = theme === 'flight' ? '#bef7e7' : '#ffca6c';
      for (let n = 0; n < p.trailLen; n++) {                 // newest first
        const j = (p.trailHead - 1 - n + TRAIL_LENGTH) % TRAIL_LENGTH;
        ctx.globalAlpha = ((p.trailLen - n) / p.trailLen) * 0.17;
        ctx.fillRect(p.trail[j * 2] - 0.2, p.trail[j * 2 + 1] - 0.2, 0.4, 0.4);
      }
      ctx.globalAlpha = 1;
      ctx.save();
      ctx.translate(p.px + (p.x - p.px) * alpha, p.py + (p.y - p.py) * alpha);
      ctx.rotate(p.heading);                                 // eased, so a bounce turns the sprite instead of snapping it
      // A soft shadow offset towards the bottom right (light from the top left, whatever the board's
      // rotation): far below a plane, tight against a car.
      ctx.shadowColor = 'rgba(2,12,22,0.34)';
      ctx.shadowBlur = (theme === 'flight' ? 0.7 : 0.35) * k;
      ctx.shadowOffsetX = (theme === 'flight' ? 0.95 : 0.3) * k;
      ctx.shadowOffsetY = (theme === 'flight' ? 1.35 : 0.4) * k;
      if (ready) {
        ctx.drawImage(sprite, -2.25, -1.68, 4.5, 3.36);
      } else {                                               // until the sprite has loaded
        ctx.fillStyle = theme === 'flight' ? '#ff8d63' : '#5bd6e2';
        ctx.fillRect(-1.55, -0.48, 3.1, 0.96);
        ctx.fillRect(-0.25, -1.05, 0.7, 2.1);
      }
      ctx.restore();
    }
  }
}

/* --- obstacle art, carried over from the prototype ------------------------------------------ */

function drawMountain(ctx, { x, y, w, h }) {
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.fillStyle = '#102232'; ctx.fillRect(x, y, w, h);
  const peakA = x + Math.max(1.3, w * 0.28), peakB = x + Math.min(w - 1.3, w * 0.7);
  ctx.fillStyle = '#315263';
  ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(peakA, y + 0.55); ctx.lineTo(x + w * 0.58, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#234252';
  ctx.beginPath(); ctx.moveTo(x + w * 0.25, y + h); ctx.lineTo(peakB, y + h * 0.12); ctx.lineTo(x + w, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#a9d5cc';
  ctx.fillRect(peakA - 0.48, y + 0.62, 0.96, 0.24);
  ctx.fillRect(peakA - 0.23, y + 0.86, 0.46, 0.28);
  ctx.fillRect(peakB - 0.43, y + h * 0.14, 0.86, 0.22);
  ctx.fillStyle = 'rgba(184,247,219,.38)';
  for (let xx = x + 0.7; xx < x + w - 0.5; xx += 1.35) ctx.fillRect(xx, y + h - 0.65, 0.35, 0.16);
  ctx.restore();
}

function drawCityBlock(ctx, { x, y, w, h }) {
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.fillStyle = '#152233'; ctx.fillRect(x, y, w, h);
  const widths = [Math.max(1.4, w * 0.29), Math.max(1.5, w * 0.34), Math.max(1.25, w * 0.22)];
  let cursor = x + 0.35;
  widths.forEach((width, i) => {
    const top = y + (i === 1 ? 0.35 : 1.15);
    ctx.fillStyle = i === 1 ? '#304154' : '#26384b';
    ctx.fillRect(cursor, top, width, y + h - top);
    ctx.fillStyle = '#e7c86d';
    for (let wy = top + 0.6; wy < y + h - 0.35; wy += 0.78) {
      for (let wx = cursor + 0.35; wx < cursor + width - 0.18; wx += 0.65) {
        if ((Math.floor(wx * 5 + wy * 3) % 3) !== 0) ctx.fillRect(wx, wy, 0.17, 0.24);
      }
    }
    cursor += width + 0.22;
  });
  ctx.fillStyle = '#0d1725'; ctx.fillRect(x, y + h - 0.42, w, 0.42);
  ctx.restore();
}
