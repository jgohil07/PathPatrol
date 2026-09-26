/* Scenery: the textures the board is painted with, generated in code (no image files) and baked once.

   - field(): the open ground for a level. Flight is water (depth and ripples from value noise), Drive is farmland
     (patches of crops in rows, with hedges between them). Seeded by the level, so level n always looks the same.
   - waveTile(): a small tile of ripple glints, scrolled over the water every frame.
   - clouds(): soft cloud shadows that drift over the whole board, wrapping left to right.
   - claimedTile(): the pattern on claimed ground (Flight: contour lines of high ground; Drive: a city grid).
   - grade(): the time of day for a level: day, dusk, night or dawn, a band of six levels each.

   Everything returns a canvas; nothing here draws on the game canvas or allocates per frame. */
import { BOARD_W, BOARD_H } from './config.js';
import { Rng } from './rng.js';

export const TEXTURE_PER_UNIT = 4;                    // texture pixels per board unit (smoothed when drawn)
export const GRADES = ['day', 'dusk', 'night', 'dawn'];
/* A wash over the open field for each time of day: [r, g, b, alpha]. Day is untouched. */
const WASH = { day: null, dusk: [255, 120, 70, 0.16], night: [8, 16, 58, 0.48], dawn: [255, 170, 190, 0.12] };

export const gradeFor = (level) => GRADES[Math.floor((Math.max(1, level) - 1) / 6) % GRADES.length];
export const washFor = (grade) => WASH[grade];

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
}

const hex = (colour) => {
  const n = parseInt(colour.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const clamp = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);

/* Value noise on a lattice of `cell` pixels, smoothly interpolated. */
function valueNoise(rng, w, h, cell) {
  const gw = Math.ceil(w / cell) + 2, gh = Math.ceil(h / cell) + 2;
  const lattice = new Float32Array(gw * gh);
  for (let i = 0; i < lattice.length; i++) lattice[i] = rng.float();
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    const fy = y / cell, iy = Math.floor(fy), ty = fy - iy, sy = ty * ty * (3 - 2 * ty);
    for (let x = 0; x < w; x++) {
      const fx = x / cell, ix = Math.floor(fx), tx = fx - ix, sx = tx * tx * (3 - 2 * tx);
      const a = lattice[iy * gw + ix], b = lattice[iy * gw + ix + 1];
      const c = lattice[(iy + 1) * gw + ix], d = lattice[(iy + 1) * gw + ix + 1];
      out[y * w + x] = (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy;
    }
  }
  return out;
}

/* The open ground of a level, TEXTURE_PER_UNIT pixels per unit. `base` is the palette's field colour. */
export function field(theme, base, seed, level) {
  const k = TEXTURE_PER_UNIT;
  const w = BOARD_W * k, h = BOARD_H * k;
  const out = canvas(w, h);
  const g = out.getContext('2d');
  const image = g.createImageData(w, h);
  const px = image.data;
  const rng = new Rng(`${seed}|scenery|${theme}|${level}`);
  const [r0, g0, b0] = hex(base);
  if (theme === 'drive') {
    paintFarmland(px, w, h, r0, g0, b0, rng);
  } else {
    const depth = valueNoise(rng, w, h, 70);
    const swell = valueNoise(rng, w, h, 22);
    for (let i = 0, o = 0; i < w * h; i++, o += 4) {
      // Broad shallows (lighter, a touch greener) and deeps, with a gentler swell over them: water, not smudges.
      const d = 0.7 * depth[i] + 0.3 * swell[i];
      const f = 0.93 + 0.12 * d;
      px[o] = clamp(r0 * f); px[o + 1] = clamp(g0 * f + 7 * (d - 0.5)); px[o + 2] = clamp(b0 * f + 3 * (d - 0.5)); px[o + 3] = 255;
    }
  }
  g.putImageData(image, 0, 0);
  return out;
}

/* Farmland: a jittered grid of fields, each a slightly different crop colour with rows running one way, and darker
   hedges along the borders between them. */
function paintFarmland(px, w, h, r0, g0, b0, rng) {
  const k = TEXTURE_PER_UNIT;
  const rows = [0];
  while (rows[rows.length - 1] < h) rows.push(rows[rows.length - 1] + Math.round((9 + rng.float() * 10) * k));
  const tone = valueNoise(rng, w, h, 60);
  for (let j = 0; j < rows.length - 1; j++) {
    const cols = [-Math.round(rng.float() * 14 * k)];                      // each row of fields has its own boundaries, like brickwork
    while (cols[cols.length - 1] < w) cols.push(cols[cols.length - 1] + Math.round((11 + rng.float() * 14) * k));
    for (let i = 0; i < cols.length - 1; i++) {
      const tint = 0.9 + rng.float() * 0.18, warm = (rng.float() - 0.5) * 16;
      const across = rng.float() < 0.5;                                    // crop rows run across or down this field
      const x0 = Math.max(0, cols[i]), x1 = Math.min(w, cols[i + 1]), y0 = rows[j], y1 = Math.min(h, rows[j + 1]);
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const o = (y * w + x) * 4;
          const hedge = x - x0 < 2 || y - y0 < 2;
          const row = ((across ? y : x) % 5) < 1 ? 0.94 : 1;
          const f = (hedge ? 0.72 : tint * row) * (0.94 + 0.12 * tone[y * w + x]);
          px[o] = clamp(r0 * f + warm); px[o + 1] = clamp(g0 * f + (hedge ? -4 : 0)); px[o + 2] = clamp(b0 * f - warm * 0.5); px[o + 3] = 255;
        }
      }
    }
  }
}

