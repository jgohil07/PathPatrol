/* Composition root: builds the pieces, runs the loop, and installs the safety nets. */
import { STEP, MAX_STEPS_PER_FRAME } from './config.js';
import { createStorage } from './storage.js';
import { Game, PHASE } from './game.js';
import { View } from './view.js';
import { Renderer } from './render.js';
import { UI } from './ui.js';
import { Sound } from './audio.js';
import { Haptics } from './haptics.js';
import { Fx } from './fx.js';
import { installInputMode, installKeyboard, installPointer } from './input.js';

const debug = new URLSearchParams(location.search).has('debug');

const STATS_WINDOW_MS = 500;

/* Fixed-step simulation with interpolated drawing: motion is identical at 60, 90, 120 or 144 Hz.
   loop.stats is refreshed twice a second: frames per second and the script time one frame costs
   (update plus draw, not the wait for the next vsync). loop.onStats, when set, is called with it. */
function startLoop({ game, renderer, sound }) {
  let last = performance.now();
  let acc = 0;
  let windowStart = last, windowFrames = 0, windowWork = 0, windowMax = 0;
  const loop = {
    frozen: false,                     // tests hold the simulation still and step it by hand
    frames: 0,
    stats: { fps: 0, avgMs: 0, maxMs: 0 },
    onStats: null,
    onFrame: null,                     // called every frame before drawing (the HUD's power-up chips)
  };

  function work(dt) {
    game.tick(dt);
    sound.update();                                     // the drawing hum follows the route, frame by frame
    if (loop.onFrame) loop.onFrame();
    if (loop.frozen || !game.isStepping()) {
      acc = 0;
    } else {
      acc += dt;
      let steps = 0;
      while (acc >= STEP && steps < MAX_STEPS_PER_FRAME) { game.step(STEP); acc -= STEP; steps++; }
      if (steps === MAX_STEPS_PER_FRAME) acc = 0;      // too slow to catch up: drop the time, don't spiral
    }
    if (renderer.dirty || game.isAnimating() || (renderer.fx && renderer.fx.active)) renderer.draw(loop.frozen ? 1 : acc / STEP);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
    last = now;
    loop.frames++;
    if (game.phase === PHASE.CRASHED) return;
    const began = performance.now();
    work(dt);
    const cost = performance.now() - began;
    windowFrames++;
    windowWork += cost;
    if (cost > windowMax) windowMax = cost;
    if (now - windowStart >= STATS_WINDOW_MS) {
      loop.stats = { fps: Math.round((windowFrames * 1000) / (now - windowStart)), avgMs: windowWork / windowFrames, maxMs: windowMax };
      if (loop.onStats) loop.onStats(loop.stats);
      windowStart = now; windowFrames = 0; windowWork = 0; windowMax = 0;
    }
  }
  requestAnimationFrame(frame);
  return loop;
}

/* A hidden tab, a blurred window or a page being unloaded pauses the run. Hiding or unloading also saves it
     (a tab swiped away on a phone may never come back), after the pause has erased any route in progress. */
function installAutoPause(game) {
  const away = () => { game.pause('auto'); game.persist(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) away(); });
  window.addEventListener('blur', () => game.pause('auto'));
  window.addEventListener('pagehide', away);
}

/* Anything uncaught stops the game and says so, instead of leaving a frozen board. */
function installErrorBoundary(game) {
  window.addEventListener('error', (event) => { console.error(event.error || event.message); game.crash(event.error || event.message); });
  window.addEventListener('unhandledrejection', (event) => { console.error(event.reason); game.crash(event.reason); });
}

function boot() {
  const storage = createStorage();
  const game = new Game({ storage });
  installErrorBoundary(game);
  installInputMode();

  const canvas = document.getElementById('gameCanvas');
  const view = new View(canvas, document.getElementById('stage'));       // the board is fitted into the stage
  const renderer = new Renderer({ canvas, view, game, storage });
  renderer.fx = new Fx({ game, view });
  view.onChange = () => renderer.resize();
  const sound = new Sound({ game, storage });
  const haptics = new Haptics({ game, storage });
  const loop = startLoop({ game, renderer, sound });
  const ui = new UI({ game, storage, renderer, loop, sound, haptics, debug });
  installKeyboard({ game, ui });
  installPointer({ canvas, view, game });
  installAutoPause(game);
  game.enterTitle();

  if (debug) import('./debug.js').then((m) => m.install({ game, view, renderer, ui, storage, loop, sound, haptics }));
}

boot();
