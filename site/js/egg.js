/* The splash, and the one extra board it leads to. The splash is built on demand, styled by app.css (the security
   policy allows no inline styles) and removed once it has faded. The board is plain data plus a builder shaped like
   level.js's buildLevel, so the game runs it like any other level. */
import { CELLS_PER_UNIT as S, FRAME_UNITS } from './config.js';
import { BORDER } from './grid.js';
import { makePatrol, awayFromAxes } from './physics.js';

export const SPLASH_MS = 3000;
export const FADE_MS = 460;
export const TAPS = 5;
export const TAP_WINDOW_MS = 3000;

/* Hand-placed and the same for everyone: a pinwheel of four bars around the middle and a block in each corner, with four
   patrols a little quicker than level 3's. Every corridor is at least 6 units wide (a patrol is 2.7 across). */
export const EXTRA = Object.freeze({
  target: 60,
  speed: 20,
  obstacles: Object.freeze([
    { x: 44, y: 22, w: 18, h: 4 }, { x: 74, y: 24, w: 4, h: 16 }, { x: 58, y: 46, w: 18, h: 4 }, { x: 42, y: 32, w: 4, h: 16 },
    { x: 12, y: 10, w: 8, h: 5 }, { x: 100, y: 10, w: 8, h: 5 }, { x: 12, y: 57, w: 8, h: 5 }, { x: 100, y: 57, w: 8, h: 5 },
  ]),
  patrols: Object.freeze([[30, 18, 35], [90, 54, 215], [90, 18, 145], [30, 54, 325]]),        // x, y, heading in degrees
  /* Its own colours on the board: the field, the ink of claimed ground and the rim of open ground beside a wall. */
  look: Object.freeze({ field: '#3b1670', ink: [12, 6, 26], dot: [46, 24, 74], glow: [255, 123, 240] }),
});

/* The board, built the way buildLevel builds one: the frame, the blocks, then the patrols. */
export function buildExtraLevel(grid) {
  grid.clear();
  grid.frame(FRAME_UNITS * S);
  const obstacles = EXTRA.obstacles.map((block) => ({ ...block }));
  for (const { x, y, w, h } of obstacles) grid.fillRect(x * S, y * S, (x + w) * S, (y + h) * S, BORDER);
  const initialPlayable = grid.countField();
  const patrols = EXTRA.patrols.map(([x, y, degrees]) => {
    const angle = (degrees * Math.PI) / 180;
    const heading = awayFromAxes(Math.cos(angle), Math.sin(angle));
    return makePatrol(x, y, heading.x * EXTRA.speed, heading.y * EXTRA.speed);
  });
  const info = { level: 1, patrols: patrols.length, speed: EXTRA.speed, target: EXTRA.target, obstacles: obstacles.length, tracers: 0, powerups: false };
  return { number: 1, info, obstacles, initialPlayable, patrols, cleared: 0, routes: [] };
}

const HEART =
  'M12 20.7c-.38 0-.75-.14-1.04-.4C6.45 16.3 3.2 13.4 3.2 9.75 3.2 7.1 5.3 5 7.85 5c1.66 0 3.2.88 4.15 2.28C12.95 5.88 14.5 5 16.15 5 18.7 5 20.8 7.1 20.8 9.75c0 3.65-3.25 6.55-7.76 10.55-.29.26-.66.4-1.04.4z';

function element(tag, className, attributes = {}, namespace = null) {
  const node = namespace ? document.createElementNS(namespace, tag) : document.createElement(tag);
  if (className) node.setAttribute('class', className);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  return node;
}

/* Built node by node: the page's security policy is strict, and no script here turns a string into markup. */
function buildSplash() {
  const SVG = 'http://www.w3.org/2000/svg';
  const heart = element('svg', 'egg-heart', { width: 12, height: 12, viewBox: '0 0 24 24', 'aria-hidden': 'true' }, SVG);
  heart.append(element('path', '', { d: HEART }, SVG));
  const name = element('p', 'egg-name', { translate: 'no' });
  name.textContent = 'Jay';
  const sub = element('p', 'egg-sub');
  sub.append(heart, 'indie dev');
  const meta = element('div', 'egg-meta');
  meta.append(name, sub);
  const key = element('div', 'egg-key', { 'aria-hidden': 'true' });
  key.textContent = '~/';
  const stage = element('div', 'egg-stage');
  stage.append(key, meta);
  const splash = element('div', 'egg', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Built by Jay' });
  splash.append(stage);
  return splash;
}

/**
 * @param {object} options
 * @param {Element}  options.brand    the element whose taps are counted
 * @param {Element}  options.page     the app's root: made inert while the splash shows, so nothing behind it can be reached
 * @param {Function} options.canOpen  false while the splash must not appear
 * @param {Function} options.onEnter  called as the splash starts to fade
 */
export function createEgg({ brand, page, canOpen = () => true, onEnter }) {
  let node = null;
  let timer = 0;
  let taps = [];

  function close() {
    if (!node) return;
    const closing = node;
    node = null;
    window.clearTimeout(timer);
    page.inert = false;
    closing.classList.add('out');
    window.setTimeout(() => closing.remove(), FADE_MS);
    onEnter();
  }

  function show() {
    if (node || !canOpen()) return false;
    node = buildSplash();
    node.addEventListener('click', close);
    document.body.append(node);
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    page.inert = true;
    timer = window.setTimeout(close, SPLASH_MS);
    return true;
  }

  brand.addEventListener('click', () => {
    const now = Date.now();
    taps = taps.filter((at) => now - at <= TAP_WINDOW_MS);
    taps.push(now);
    if (taps.length >= TAPS) {
      taps = [];
      show();
    }
  });

  /* In the capture phase and swallowed: the game's own Escape (pause) must not see the key that closed the splash. */
  document.addEventListener(
    'keydown',
    (event) => {
      if (!node) return;
      event.stopImmediatePropagation();
      if (event.key === 'Escape') close();
    },
    true,
  );

  return {
    show,
    get isOpen() {
      return node !== null;
    },
  };
}