/* A tile of little ripple glints, `size` device pixels square, drawn at `alpha`. Seamless when repeated. */
export function waveTile(size) {
  const out = canvas(size, size);
  const g = out.getContext('2d');
  const rng = new Rng('waves');
  g.strokeStyle = 'rgba(235,255,250,1)';
  g.lineCap = 'round';
  g.lineWidth = Math.max(1, size / 110);
  for (let i = 0; i < 14; i++) {
    const x = rng.float() * size, y = rng.float() * size, len = size * (0.03 + rng.float() * 0.05);
    for (const dx of [-size, 0, size]) {                                  // drawn three times over, so the tile wraps
      for (const dy of [-size, 0, size]) {
        g.beginPath();
        g.moveTo(x + dx - len, y + dy);
        g.quadraticCurveTo(x + dx, y + dy - len * 0.35, x + dx + len, y + dy);
        g.stroke();
      }
    }
  }
  return out;
}

/* Cloud shadows over the board (BOARD_W x BOARD_H units at `k` pixels per unit, kept small: they are soft). Blobs near
   the right edge are drawn again at the left, so the layer wraps seamlessly as it drifts. */
export function clouds(k = 2) {
  const w = BOARD_W * k, h = BOARD_H * k;
  const out = canvas(w, h);
  const g = out.getContext('2d');
  const rng = new Rng('clouds');
  for (let i = 0; i < 9; i++) {
    const cx = rng.float() * w, cy = rng.float() * h, r = (8 + rng.float() * 12) * k;
    for (let puff = 0; puff < 4; puff++) {
      const px = cx + (rng.float() - 0.5) * r * 1.6, py = cy + (rng.float() - 0.5) * r * 0.7, pr = r * (0.55 + rng.float() * 0.45);
      for (const dx of [-w, 0, w]) {
        const blob = g.createRadialGradient(px + dx, py, 0, px + dx, py, pr);
        blob.addColorStop(0, 'rgba(0,8,20,0.5)');
        blob.addColorStop(1, 'rgba(0,8,20,0)');
        g.fillStyle = blob;
        g.fillRect(px + dx - pr, py - pr, pr * 2, pr * 2);
      }
    }
  }
  return out;
}

/* The pattern on claimed ground: a tile `size` device pixels square, over the ink colour [r, g, b]. */
export function claimedTile(theme, ink, size) {
  const out = canvas(size, size);
  const g = out.getContext('2d');
  const [r, gg, b] = ink;
  g.fillStyle = `rgb(${r},${gg},${b})`;
  g.fillRect(0, 0, size, size);
  const line = Math.max(1, size / 90);
  if (theme === 'drive') {                                                // city blocks between streets
    const step = size / 3;
    g.fillStyle = `rgb(${r + 7},${gg + 11},${b + 15})`;
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) g.fillRect(x * step + step * 0.12, y * step + step * 0.12, step * 0.76, step * 0.76);
    g.fillStyle = `rgb(${r + 14},${gg + 21},${b + 27})`;
    for (let y = 0; y < 3; y++) for (let x = 0; x < 3; x++) if ((x + y) % 2 === 0) g.fillRect(x * step + step * 0.3, y * step + step * 0.3, step * 0.4, step * 0.4);
  } else {                                                                // contour lines of high ground
    g.strokeStyle = `rgb(${r + 13},${gg + 23},${b + 26})`;
    g.lineWidth = line;
    for (let i = 0; i < 4; i++) {
      const y = (i + 0.5) * (size / 4);
      g.beginPath();
      for (let x = 0; x <= size; x += size / 24) {
        const yy = y + Math.sin((x / size) * Math.PI * 2 + i * 1.7) * size * 0.06;
        if (x === 0) g.moveTo(x, yy); else g.lineTo(x, yy);
      }
      g.stroke();
    }
  }
  return out;
}
