/* Drawing. Three cached layers and a per-frame pass:

   - base: the open ground's art (water or farmland, baked by scenery.js), the light across the board, the time of day
     and a vignette. Rebuilt when a level starts, the theme changes or the canvas is resized.
   - territory: claimed ground (its pattern, a bevelled edge, the rim of light on the open ground beside it), the
     finished routes and the obstacles. Transparent over open ground. Rebuilt after a capture, and with the base.
   - each frame: the base, ripples and cloud shadows drifting over it, the territory, foam running along the shoreline,
     then the live route, pickups, patrols, tracers and effects.

   Ambient motion (ripples, foam, clouds) runs on game.age, simulated time, not the wall clock: a paused or frozen game is
   perfectly still, and reduced motion stops it altogether. The capture reveal and the level wipe are effects: they use
   real time, like fx.js, and finish by themselves.

   All drawing is in board units; view.applyTransform() maps them to device pixels, rotation included. */
import { BOARD_W, BOARD_H, GRID_W, GRID_H, CELLS_PER_UNIT as S, KINDS, PATROL_RADIUS } from './config.js';
import { steeringOf } from './steering.js';
import { FIELD, WALL, BORDER, walkCells } from './grid.js';
import { TRAIL_LENGTH } from './physics.js';
import { GLYPHS } from './glyphs.js';
import { POWER } from './powerups.js';
import { EXTRA } from './egg.js';
import { traceContours } from './contour.js';
import * as scenery from './scenery.js';

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
const DOT = [22, 40, 58];                 // the extra board keeps its dot-matrix on claimed ground, every 4 units
const GLOW = [114, 244, 209];             // the aqua rim on open ground next to a wall: strong at one cell, fading at two

/* Patrol sprites: their size on the board, and a soft shadow thrown towards the bottom right of the screen (light from
   the top left, whatever the board's rotation): far below a plane, tight against a car. */
const SPRITE_W = 4.5, SPRITE_H = 3.36;       // a standard patrol's sprite; other kinds are drawn in proportion to their radius
const SPRITE_FILES = {
  flight: { standard: 'plane.svg', scout: 'scout.svg', bomber: 'bomber.svg', hunter: 'hunter.svg', boss: 'boss.svg' },
  drive: { standard: 'car.svg', scout: 'scout-car.svg', bomber: 'bomber-car.svg', hunter: 'hunter-car.svg', boss: 'boss-car.svg' },
};
const HUNTER_TINT = '255,77,109';           // the hunter's crimson, for its wind-up ring and its chase
const SHADOW = { flight: { blur: 0.7, x: 0.95, y: 1.35 }, drive: { blur: 0.35, x: 0.3, y: 0.4 } };
const RIM = 0.16;                         // units: the pale rim round every sprite (see _sprite)
const RIM_COLOUR = 'rgba(236,250,246,0.78)';
const MAX_BANK = 0.85;                    // radians: how far a plane rolls into a turn (drawn as a squash across its body)

const REVEAL_MS = 360;                    // newly claimed ground floods outwards from the route over this long
const REVEAL_SOFT = 6;                    // cells: the soft leading edge of the flood
const WIPE_MS = 420;                      // the old board sweeps away when the next level starts

