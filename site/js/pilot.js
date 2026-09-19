/* The keyboard pilot: draws with the arrow keys or WASD by driving the route engine as a pointer that is always exactly
   where the cursor is. Nothing else changes: the same cells, the same patrol and tracer hits, the same close, the same
   sound and tip ring. It steps on the game clock (a pause stops it) and works in board units; the input layer has
   already turned "up, down, left, right on the screen" into board directions, whatever way the board is turned.

   Xonix rules:
   - the cursor moves in the direction of the last key pressed; letting go of that key falls back to an earlier one
     that is still held, and letting go of all of them stops it. Stopping in the field leaves the route live
   - a route that closes, or is lost to a patrol or a tracer, stops the cursor where the route began or ended, and
     it waits for a fresh key press, so a held key never carries it on into ground it did not choose
   - Backspace drops the route being drawn (free, but it breaks the combo) and returns the cursor to where it began
   - nothing shows until the first key is pressed, and a pointer taking over puts the cursor away again */
import { BOARD_W, BOARD_H, FRAME_UNITS, CELLS_PER_UNIT as S, KEYBOARD, TUTORIAL } from './config.js';
import { toCell } from './grid.js';
import { MODE } from './route.js';

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export class Pilot {
  constructor(game) {
    this.game = game;
    this.active = false;                 // the cursor is out: the route engine has a virtual pointer down on it
    this.x = BOARD_W / 2;                // the cursor, in board units; on safe ground unless a route is being drawn
    this.y = FRAME_UNITS / 2;
    this.held = [];                      // [{ key, x, y }]: the direction keys down, oldest first; the last one steers
    this.halted = false;                 // a route ended: no movement until a fresh press
    this.unsaid = false;                 // re-armed quietly: the next press says "armed", as a touch on the edge would
    game.on('phase', ({ phase }) => { if (phase !== 'playing') this.stop(); });
    game.on('level', () => { this.stop(); this._home(); });
    game.on('capture', () => { this.halted = true; });
  }

  /* A direction key went down. (bx, by) is that direction on the board. Returns whether the key was taken, so the
     caller can keep the page from scrolling. Auto-repeat only keeps a direction going; it is never a new press. */
  press(key, bx, by, repeat = false) {
    if (!this.game.isPlaying()) return false;
    if (repeat) return this.active;
    if (!this.active && !this._engage()) return false;
    this._settle();
    this.held.push({ key, x: bx, y: by });
    this.halted = false;
    if (this.unsaid) { this.unsaid = false; this.game.emit('route', { type: 'armed' }); }
    return true;
  }

  lift(key) {
    this.held = this.held.filter((h) => h.key !== key);
  }

  /* Every key is forgotten, in case a key-up was swallowed (macOS sends none while Cmd is down). */
  releaseAll() { this.held.length = 0; }

  /* Backspace: drop the route being drawn and go back to where it began. */
  backspace() {
    const { route } = this.game;
    if (!this.active || route.mode !== MODE.DRAWING) return;
    route.end('backspace');              // the engine erases it and says why: the game breaks the combo
    this._rearm();
  }

  /* A pointer is taking the route engine over: put the cursor away, and leave the route to the pointer. */
  yield() {
    this.active = false;
    this.held.length = 0;
    this.halted = false;
    this.unsaid = false;
  }

  /* Play stopped, or the window lost the keyboard: forget the keys, and hand the route engine back. */
  stop() {
    this.held.length = 0;
    this.halted = false;
    this.unsaid = false;
    if (!this.active) return;
    this.active = false;
    this._toSafeGround();
    this.game.route.end('stop');
  }

  /* Called every physics step while playing. */
  update(dt) {
    if (!this.active) return;
    this._settle();
    const dir = this.halted ? null : this.held[this.held.length - 1];
    if (!dir) return;
    const step = KEYBOARD.speed * dt;
    this.x = clamp(this.x + dir.x * step, 0, BOARD_W);
    this.y = clamp(this.y + dir.y * step, 0, BOARD_H);
    this.game.route.move(this.x, this.y);
  }

  /* --- internals -------------------------------------------------------------------------- */

  _engage() {
    const { route } = this.game;
    if (route.down) return false;        // a pointer has it (the engine forgets a stale one when play stops)
    this._toSafeGround();
    route.coarse = false;
    route.begin(this.x, this.y, 0);      // the cursor is on safe ground, so this arms
    this.active = true;
    this.halted = false;
    this.unsaid = false;
    return true;
  }

  /* A patrol or a tracer caught the route since the last step: back to where it began, waiting for a fresh press. */
  _settle() {
    if (this.game.route.mode === MODE.SPENT) this._rearm();
  }

  _rearm() {
    const { route } = this.game;
    const { cx, cy } = route.anchor;
    this.x = (cx + 0.5) / S;
    this.y = (cy + 0.5) / S;
    this.halted = true;
    this.unsaid = true;
    route.begin(this.x, this.y, 0, true);   // down again, armed on the safe cell the route began from
  }

  _toSafeGround() {
    const { grid, route } = this.game;
    if (grid.isSolid(toCell(this.x), toCell(this.y))) return;
    if (grid.isSolid(route.anchor.cx, route.anchor.cy)) {
      this.x = (route.anchor.cx + 0.5) / S;
      this.y = (route.anchor.cy + 0.5) / S;
    } else this._home();
  }

  /* Where the cursor starts on a new level: the middle of the top edge, or under the tutorial's ghost finger. */
  _home() {
    const run = this.game.run;
    this.x = run && run.mode === 'tutorial' ? TUTORIAL.ghostX : BOARD_W / 2;
    this.y = FRAME_UNITS / 2;
  }
}
