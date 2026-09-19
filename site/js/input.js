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
   the keyboard, and P or R R must not act on the game behind it. */
import { PHASE } from './game.js';

const SNAP_FINE_PX = 10;        // a mouse or pen may start this far (CSS px) from safe ground and be pulled onto it
const SNAP_COARSE_PX = 22;      // a finger is less precise

const FORM_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const CONTROL_SELECTOR = 'button, a[href], summary, [role="switch"], [role="radio"]';
const RESTART_WINDOW_MS = 1500;

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

export function installKeyboard({ game, ui }) {
  let restartArmedAt = -Infinity;                   // not 0: that would count as "pressed at page load"

  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target && (target.isContentEditable || FORM_TAGS.has(target.tagName))) return;
    if (ui.isModalOpen()) return;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;

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
}