export class Renderer {
  constructor({ canvas, view, game, storage }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.view = view;
    this.game = game;
    this.theme = storage.settings.theme;
    // One sprite per theme and kind (the plain plane and car are the prototype's files, redrawn).
    this.sprites = {};
    for (const [theme, files] of Object.entries(SPRITE_FILES)) {
      this.sprites[theme] = {};
      for (const [kind, file] of Object.entries(files)) {
        const image = new Image();
        image.addEventListener('load', () => { this._spriteCache.clear(); this.invalidate(); });
        image.src = `assets/sprites/${file}`;
        this.sprites[theme][kind] = image;
      }
    }

    this.base = document.createElement('canvas');
    this.baseCtx = this.base.getContext('2d', { alpha: false });
    this.territory = document.createElement('canvas');
    this.territoryCtx = this.territory.getContext('2d');
    this.revealLayer = document.createElement('canvas');
    this.revealCtx = this.revealLayer.getContext('2d');
    this.wipe = document.createElement('canvas');
    this.wipeCtx = this.wipe.getContext('2d', { alpha: false });
    // Cell-resolution helpers: which cells are solid (the claimed ground's mask), the bevel and rim detail, and the
    // reveal's mask. One pixel per grid cell, scaled up when drawn.
    this.mask = cellCanvas();
    this.detail = cellCanvas();
    this.revealMask = cellCanvas();
    this.solid = new Uint8Array(GRID_W * GRID_H);             // the solid cells the territory layer was last painted from
    this.revealDist = new Uint16Array(GRID_W * GRID_H);
    this.revealCells = [];
    this.revealMax = 0;
    this.revealAt = -Infinity;
    this.wipeAt = -Infinity;

    this.baseDirty = true;
    this.territoryDirty = true;
    this.dirty = true;
    this.frames = 0;                                          // for tests: draws actually performed
    this.reducedMotion = false;                               // stops the ambient motion and the dashes on a live route
    this.ghost = null;                                        // where the tutorial's ghost finger was drawn this frame (for tests)
    this.fx = null;                                           // particles, popups and shake (set by main.js)
    this.pickupDrawn = null;                                  // the power-up drawn this frame, if any (for tests)
    this.flashAlpha = 0;                                      // the red "life lost" tint drawn this frame (for tests)
    this.revealing = false;                                   // a capture's flood is showing (for tests)
    this.steeringDrawn = {};                                  // hunters drawn this frame by steering state (for tests)
    this._shake = { x: 0, y: 0 };
    this._fieldKey = '';
    this._field = null;
    this._clouds = scenery.clouds();
    this._wavePattern = null;
    this._claimedPattern = null;
    this._foam = null;
    this._spriteCache = new Map();                            // `${theme}|${kind}` -> the sprite rasterised at the board's scale

    game.on('level', () => this._onLevel());
    game.on('capture', (result) => this._onCapture(result));
    game.on('phase', () => this.invalidate());
  }

  invalidate() { this.dirty = true; }
  invalidateStatic() { this.baseDirty = true; this.territoryDirty = true; this.dirty = true; }
  resize() { this._wavePattern = null; this._claimedPattern = null; this._spriteCache.clear(); this.invalidateStatic(); }
  setTheme(theme) { this.theme = theme; this._claimedPattern = null; this.invalidateStatic(); }
  setReducedMotion(on) {
    this.reducedMotion = !!on;
    if (on) { this.revealAt = -Infinity; this.wipeAt = -Infinity; }
    if (this.fx) { this.fx.reducedMotion = !!on; if (on) this.fx.clear(); }
    this.invalidate();
  }

  /* Seconds of ambient motion: simulated time, so it stands still whenever the game does. */
  get age() { return this.reducedMotion ? 0 : this.game.age; }

  /* alpha: how far between the last two physics steps this frame falls (0..1). */
  draw(alpha = 1) {
    const { view, game, ctx, fx } = this;
    if (!view.fit || !game.level) return;
    const now = performance.now();
    if (fx) fx.update(now);
    if (this.baseDirty) this._buildBase();
    if (this.territoryDirty) this._buildTerritory();
    const shake = fx ? fx.shakeOffset(now, view.fit.ratio, this._shake) : this._shake;      // device pixels; 0, 0 when still
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (shake.x !== 0 || shake.y !== 0) {                                                       // a shaken board leaves a sliver: fill it with the frame's colour
      ctx.fillStyle = '#0b1422';
      ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    }
    ctx.drawImage(this.base, shake.x, shake.y);
    this._drawRipples(shake);
    ctx.save();
    view.applyTransform(ctx, shake.x, shake.y);
    this._drawClouds();                                                        // over open ground only: claimed ground and obstacles keep their colours
    ctx.restore();
    this._drawTerritory(now, shake);
    ctx.save();
    view.applyTransform(ctx, shake.x, shake.y);
    this._drawFoam();
    this._drawLiveRoute();
    this._drawGhost();
    this._drawPickup(now);
    this.steeringDrawn = {};
    this._drawPatrols(alpha, now);
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
    const wiping = this._drawWipe(now);
    if (fx) fx.drawPopups(ctx, now, view.fit.ratio, shake.x, shake.y);
    this.dirty = this.revealing || wiping;                   // an effect of the renderer's own keeps the frames coming
    this.frames++;
  }

  /* --- events ---------------------------------------------------------------------------------- */

  _onLevel() {
    // The next level of a run, straight from its win screen: keep a picture of the old board to sweep away.
    if (this.game.phase === 'clear' && !this.reducedMotion && this.view.fit && this.frames > 0) {
      const { pxW, pxH } = this.view.fit;
      if (this.wipe.width !== pxW) this.wipe.width = pxW;
      if (this.wipe.height !== pxH) this.wipe.height = pxH;
      this.wipeCtx.drawImage(this.canvas, 0, 0);
      this.wipeAt = performance.now();
    }
    this.revealAt = -Infinity;
    this.revealing = false;
    this.invalidateStatic();
  }

