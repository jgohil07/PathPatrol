/* Contours: the boundary between open ground and everything solid, as closed loops of unit edges.

   Method: crack-following. Every open cell side that touches a solid cell (or the edge of the grid) is a directed unit
   edge, oriented so that the open cell is on its right (y grows downwards). At each corner exactly one edge leaves, except
   where two open cells touch only diagonally: there the loop turns right, staying with the cell it is hugging. That
   keeps the two apart, which matches the 4-connected flood fill that decides what a capture claims.

   The guarantees (tested on random grids): every boundary edge is in exactly one loop, every loop is closed, and
   consecutive edges share a corner. The outer boundary of a region is one loop, and each obstacle inside it is another.

   "Open" is any cell that is not solid, so a route being drawn (ROUTE cells) does not change the contours. */
import { CELLS_PER_UNIT as S } from './config.js';
import { WALL, BORDER } from './grid.js';

const DX = [1, 0, -1, 0];                 // east, south, west, north
const DY = [0, 1, 0, -1];

/* loops[i] = { n, vx, vy, solid }: edge k of a loop runs from corner (vx[k], vy[k]) to the corner of edge k+1 (wrapping);
   solid[k] is the index of the solid cell across that edge, or -1 outside the grid. Longest loop first. */
export function traceContours(grid) {
  const { w, h, cells } = grid;
  const solidAt = (x, y) => x < 0 || y < 0 || x >= w || y >= h || cells[y * w + x] === WALL || cells[y * w + x] === BORDER;
  const W1 = w + 1;

  // 1. the edges
  const from = [], dirs = [], across = [];
  const add = (vx, vy, dir, x, y) => { from.push(vy * W1 + vx); dirs.push(dir); across.push(x < 0 || y < 0 || x >= w || y >= h ? -1 : y * w + x); };
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (solidAt(x, y)) continue;
      if (solidAt(x, y - 1)) add(x, y, 0, x, y - 1);                 // top side, travelling east
      if (solidAt(x + 1, y)) add(x + 1, y, 1, x + 1, y);              // right side, travelling south
      if (solidAt(x, y + 1)) add(x + 1, y + 1, 2, x, y + 1);          // bottom side, travelling west
      if (solidAt(x - 1, y)) add(x, y + 1, 3, x - 1, y);              // left side, travelling north
    }
  }
  const edges = from.length;
  if (!edges) return { loops: [], edges: 0 };

  // 2. link them: which edges leave each corner (at most two)
  const first = new Int32Array((w + 1) * (h + 1)).fill(-1);
  const next = new Int32Array(edges).fill(-1);
  for (let e = edges - 1; e >= 0; e--) { next[e] = first[from[e]]; first[from[e]] = e; }

  // 3. walk them into loops, always taking the right-most turn
  const used = new Uint8Array(edges);
  const loops = [];
  for (let start = 0; start < edges; start++) {
    if (used[start]) continue;
    const ids = [];
    let e = start;
    do {
      used[e] = 1;
      ids.push(e);
      const vx = (from[e] % W1) + DX[dirs[e]], vy = Math.floor(from[e] / W1) + DY[dirs[e]];
      let pick = -1, best = -1;
      for (let c = first[vy * W1 + vx]; c >= 0; c = next[c]) {
        if (used[c] && c !== start) continue;
        const turn = (dirs[c] - dirs[e] + 4) % 4;                     // 1 = right, 0 = straight, 3 = left, (2 never happens)
        const rank = turn === 1 ? 3 : turn === 0 ? 2 : 1;
        if (rank > best) { best = rank; pick = c; }
      }
      e = pick;
    } while (e !== start && e >= 0);
    const n = ids.length;
    const loop = { n, vx: new Int16Array(n), vy: new Int16Array(n), solid: new Int32Array(n) };
    for (let k = 0; k < n; k++) {
      loop.vx[k] = from[ids[k]] % W1;
      loop.vy[k] = Math.floor(from[ids[k]] / W1);
      loop.solid[k] = across[ids[k]];
    }
    loops.push(loop);
  }
  loops.sort((a, b) => b.n - a.n);
  return { loops, edges };
}

/* The point at fractional edge index t along a loop, in board units. */
export function pointAt(loop, t, out = { x: 0, y: 0 }) {
  const n = loop.n;
  const i = Math.floor(t) % n, f = t - Math.floor(t);
  const j = (i + 1) % n;
  out.x = (loop.vx[i] + (loop.vx[j] - loop.vx[i]) * f) / S;
  out.y = (loop.vy[i] + (loop.vy[j] - loop.vy[i]) * f) / S;
  return out;
}

/* The edge closest to (x, y) in board units, over every loop: { loop, k, d2 } or null. Distances go to the edge's
   midpoint, which is enough to choose between edges a whole cell apart. */
export function nearestEdge(loops, x, y) {
  let best = null, bestSq = Infinity;
  const cx = x * S, cy = y * S;
  for (let li = 0; li < loops.length; li++) {
    const loop = loops[li];
    for (let k = 0; k < loop.n; k++) {
      const j = (k + 1) % loop.n;
      const mx = (loop.vx[k] + loop.vx[j]) / 2, my = (loop.vy[k] + loop.vy[j]) / 2;
      const d = (mx - cx) * (mx - cx) + (my - cy) * (my - cy);
      if (d < bestSq) { bestSq = d; best = { loop: li, k, d2: d / (S * S) }; }
    }
  }
  return best;
}
