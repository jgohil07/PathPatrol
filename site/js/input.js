/* Input. For now: keyboard commands. The pointer pipeline and drawing keys arrive with the route engine.

   Shortcuts ignore any chord with Cmd, Ctrl or Alt (the prototype paused on Cmd+P and switched theme
   on Ctrl+F), and anything typed into a form control. */
import { PHASE } from './game.js';

const FORM_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
const RESTART_WINDOW_MS = 1500;

export function installKeyboard({ game, ui }) {
  let restartArmedAt = -Infinity;                   // not 0: that would count as "pressed at page load"

  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target && (target.isContentEditable || FORM_TAGS.has(target.tagName))) return;
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
      case 'r':
        if (event.repeat) break;
        if (performance.now() - restartArmedAt < RESTART_WINDOW_MS) { restartArmedAt = -Infinity; game.restartLevel(); }
        else if (game.phase === PHASE.PLAYING || game.phase === PHASE.PAUSED) { restartArmedAt = performance.now(); ui.toast('Press R again to restart the level', RESTART_WINDOW_MS); }
        break;
      default:
    }
  });
}