  /* A route closed: flood the new ground outwards from it. Captures made without a route (the test hooks, a restore)
     simply appear. The distances are measured now, against the cells the territory layer was last painted from. */
  _onCapture(result) {
    this.territoryDirty = true;
    this.dirty = true;
    const route = result && result.route;
    if (this.reducedMotion || !route || route.length < 4) return;
    const { cells } = this.game.grid;
    const dist = this.revealDist;
    const fresh = this.revealCells;
    fresh.length = 0;
    dist.fill(0xffff);
    for (let i = 0; i < cells.length; i++) if (!this.solid[i] && (cells[i] === WALL || cells[i] === BORDER)) { fresh.push(i); dist[i] = 0xfffe; }
    if (!fresh.length) return;
    const queue = [];
    const seed = (cx, cy) => {
      if (cx < 0 || cy < 0 || cx >= GRID_W || cy >= GRID_H) return;
      const i = cy * GRID_W + cx;
      if (dist[i] === 0xfffe) { dist[i] = 0; queue.push(i); }
    };
    for (let k = 0; k + 3 < route.length; k += 2) {                         // the route's own cells are where it starts
      seed(Math.floor(route[k] * S), Math.floor(route[k + 1] * S));
      walkCells(route[k] * S, route[k + 1] * S, route[k + 2] * S, route[k + 3] * S, seed);
    }
    let max = 0;
    for (let head = 0; head < queue.length; head++) {
      const i = queue[head], d = dist[i] + 1, x = i % GRID_W;
      if (x > 0 && dist[i - 1] === 0xfffe) { dist[i - 1] = d; queue.push(i - 1); }
      if (x < GRID_W - 1 && dist[i + 1] === 0xfffe) { dist[i + 1] = d; queue.push(i + 1); }
      if (i >= GRID_W && dist[i - GRID_W] === 0xfffe) { dist[i - GRID_W] = d; queue.push(i - GRID_W); }
      if (i < dist.length - GRID_W && dist[i + GRID_W] === 0xfffe) { dist[i + GRID_W] = d; queue.push(i + GRID_W); }
      if (d > max) max = d;
    }
    for (const i of fresh) if (dist[i] === 0xfffe) dist[i] = 0;              // cut off from the route (it cannot be): just show it
    this.revealMax = Math.max(1, max);
    this.revealAt = performance.now();
    this.revealing = true;
  }

  /* --- the base layer ------------------------------------------------------------------------ */

  /* The extra board has colours of its own; every other level takes its palette from the theme. */
  _look() {
    const { run } = this.game;
    return run && run.mode === 'extra' ? EXTRA.look : null;
  }

  _buildBase() {
    const { base, baseCtx: ctx, view, game } = this;
    const { pxW, pxH } = view.fit;
    if (base.width !== pxW) base.width = pxW;
    if (base.height !== pxH) base.height = pxH;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#0b1422';
    ctx.fillRect(0, 0, pxW, pxH);
    ctx.save();
    view.applyTransform(ctx);
    const look = this._look();
    const number = game.level.number;
    const colour = look ? look.field : paletteFor(this.theme, number)[0];
    const seed = game.run ? game.run.seed : 'title';
    const key = `${this.theme}|${colour}|${seed}|${number}`;
    if (key !== this._fieldKey) { this._field = scenery.field(look ? 'flight' : this.theme, colour, seed, number); this._fieldKey = key; }
    ctx.drawImage(this._field, 0, 0, BOARD_W, BOARD_H);
    const shade = ctx.createLinearGradient(0, 0, BOARD_W, BOARD_H);           // light from the top left
    shade.addColorStop(0, 'rgba(255,255,255,.08)');
    shade.addColorStop(0.55, 'rgba(255,255,255,0)');
    shade.addColorStop(1, 'rgba(0,0,0,.17)');
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    const wash = look ? null : scenery.washFor(scenery.gradeFor(number));      // the time of day
    if (wash) {
      ctx.fillStyle = `rgba(${wash[0]},${wash[1]},${wash[2]},${wash[3]})`;
      ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    }
    const vignette = ctx.createRadialGradient(BOARD_W / 2, BOARD_H / 2, BOARD_H * 0.35, BOARD_W / 2, BOARD_H / 2, BOARD_W * 0.62);
    vignette.addColorStop(0, 'rgba(0,6,14,0)');
    vignette.addColorStop(1, 'rgba(0,6,14,0.3)');
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    ctx.restore();
    this.baseDirty = false;
  }

