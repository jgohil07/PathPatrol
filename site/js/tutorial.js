/* The tutorial coach: three steps on a gentle board, with a scripted ghost finger that shows each one.

     1  touch an edge           done when a touch finds safe ground
     2  drag into the field      done when the live route is TUTORIAL.dragCells long
     3  finish on any edge       done by a capture of at least TUTORIAL.minCapture percent

   Nothing here can hurt: a lift or a patrol hit only sends the coach back to step 1, and the tutorial's captures
   never touch the score or the records (the game checks the run's mode). The ghost is drawn by the renderer from
   ghostAt(), in board units, so it lands in the right place on the rotated portrait board as well.

   The coach's messages are kept short on purpose: they share the one-line console under the HUD, which on a
   320 px phone holds about 36 characters. A test enforces that. */
import { TUTORIAL, BOARD_H } from './config.js';

export const STEP = Object.freeze({ EDGE: 1, DRAG: 2, FINISH: 3 });

export const COACH = Object.freeze({
  [STEP.EDGE]: 'Start on the glowing edge',
  [STEP.DRAG]: 'Keep going into the field',
  [STEP.FINISH]: 'Now finish on any edge',
  lifted: 'Lifted early, no harm. Try again',
  cancelled: 'Cancelled, no harm. Try again',
  hit: 'A plane hit it: free here. Again',
  small: 'Too small. Cross the whole board',
});

const TOP = 1;                                 // the ghost starts on the top edge...
const MIDDLE = BOARD_H / 2;                    // ...crosses the middle...
const BOTTOM = BOARD_H - 1;                    // ...and ends on the bottom edge
const MOVE_MS = 1500;                          // one sweep of the ghost
const HOLD_MS = 700;                           // then it waits before starting over

const smooth = (t) => t * t * (3 - 2 * t);

export class Tutorial {
  constructor(game) {
    this.game = game;
    this.active = false;
    this.step = STEP.EDGE;
    this.origin = 'start';                     // 'start' (first launch) or 'help' (replayed): where Skip goes afterwards
    game.on('route', (event) => this._onRoute(event));
    game.on('capture', (result) => this._onCapture(result));
  }

  start(origin = 'start') {
    this.active = true;
    this.origin = origin;
    this._go(STEP.EDGE);
  }

  stop() {
    if (!this.active) return;
    this.active = false;
    this.game.emit('tutorial', { active: false });
  }

  _go(step, notice = '') {
    this.step = step;
    this.game.emit('tutorial', { active: true, step, text: notice || COACH[step] });
  }

  _onRoute(event) {
    if (!this.active) return;
    if (event.type === 'armed' && this.step === STEP.EDGE) this._go(STEP.DRAG);
    else if (event.type === 'cancel' && (event.reason === 'lift' || event.reason === 'cancel')) this._go(STEP.EDGE, COACH.lifted);
    else if (event.type === 'cancel' && event.reason === 'backspace') this._go(STEP.EDGE, COACH.cancelled);
    else if (event.type === 'hit') this._go(STEP.EDGE, COACH.hit);
  }

  /* Called every physics step while playing. */
  update() {
    if (!this.active) return;
    const route = this.game.route;
    if (this.step === STEP.DRAG && route.cells.length >= TUTORIAL.dragCells) this._go(STEP.FINISH);
    else if (this.step === STEP.DRAG && !route.down) this._go(STEP.EDGE);            // let go before drawing anything
  }

  _onCapture(result) {
    if (!this.active) return;
    if (result.gained >= TUTORIAL.minCapture) this.game.finishTutorial(result);
    else this._go(STEP.EDGE, COACH.small);
  }

  /* Where the ghost finger is at `ms` (a running clock in milliseconds), in board units. `moving` is false when
     it should simply pulse in place. */
  ghostAt(ms) {
    const x = TUTORIAL.ghostX;
    if (this.step === STEP.EDGE) return { x, y: TOP, fromY: TOP, toY: TOP, moving: false, pulse: 0.5 + 0.5 * Math.sin(ms / 260) };
    const [from, to] = this.step === STEP.DRAG ? [TOP, MIDDLE] : [MIDDLE, BOTTOM];
    const phase = ms % (MOVE_MS + HOLD_MS);
    const t = smooth(Math.min(1, phase / MOVE_MS));
    return { x, y: from + (to - from) * t, fromY: from, toY: to, moving: true, pulse: 1 };
  }
}
