/* Drawing. Two layers:

   - a static layer (field colour, texture, claimed territory, obstacles), rebuilt only when a level
     starts, ground is claimed, the theme changes or the canvas is resized;
   - a per-frame layer (patrols, trails, flash) drawn on top of a single drawImage of the static one.

   All drawing is in board units; view.applyTransform() maps them to device pixels, rotation included. */
import { BOARD_W, BOARD_H, GRID_W, GRID_H } from './config.js';
import { FIELD, WALL, BORDER } from './grid.js';
import { TRAIL_LENGTH } from './physics.js';

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

const INK = [11, 20, 34];                 // #0b1422: claimed ground and the frame
const GLOW = [114, 244, 209, 56];         // the faint aqua rim on open ground next to a wall

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

    game.on('level', () => this.invalidateStatic());
    game.on('capture', () => this.invalidateStatic());
    game.on('phase', () => this.invalidate());
  }

  invalidate() { this.dirty = true; }
  invalidateStatic() { this.staticDirty = true; this.dirty = true; }
  resize() { this.invalidateStatic(); }
  setTheme(theme) { this.theme = theme; this.invalidateStatic(); }

  /* alpha: how far between the last two physics steps this frame falls (0..1). */
  draw(alpha = 1) {
    const { view, game, ctx } = this;
    if (!view.fit || !game.level) return;
    if (this.staticDirty) this._buildStatic();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(this.layer, 0, 0);
    ctx.save();
    view.applyTransform(ctx);
    this._drawPatrols(alpha);
    if (game.flash > 0) {
      ctx.fillStyle = `rgba(255,92,77,${game.flash * 0.5})`;
      ctx.fillRect(0, 0, BOARD_W, BOARD_H);
    }
    ctx.restore();
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
    const palette = paletteFor(this.theme, game.level.number);
    ctx.fillStyle = palette[0];
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
    for (const obstacle of game.level.obstacles) {
      if (this.theme === 'flight') drawMountain(ctx, obstacle); else drawCityBlock(ctx, obstacle);
    }
    ctx.restore();
    this.staticDirty = false;
  }

  /* Claimed ground and the frame in ink; open ground next to a wall gets a faint rim. */
  _paintTerritory() {
    const { cells, w, h } = this.game.grid;
    const px = this.territoryImage.data;
    const solid = (v) => v === WALL || v === BORDER;
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x, o = i * 4, v = cells[i];
        if (solid(v)) {
          px[o] = INK[0]; px[o + 1] = INK[1]; px[o + 2] = INK[2]; px[o + 3] = 255;
        } else if (v === FIELD && (
          (x > 0 && solid(cells[i - 1])) || (x < w - 1 && solid(cells[i + 1])) ||
          (y > 0 && solid(cells[i - w])) || (y < h - 1 && solid(cells[i + w])))) {
          px[o] = GLOW[0]; px[o + 1] = GLOW[1]; px[o + 2] = GLOW[2]; px[o + 3] = GLOW[3];
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

  /* --- per-frame layer -------------------------------------------------------------------- */

  _drawPatrols(alpha) {
    const { ctx, theme } = this;
    const sprite = this.sprites[theme];
    const ready = sprite.complete && sprite.naturalWidth > 0;
    const glow = 0.14 * this.view.fit.k;                     // shadowBlur is in device px, not units
    for (const p of this.game.level.patrols) {
      ctx.fillStyle = theme === 'flight' ? '#bef7e7' : '#ffca6c';
      for (let k = 0; k < p.trailLen; k++) {                 // newest first
        const j = (p.trailHead - 1 - k + TRAIL_LENGTH) % TRAIL_LENGTH;
        ctx.globalAlpha = ((p.trailLen - k) / p.trailLen) * 0.17;
        ctx.fillRect(p.trail[j * 2] - 0.2, p.trail[j * 2 + 1] - 0.2, 0.4, 0.4);
      }
      ctx.globalAlpha = 1;
      ctx.save();
      ctx.translate(p.px + (p.x - p.px) * alpha, p.py + (p.y - p.py) * alpha);
      ctx.rotate(Math.atan2(p.vy, p.vx));
      ctx.shadowColor = theme === 'flight' ? '#ff9271' : '#9aefff';
      ctx.shadowBlur = glow;
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