  /* Ripples glinting on open water, drifting slowly: under the territory layer, so only open ground shows them. */
  _drawRipples(shake) {
    if (this.theme !== 'flight' && !this._look()) return;
    const { ctx, view } = this;
    const size = Math.max(32, Math.round(14 * view.fit.k));
    if (!this._wavePattern || this._wavePattern.size !== size) {
      this._wavePattern = { size, pattern: ctx.createPattern(scenery.waveTile(size), 'repeat') };
    }
    const age = this.age;
    const ox = ((age * 0.9 * view.fit.k) % size) - size + shake.x;
    const oy = ((age * 0.35 * view.fit.k) % size) - size + shake.y;
    ctx.save();
    ctx.globalAlpha = 0.09;
    ctx.translate(ox, oy);
    ctx.fillStyle = this._wavePattern.pattern;
    ctx.fillRect(0, 0, this.canvas.width + size * 2, this.canvas.height + size * 2);
    ctx.restore();
  }

  /* --- the territory layer --------------------------------------------------------------------- */

  _buildTerritory() {
    const { territory, territoryCtx: ctx, view, game } = this;
    const { pxW, pxH } = view.fit;
    if (territory.width !== pxW) territory.width = pxW;
    if (territory.height !== pxH) territory.height = pxH;
    const look = this._look();
    this._paintCells(look);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, pxW, pxH);
    ctx.save();
    view.applyTransform(ctx);
    // Claimed ground: its pattern, cut to the solid cells.
    ctx.fillStyle = this._claimedFill(look);
    ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    ctx.globalCompositeOperation = 'destination-in';
    ctx.imageSmoothingEnabled = false;                                        // crisp cells: the pixel edge is deliberate
    ctx.drawImage(this.mask.canvas, 0, 0, BOARD_W, BOARD_H);
    ctx.globalCompositeOperation = 'source-over';
    ctx.drawImage(this.detail.canvas, 0, 0, BOARD_W, BOARD_H);                        // the bevel, the rim of light, the extra board's dots
    ctx.imageSmoothingEnabled = true;
    for (const points of game.level.routes) this._strokeRoute(ctx, points, null, false);
    const light = this._lightVector();
    for (const obstacle of game.level.obstacles) drawObstacleShadow(ctx, obstacle, light, this.theme);
    for (const obstacle of game.level.obstacles) {
      if (this.theme === 'flight') drawMountain(ctx, obstacle); else drawCityBlock(ctx, obstacle);
    }
    ctx.restore();
    this._foam = foamPath(game.grid);
    this.territoryDirty = false;
  }

  /* The claimed ground's fill: a pattern in board units (the extra board keeps its flat ink). */
  _claimedFill(look) {
    if (look) return `rgb(${look.ink[0]},${look.ink[1]},${look.ink[2]})`;
    const k = this.view.fit.k;
    const size = Math.max(24, Math.round(12 * k));
    const key = `${this.theme}|${size}`;
    if (!this._claimedPattern || this._claimedPattern.key !== key) {
      const pattern = this.territoryCtx.createPattern(scenery.claimedTile(this.theme, INK, size), 'repeat');
      if (pattern.setTransform) pattern.setTransform(new DOMMatrix([1 / k, 0, 0, 1 / k, 0, 0]));   // the tile is in device pixels; the fill is drawn in board units
      this._claimedPattern = { key, pattern };
    }
    return this._claimedPattern.pattern;
  }

  /* One pixel per cell: the solid mask, and the detail over it. Claimed ground gets a bevel (lit where open ground is
     above or to the left of it on the screen, shaded where it is below or to the right); open ground next to a wall
     gets the rim of light, strong at one cell and fading at two. */
  _paintCells(look) {
    const { cells, w, h } = this.game.grid;
    const dots = look ? look.dot : null, glow = look ? look.glow : GLOW;         // (the mask only needs its alpha: the ink comes from _claimedFill)
    const mask = this.mask.image.data, px = this.detail.image.data;
    const solid = (v) => v === WALL || v === BORDER;
    const at = (x, y) => (x < 0 || y < 0 || x >= w || y >= h ? true : solid(cells[y * w + x]));
    const light = this._lightCells();
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x, o = i * 4, v = cells[i];
        this.solid[i] = solid(v) ? 1 : 0;
        px[o + 3] = 0;
        if (solid(v)) {
          mask[o + 3] = 255;
          if (dots && v === WALL && (x & 7) === 4 && (y & 7) === 4) { px[o] = dots[0]; px[o + 1] = dots[1]; px[o + 2] = dots[2]; px[o + 3] = 255; continue; }
          if (v !== WALL) continue;
          const lit = !at(x - light.x, y) || !at(x, y - light.y);              // open ground on the lit side
          const dark = !at(x + light.x, y) || !at(x, y + light.y);
          if (lit) { px[o] = glow[0]; px[o + 1] = glow[1]; px[o + 2] = glow[2]; px[o + 3] = 70; }
          else if (dark) { px[o] = 0; px[o + 1] = 0; px[o + 2] = 0; px[o + 3] = 90; }
        } else {
          mask[o + 3] = 0;
          if (v !== FIELD) continue;
          let alpha = 0;
          if ((x > 0 && solid(cells[i - 1])) || (x < w - 1 && solid(cells[i + 1])) || (y > 0 && solid(cells[i - w])) || (y < h - 1 && solid(cells[i + w]))) alpha = 66;
          else if ((x > 1 && solid(cells[i - 2])) || (x < w - 2 && solid(cells[i + 2])) || (y > 1 && solid(cells[i - 2 * w])) || (y < h - 2 && solid(cells[i + 2 * w]))) alpha = 26;
          px[o] = glow[0]; px[o + 1] = glow[1]; px[o + 2] = glow[2]; px[o + 3] = alpha;
        }
      }
    }
    this.mask.ctx.putImageData(this.mask.image, 0, 0);
    this.detail.ctx.putImageData(this.detail.image, 0, 0);
  }

  /* The territory, or while a capture's flood is running, the new territory uncovered cell by cell from the route. */
  _drawTerritory(now, shake) {
    const { ctx } = this;
    const t = (now - this.revealAt) / REVEAL_MS;
    if (!this.revealing || t >= 1 || t < 0) {
      this.revealing = false;
      ctx.drawImage(this.territory, shake.x, shake.y);
      return;
    }
    const front = t * (this.revealMax + REVEAL_SOFT);
    const m = this.revealMask.image.data;
    if (!this.revealMask.ready) { for (let o = 3; o < m.length; o += 4) m[o] = 255; this.revealMask.ready = true; }
    for (const i of this.revealCells) {
      const a = (front - this.revealDist[i]) / REVEAL_SOFT;
      m[i * 4 + 3] = a <= 0 ? 0 : a >= 1 ? 255 : Math.round(a * 255);
    }
    this.revealMask.ctx.putImageData(this.revealMask.image, 0, 0);
    const layer = this.revealLayer, g = this.revealCtx;
    if (layer.width !== this.territory.width) layer.width = this.territory.width;
    if (layer.height !== this.territory.height) layer.height = this.territory.height;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalCompositeOperation = 'copy';
    g.drawImage(this.territory, 0, 0);
    g.globalCompositeOperation = 'destination-in';
    this.view.applyTransform(g);
    g.drawImage(this.revealMask.canvas, 0, 0, BOARD_W, BOARD_H);
    g.globalCompositeOperation = 'source-over';
    ctx.drawImage(layer, shake.x, shake.y);
    for (const i of this.revealCells) m[i * 4 + 3] = 255;                   // leave the mask all-opaque for the next flood
  }

  /* Foam (or dust, on land) running slowly along every shoreline of open ground. */
  _drawFoam() {
    if (!this._foam) return;
    const { ctx } = this;
    const look = this._look();
    ctx.save();
    ctx.setLineDash([0.7, 1.6]);
    ctx.lineDashOffset = -this.age * 1.4;
    ctx.lineWidth = 0.32;
    ctx.lineCap = 'round';
    ctx.strokeStyle = look ? `rgba(${look.glow[0]},${look.glow[1]},${look.glow[2]},0.3)` : this.theme === 'flight' ? 'rgba(232,255,248,0.3)' : 'rgba(244,228,186,0.2)';
    ctx.stroke(this._foam);
    ctx.restore();
  }

  /* Cloud shadows drifting across the whole board, wrapping round. */
  _drawClouds() {
    const { ctx } = this;
    const x = (this.age * 1.3) % BOARD_W;
    ctx.save();
    ctx.globalAlpha = 0.28;
    ctx.drawImage(this._clouds, x - BOARD_W, 0, BOARD_W, BOARD_H);
    ctx.drawImage(this._clouds, x, 0, BOARD_W, BOARD_H);
    ctx.restore();
  }

  /* The old board sweeps off to the right as the next level starts. True while it runs. */
  _drawWipe(now) {
    const t = (now - this.wipeAt) / WIPE_MS;
    if (t < 0 || t >= 1) return false;
    const { ctx } = this;
    const w = this.canvas.width, h = this.canvas.height;
    const e = t * t * (3 - 2 * t);
    const edge = Math.round(e * w);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.wipe, edge, 0, w - edge, h, edge, 0, w - edge, h);
    ctx.fillStyle = 'rgba(114,244,209,0.65)';                                 // a bright seam where the new board meets the old
    ctx.fillRect(edge - Math.max(1, w / 400), 0, Math.max(2, w / 200), h);
    ctx.restore();
    return true;
  }

  /* --- light ------------------------------------------------------------------------------------- */

  /* The screen's light comes from the top left. In board units, that shadow direction is turned with the board. */
  _lightVector() {
    return this.view.fit.rotated ? { x: 1, y: -1 } : { x: 1, y: 1 };
  }

  /* The same, as a step between cells towards the shadow side. */
  _lightCells() { return this._lightVector(); }

  /* A screen offset (in board units along the screen's axes) as an offset on the board. */
  _screenToBoard(sx, sy) { return this.view.fit.rotated ? { x: sy, y: -sx } : { x: sx, y: sy }; }

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

  /* --- patrols ------------------------------------------------------------------------------------ */

  /* A kind's sprite rasterised once at the board's scale, with its blurred silhouette for the shadow: far cheaper than a
     canvas shadow on every patrol every frame. Rebuilt when the scale changes or a sprite (re)loads. */
  _sprite(kind) {
    const { theme } = this;
    const k = this.view.fit.k;
    const key = `${theme}|${kind}`;
    const cached = this._spriteCache.get(key);
    if (cached && cached.k === k) return cached;
    const set = this.sprites[theme];
    const image = set[kind] || set.standard;
    if (!(image.complete && image.naturalWidth > 0)) return null;
    const size = (KINDS[kind] ? KINDS[kind].radius : PATROL_RADIUS) / PATROL_RADIUS;
    const W = SPRITE_W * size, H = SPRITE_H * size;
    const w = Math.max(1, Math.ceil(W * k)), h = Math.max(1, Math.ceil(H * k));
    const body = document.createElement('canvas');
    body.width = w; body.height = h;
    const b = body.getContext('2d');
    // A thin pale rim, like a sticker's edge: it keeps the sprite standing out on a mid-tone field (see the contrast test).
    // Its silhouette is stamped around the sprite, then the sprite goes on top.
    const rim = Math.max(1, Math.round(RIM * k));
    const inset = rim;
    const inner = document.createElement('canvas');
    inner.width = w; inner.height = h;
    const g0 = inner.getContext('2d');
    g0.drawImage(image, inset, inset, w - 2 * inset, h - 2 * inset);
    g0.globalCompositeOperation = 'source-in';
    g0.fillStyle = RIM_COLOUR;
    g0.fillRect(0, 0, w, h);
    for (let a = 0; a < 8; a++) b.drawImage(inner, Math.round(Math.cos((a * Math.PI) / 4) * rim), Math.round(Math.sin((a * Math.PI) / 4) * rim));
    b.drawImage(image, inset, inset, w - 2 * inset, h - 2 * inset);
    const blur = SHADOW[theme].blur * k;
    const margin = Math.ceil(blur * 2) + 1;
    const shadow = document.createElement('canvas');
    shadow.width = w + margin * 2; shadow.height = h + margin * 2;
    const g = shadow.getContext('2d');
    // The silhouette, blurred: drawn far off the canvas with a shadow that lands back on it (works in every browser).
    const away = shadow.width + 10;
    g.shadowColor = 'rgba(2,12,22,0.34)';
    g.shadowBlur = blur;
    g.shadowOffsetX = away;
    g.drawImage(body, margin - away, margin);
    const sprite = { k, body, shadow, margin: margin / k, w: W, h: H };
    this._spriteCache.set(key, sprite);
    return sprite;
  }

  _drawPatrols(alpha, now) {
    const { ctx, theme } = this;
    const flight = theme === 'flight';
    const shade = SHADOW[theme];
    const offset = this._screenToBoard(shade.x, shade.y);
    for (const p of this.game.level.patrols) {
      const x = p.px + (p.x - p.px) * alpha, y = p.py + (p.y - p.py) * alpha;
      const sprite = this._sprite(p.kind);
      this._drawWake(p, x, y, flight);
      this._drawSteering(p, x, y, now);
      // Banking: how far the drawn heading still has to turn to meet the velocity is how hard the patrol is turning. A
      // plane rolls into it (drawn as a squash across its body); a car does not.
      let bank = 0;
      if (flight && !this.reducedMotion && (p.vx !== 0 || p.vy !== 0)) {
        let turn = Math.atan2(p.vy, p.vx) - p.heading;
        turn -= Math.PI * 2 * Math.round(turn / (Math.PI * 2));
        bank = Math.max(-MAX_BANK, Math.min(MAX_BANK, turn * 1.6));
      }
      const across = Math.cos(bank);
      ctx.save();
      ctx.translate(x, y);
      if (sprite) {
        ctx.save();
        ctx.translate(offset.x, offset.y);
        ctx.rotate(p.heading);
        ctx.scale(1, across);
        const m = sprite.margin;
        ctx.drawImage(sprite.shadow, -sprite.w / 2 - m, -sprite.h / 2 - m, sprite.w + 2 * m, sprite.h + 2 * m);
        ctx.restore();
        ctx.rotate(p.heading);
        ctx.scale(1, across);
        ctx.drawImage(sprite.body, -sprite.w / 2, -sprite.h / 2, sprite.w, sprite.h);
      } else {                                               // until the sprite has loaded
        ctx.rotate(p.heading);
        ctx.fillStyle = flight ? '#ff8d63' : '#5bd6e2';
        ctx.fillRect(-1.55, -0.48, 3.1, 0.96);
        ctx.fillRect(-0.25, -1.05, 0.7, 2.1);
      }
      ctx.restore();
    }
  }

  /* A hunter that has noticed a route: during its wind-up a dashed ring closes in on it, so the player sees it coming
     before it turns; while it chases, a solid ring and a tick pointing at the pen. Still (no pulse) with reduced motion. */
  _drawSteering(p, x, y, now) {
    const s = steeringOf(p);
    this.steeringDrawn[s.state] = (this.steeringDrawn[s.state] || 0) + 1;
    if (s.state !== 'windup' && s.state !== 'chase') return;
    const { ctx } = this;
    const scale = this.view.fit.scale;
    ctx.save();
    ctx.lineWidth = 2.2 / scale;
    if (s.state === 'windup') {
      ctx.setLineDash([4 / scale, 3 / scale]);
      ctx.strokeStyle = `rgba(${HUNTER_TINT},${0.35 + 0.6 * s.t})`;
      ctx.beginPath();
      ctx.arc(x, y, p.r + 4.2 - 3 * s.t, 0, Math.PI * 2);
      ctx.stroke();
    } else {
      const pulse = this.reducedMotion ? 0 : 0.25 * Math.sin(now / 90);
      ctx.strokeStyle = `rgba(${HUNTER_TINT},0.9)`;
      ctx.beginPath();
      ctx.arc(x, y, p.r + 1.1 + pulse, 0, Math.PI * 2);
      ctx.stroke();
      const tip = this.game.route.tip, a = Math.atan2(tip.y - y, tip.x - x), r0 = p.r + 1.3;
      ctx.beginPath();
      ctx.moveTo(x + Math.cos(a) * r0, y + Math.sin(a) * r0);
      ctx.lineTo(x + Math.cos(a) * (r0 + 1.4), y + Math.sin(a) * (r0 + 1.4));
      ctx.stroke();
    }
    ctx.restore();
  }

  /* Behind each patrol, built from its recent positions: two contrails from a plane's wingtips, or two tyre tracks
     behind a car, fading with age. */
  _drawWake(p, x, y, flight) {
    const n = p.trailLen;
    if (n < 2) return;
    const { ctx } = this;
    const spread = flight ? 1.55 : 0.75;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineWidth = flight ? 0.28 : 0.22;
    ctx.strokeStyle = flight ? '#f2fffb' : '#1b232b';
    let ax = x, ay = y;
    for (let k = 0; k < n; k++) {                                            // newest first
      const j = (p.trailHead - 1 - k + TRAIL_LENGTH) % TRAIL_LENGTH;
      const bx = p.trail[j * 2], by = p.trail[j * 2 + 1];
      const dx = ax - bx, dy = ay - by, len = Math.hypot(dx, dy);
      if (len > 1e-6 && len < 8) {                                            // (a patrol that was moved by hand leaves no streak)
        const nx = (-dy / len) * spread, ny = (dx / len) * spread;
        ctx.globalAlpha = (1 - k / n) * (flight ? 0.32 : 0.2);
        ctx.beginPath();
        ctx.moveTo(ax + nx, ay + ny); ctx.lineTo(bx + nx, by + ny);
        ctx.moveTo(ax - nx, ay - ny); ctx.lineTo(bx - nx, by - ny);
        ctx.stroke();
      }
      ax = bx; ay = by;
    }
    ctx.restore();
  }
}

