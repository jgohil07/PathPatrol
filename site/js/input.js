/* Input: the pointer pipeline that drives the route engine, and the keyboard commands.

   Pointer rules, each one there because the prototype got it wrong on a phone:
   - one pointer owns the route; every other finger is ignored (the prototype let a second finger
     take over the aim)
   - the pointer is captured, so a drag that wanders off the canvas still finishes
   - coalesced events are used when the browser provides them, so a fast swipe keeps its shape
   - every way a pointer can disappear (up, cancel, lost capture, pause, a new level) ends the route
   - the view is frozen while a pointer is down, so a resize cannot make the route jump

   Shortcuts ignore any chord with Cmd, Ctrl or Alt (the prototype paused on Cmd+P and switched theme
   on Ctrl+F), anything typed into a form control, and everything while a dialog is open: the dialog owns
   the keyboard, and P or R R must not act on the game behind it.

   The arrow keys and WASD draw (see pilot.js). They are turned through the board's rotation here, so "up" is up on
   the screen whichever way the board is drawn, and they are only taken while nothing else has the keyboard: with no
   focus, or with the board focused, never from a button or a switch that is being used. */
import { PHASE } from './game.js';
import { screenDirToBoard } from './view.js';

const SNAP_FINE_PX = 10;        // a mouse or pen may start this far (CSS px) from safe ground and be pulled onto it
const SNAP_COARSE_PX = 22;      // a finger is less precise

const FORM_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const CONTROL_SELECTOR = 'button, a[href], summary, [role="switch"], [role="radio"]';
const RESTART_WINDOW_MS = 1500;

/* Which kind of input was used last. A player who started or resumed a run from the keyboard is left with the board
   focused (arrow keys work at once, and the focus ring shows where they go); a mouse or touch player is not given a ring. */
export const lastInput = { keyboard: false };
const STEER = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0], w: [0, -1], s: [0, 1], a: [-1, 0], d: [1, 0] };   // screen directions
const normalise = (key) => (key.length === 1 ? key.toLowerCase() : key);

export function installPointer({ canvas, view, game }) {
  const route = game.route;
  let active = null;                                       // { id } while a pointer owns the route

  const release = () => {
    if (!active) return;
    const { id } = active;
    active = null;
    try { canvas.releasePointerCapture(id); } catch { /* already released */ }
    view.thaw();
  };
  const at = (event) => view.toBoard(event.clientX, event.clientY);

  canvas.addEventListener('pointerdown', (event) => {
    if (active || !event.isPrimary) return;                // a second finger never takes over
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (!game.isPlaying()) return;
    event.preventDefault();
    game.pilot.yield();                                    // a touch on the board puts the keyboard cursor away
    active = { id: event.pointerId };
    try { canvas.setPointerCapture(event.pointerId); } catch { /* a synthetic event has no live pointer to capture */ }
    view.freeze();
    route.coarse = event.pointerType === 'touch';
    const p = at(event);
    route.begin(p.x, p.y, (route.coarse ? SNAP_COARSE_PX : SNAP_FINE_PX) / view.fit.scale);
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!active || event.pointerId !== active.id) return;
    const batch = typeof event.getCoalescedEvents === 'function' ? event.getCoalescedEvents() : [];
    for (const e of batch.length ? batch : [event]) {
      const p = at(e);
      route.move(p.x, p.y);
    }
  });

  canvas.addEventListener('pointerup', (event) => {
    if (!active || event.pointerId !== active.id) return;
    const p = at(event);
    route.move(p.x, p.y);                                  // lifting on safe ground still closes the route
    route.end('lift');
    release();
  });

  const lose = (event) => {
    if (!active || event.pointerId !== active.id) return;
    route.end('cancel');
    release();
  };
  canvas.addEventListener('pointercancel', lose);
  canvas.addEventListener('lostpointercapture', lose);

  canvas.addEventListener('contextmenu', (event) => event.preventDefault());   // a long press must not open a menu

  game.on('phase', () => { if (!game.isPlaying()) release(); });               // pause, win, game over: let go
}

export function installKeyboard({ game, ui, view }) {
  let restartArmedAt = -Infinity;                   // not 0: that would count as "pressed at page load"

  const boardHasKeys = (target) => target === document.body || target === document.documentElement || target.id === 'gameCanvas';     // not a button or a switch being used

  document.addEventListener('keydown', (event) => {
    if (event.metaKey) game.pilot.releaseAll();                   // with Cmd down the browser may never send the key-ups
    if (event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target && (target.isContentEditable || FORM_TAGS.has(target.tagName))) return;
    if (ui.isModalOpen()) return;
    const key = normalise(event.key);

    const steer = STEER[key];
    if (steer) {
      if (!boardHasKeys(target)) return;
      const d = screenDirToBoard(view.fit.rotated, steer[0], steer[1]);
      if (game.pilot.press(key, d.x, d.y, event.repeat)) event.preventDefault();
      return;
    }
    if (key === 'Backspace') {                                    // cancels the route; never "go back", which would leave the run behind
      if (boardHasKeys(target) && game.isPlaying()) { game.pilot.backspace(); event.preventDefault(); }
      return;
    }

    switch (key) {
      case 'p':
        if (!event.repeat) game.togglePause();
        break;
      case 'Escape':
        game.pause('manual');                       // Escape only ever pauses
        break;
      case 'm':
        if (!event.repeat) ui.toggleSound();
        break;
      case 't':
        if (!event.repeat) ui.toggleTheme();
        break;
      case 'h':
      case '?':
        if (!event.repeat) ui.openHelp();
        break;
      case 'Enter':
      case ' ':
        // A focused button, link or switch handles Enter and Space itself; doing it here too would act twice.
        if (event.repeat || (target && target.closest && target.closest(CONTROL_SELECTOR))) break;
        if (ui.confirm()) event.preventDefault();
        break;
      case 'r':
        if (event.repeat) break;
        if (performance.now() - restartArmedAt < RESTART_WINDOW_MS) { restartArmedAt = -Infinity; game.restartLevel(); }
        else if (game.phase === PHASE.PLAYING || game.phase === PHASE.PAUSED) { restartArmedAt = performance.now(); ui.toast('Press R again to restart the level', RESTART_WINDOW_MS); }
        break;
      default:
    }
  });

  document.addEventListener('keyup', (event) => {                 // a key must always be let go, whatever else is held or open
    const key = normalise(event.key);
    if (STEER[key]) game.pilot.lift(key);
  });
}

/* html[data-input] follows the pointer actually being used, so a laptop with a touch screen (or an iPad
   with a trackpad) switches between the touch and mouse presentation as the player switches. Touch is
   the only "touch"; a pen is precise, so it counts as a mouse. The CSS uses it for control sizes and
   keyboard hints; it never changes where the board is, so a touch cannot land on a board that then moves. */
export function installInputMode(root = document.documentElement) {
  const follow = (event) => {
    const mode = event.pointerType === 'touch' ? 'touch' : 'mouse';
    if (root.dataset.input !== mode) root.dataset.input = mode;
  };
  window.addEventListener('pointerdown', follow, { capture: true, passive: true });
  window.addEventListener('pointermove', follow, { capture: true, passive: true });
  window.addEventListener('pointerdown', () => { lastInput.keyboard = false; }, { capture: true, passive: true });
  window.addEventListener('keydown', () => { lastInput.keyboard = true; }, { capture: true, passive: true });
}
