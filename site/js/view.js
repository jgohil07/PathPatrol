/* Fits the board into its stage and maps between screen and board coordinates.

   A stage taller than it is wide rotates the board 90 degrees clockwise, so a phone held upright
   gets a large board and the daily level is still the same 120 x 72 board everywhere.
   The maths is in pure functions (computeFit and friends); the View class only touches the DOM. */
import { BOARD_W, BOARD_H } from './config.js';

/* stageW/stageH in CSS px. The canvas backing store is capped at maxDpr because a phone's 3x panel
   would cost 2.25x the fill work for no visible gain on this art style. */
export function computeFit(stageW, stageH, dpr = 1, maxDpr = 2) {
  const rotated = stageH > stageW;
  const sw = rotated ? BOARD_H : BOARD_W;               // board size as seen on screen, in units
  const sh = rotated ? BOARD_W : BOARD_H;
  const scale = Math.max(0, Math.min(stageW / sw, stageH / sh));      // CSS px per unit
  const ratio = Math.max(1, Math.min(dpr, maxDpr));
  const cssW = sw * scale, cssH = sh * scale;
  const pxW = Math.max(1, Math.round(cssW * ratio));
  const pxH = Math.max(1, Math.round(cssH * ratio));
  return { rotated, sw, sh, scale, cssW, cssH, pxW, pxH, ratio, k: pxW / sw };   // k: device px per unit
}

/* Board units -> device pixels, as the six arguments of ctx.setTransform. */
export function boardMatrix(fit) {
  const k = fit.k;
  return fit.rotated ? [0, k, -k, 0, BOARD_H * k, 0] : [k, 0, 0, k, 0, 0];
}

/* Position inside the canvas as fractions (0..1 across, 0..1 down) <-> board units. */
export function fractionToBoard(rotated, fu, fv, out = { x: 0, y: 0 }) {
  if (rotated) { out.x = fv * BOARD_W; out.y = (1 - fu) * BOARD_H; }
  else { out.x = fu * BOARD_W; out.y = fv * BOARD_H; }
  return out;
}
export function boardToFraction(rotated, x, y, out = { u: 0, v: 0 }) {
  if (rotated) { out.u = 1 - y / BOARD_H; out.v = x / BOARD_W; }
  else { out.u = x / BOARD_W; out.v = y / BOARD_H; }
  return out;
}

/* A screen direction (right = +x, down = +y) as a board direction, for the arrow keys. */
export function screenDirToBoard(rotated, dx, dy) {
  return rotated ? { x: dy, y: -dx } : { x: dx, y: dy };
}

export class View {
  constructor(canvas, stage, onChange = null) {
    this.canvas = canvas;
    this.stage = stage;
    this.onChange = onChange;
    this.fit = null;
    this.frozen = false;
    this._pending = false;
    if (typeof ResizeObserver === 'function') {
      this._observer = new ResizeObserver(() => this.measure());
      this._observer.observe(stage);
    }
    window.addEventListener('resize', () => this.measure());
    this.measure();
  }

  /* Re-fit to the stage. While a pointer is down the view is frozen, so a resize (rotation, the
     browser bar sliding away) cannot make a route jump; it is applied on thaw(). */
  measure() {
    if (this.frozen) { this._pending = true; return false; }
    const w = this.stage.clientWidth, h = this.stage.clientHeight;
    if (w < 2 || h < 2) return false;                   // hidden or not laid out yet
    const fit = computeFit(w, h, window.devicePixelRatio || 1);
    const old = this.fit;
    if (old && old.pxW === fit.pxW && old.pxH === fit.pxH && old.rotated === fit.rotated && old.cssW === fit.cssW && old.cssH === fit.cssH) return false;
    this.fit = fit;
    const { canvas } = this;
    canvas.style.width = `${fit.cssW}px`;
    canvas.style.height = `${fit.cssH}px`;
    if (canvas.width !== fit.pxW) canvas.width = fit.pxW;        // assigning either size clears the canvas
    if (canvas.height !== fit.pxH) canvas.height = fit.pxH;
    if (this.onChange) this.onChange(fit);
    return true;
  }

  freeze() { this.frozen = true; }
  thaw() {
    this.frozen = false;
    if (this._pending) { this._pending = false; this.measure(); }
  }

  applyTransform(ctx) { ctx.setTransform(...boardMatrix(this.fit)); }

  /* Client (viewport) coordinates -> board units. */
  toBoard(clientX, clientY, out = { x: 0, y: 0 }) {
    const r = this.canvas.getBoundingClientRect();
    return fractionToBoard(this.fit.rotated, (clientX - r.left) / r.width, (clientY - r.top) / r.height, out);
  }
}