/* A small canvas with one pixel per grid cell, and its image data. */
function cellCanvas() {
  const canvas = document.createElement('canvas');
  canvas.width = GRID_W;
  canvas.height = GRID_H;
  const ctx = canvas.getContext('2d');
  return { canvas, ctx, image: ctx.createImageData(GRID_W, GRID_H), ready: false };
}

/* The shorelines as one path in board units: every contour loop, with runs of edges in a line merged into one segment. */
function foamPath(grid) {
  const path = new Path2D();
  for (const loop of traceContours(grid).loops) {
    const n = loop.n;
    if (n < 4) continue;
    const dir = (k) => {
      const a = k % n, b = (k + 1) % n;
      return `${Math.sign(loop.vx[b] - loop.vx[a])},${Math.sign(loop.vy[b] - loop.vy[a])}`;
    };
    path.moveTo(loop.vx[0] / S, loop.vy[0] / S);
    for (let k = 1; k <= n; k++) {
      if (k < n && dir(k) === dir(k - 1)) continue;                          // still going the same way: no corner here
      path.lineTo(loop.vx[k % n] / S, loop.vy[k % n] / S);
    }
    path.closePath();
  }
  return path;
}

/* --- obstacle art --------------------------------------------------------------------------------- */

/* The shadow an obstacle throws onto the ground beside it, away from the light. */
function drawObstacleShadow(ctx, { x, y, w, h }, light, theme) {
  const d = theme === 'flight' ? 1.1 : 0.7;
  ctx.save();
  ctx.fillStyle = 'rgba(2,10,20,0.32)';
  ctx.fillRect(x + light.x * d, y + light.y * d, w, h);
  ctx.restore();
}

