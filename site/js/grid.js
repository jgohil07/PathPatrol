/* The cell grid: claimed territory, the frame and obstacles, and (later) the route being drawn.
   Cells are 1/CELLS_PER_UNIT of a world unit on a side; out-of-bounds counts as solid. */
import { GRID_W, GRID_H, CELLS_PER_UNIT } from './config.js';

export const FIELD = 0;     // open ground: patrols roam here and routes can be drawn here
export const WALL = 1;      // territory the player has claimed
export const BORDER = 2;    // the frame and the obstacle blocks
export const ROUTE = 3;     // a route that is still being drawn; patrols that touch it cost a life

/* World units to a cell coordinate. */
export const toCell = (unit) => Math.floor(unit * CELLS_PER_UNIT);

export class Grid {
  constructor(w = GRID_W, h = GRID_H) {
    this.w = w;
    this.h = h;
    this.cells = new Uint8Array(w * h);
    this._queue = new Int32Array(w * h);     // scratch space, reused by every flood fill
    this._seen = new Uint8Array(w * h);
  }

  index(x, y) { return y * this.w + x; }
  inBounds(x, y) { return x >= 0 && y >= 0 && x < this.w && y < this.h; }
  get(x, y) { return this.inBounds(x, y) ? this.cells[y * this.w + x] : BORDER; }
  set(x, y, value) { if (this.inBounds(x, y)) this.cells[y * this.w + x] = value; }
  isSolid(x, y) { const v = this.get(x, y); return v === WALL || v === BORDER; }

  clear() { this.cells.fill(FIELD); }

  /* Cells [x0, x1) x [y0, y1). */
  fillRect(x0, y0, x1, y1, value) {
    const xa = Math.max(0, x0), xb = Math.min(this.w, x1);
    for (let y = Math.max(0, y0); y < Math.min(this.h, y1); y++) {
      for (let x = xa; x < xb; x++) this.cells[y * this.w + x] = value;
    }
  }

  /* The outer frame, `thickness` cells wide. */
  frame(thickness) {
    this.fillRect(0, 0, this.w, thickness, BORDER);
    this.fillRect(0, this.h - thickness, this.w, this.h, BORDER);
    this.fillRect(0, 0, thickness, this.h, BORDER);
    this.fillRect(this.w - thickness, 0, this.w, this.h, BORDER);
  }

  count(value) {
    let n = 0;
    for (let i = 0; i < this.cells.length; i++) if (this.cells[i] === value) n++;
    return n;
  }
  countField() { return this.count(FIELD); }

  /* True if any solid cell in [x0, x1) x [y0, y1) exists. */
  rectHasSolid(x0, y0, x1, y1) {
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (this.isSolid(x, y)) return true;
    return false;
  }

  /* Does a circle (world units) overlap any solid cell? Tests against each cell's rectangle, so a
     circle grazing a corner is judged by its true distance, not by the cell centre. */
  circleHitsSolid(cx, cy, r) {
    const s = CELLS_PER_UNIT;
    const x0 = Math.floor((cx - r) * s), x1 = Math.floor((cx + r) * s);
    const y0 = Math.floor((cy - r) * s), y1 = Math.floor((cy + r) * s);
    const rr = r * r;
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        if (!this.isSolid(x, y)) continue;
        const nx = Math.max(x / s, Math.min(cx, (x + 1) / s));
        const ny = Math.max(y / s, Math.min(cy, (y + 1) / s));
        if ((cx - nx) * (cx - nx) + (cy - ny) * (cy - ny) < rr) return true;
      }
    }
    return false;
  }

  /* Flood-fills open ground (4-connected) from the seed cell indices, then turns every open cell the
     fill could not reach into WALL. Returns the number of cells claimed. */
  claimUnreachable(seeds) {
    const { cells, w, _queue: queue, _seen: seen } = this;
    const last = cells.length - w;
    seen.fill(0);
    let head = 0, tail = 0;
    for (const i of seeds) {
      if (cells[i] === FIELD && !seen[i]) { seen[i] = 1; queue[tail++] = i; }
    }
    while (head < tail) {
      const i = queue[head++];
      const x = i % w;
      if (x > 0 && cells[i - 1] === FIELD && !seen[i - 1]) { seen[i - 1] = 1; queue[tail++] = i - 1; }
      if (x < w - 1 && cells[i + 1] === FIELD && !seen[i + 1]) { seen[i + 1] = 1; queue[tail++] = i + 1; }
      if (i >= w && cells[i - w] === FIELD && !seen[i - w]) { seen[i - w] = 1; queue[tail++] = i - w; }
      if (i < last && cells[i + w] === FIELD && !seen[i + w]) { seen[i + w] = 1; queue[tail++] = i + w; }
    }
    let claimed = 0;
    for (let i = 0; i < cells.length; i++) {
      if (cells[i] === FIELD && !seen[i]) { cells[i] = WALL; claimed++; }
    }
    return claimed;
  }
}