function drawMountain(ctx, { x, y, w, h }) {
  ctx.save();
  ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  const ground = ctx.createLinearGradient(x, y, x, y + h);
  ground.addColorStop(0, '#132a3b'); ground.addColorStop(1, '#0c1b28');
  ctx.fillStyle = ground; ctx.fillRect(x, y, w, h);
  const peakA = x + Math.max(1.3, w * 0.28), peakB = x + Math.min(w - 1.3, w * 0.7);
  // The far ridge, then the near one; each with a lit face (towards the light, top left) and a shaded one.
  ctx.fillStyle = '#234252';
  ctx.beginPath(); ctx.moveTo(x + w * 0.25, y + h); ctx.lineTo(peakB, y + h * 0.12); ctx.lineTo(x + w, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#1a3444';
  ctx.beginPath(); ctx.moveTo(peakB, y + h * 0.12); ctx.lineTo(x + w, y + h); ctx.lineTo(peakB + (x + w - peakB) * 0.25, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#315263';
  ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(peakA, y + 0.55); ctx.lineTo(x + w * 0.58, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#3f6576';
  ctx.beginPath(); ctx.moveTo(x, y + h); ctx.lineTo(peakA, y + 0.55); ctx.lineTo(peakA - 0.1, y + h); ctx.closePath(); ctx.fill();
  ctx.fillStyle = '#a9d5cc';                                                // snow on both peaks
  ctx.fillRect(peakA - 0.48, y + 0.62, 0.96, 0.24);
  ctx.fillRect(peakA - 0.23, y + 0.86, 0.46, 0.28);
  ctx.fillRect(peakB - 0.43, y + h * 0.14, 0.86, 0.22);
  ctx.fillStyle = '#d7f3ec';
  ctx.fillRect(peakA - 0.3, y + 0.6, 0.35, 0.14);
  ctx.fillStyle = 'rgba(184,247,219,.38)';                                   // the shoreline at its foot
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
    ctx.fillStyle = 'rgba(0,0,0,0.35)';                                      // each tower's shadow on the street beside it
    ctx.fillRect(cursor + 0.25, top + 0.25, width, y + h - top);
    ctx.fillStyle = i === 1 ? '#304154' : '#26384b';
    ctx.fillRect(cursor, top, width, y + h - top);
    ctx.fillStyle = i === 1 ? '#3d536a' : '#31475d';                         // its roof, lit
    ctx.fillRect(cursor, top, width, 0.3);
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
