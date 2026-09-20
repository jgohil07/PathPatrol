# Path Patrol

A minimalist territory game that runs entirely in your browser. Draw a route across the board with a finger, a mouse or the
keyboard; when it lands on safe ground, the side without patrols is yours. Claim enough of the board to clear the level. No
sign-up, no account, no ads, no tracking, no server. Everything, including your progress, stays on your device.

**Live site:** https://jgohil07.github.io/PathPatrol/

## What's in it

**Play** — The route appears under your finger the moment you move: nothing waits for you to let go. Patrols bounce off walls
of any angle and off each other; each level adds patrols, speed, obstacles and, from level 4, edge tracers that crawl the
border and chase slowly drawn routes. Combos, close calls, an extra life every 25,000 points, and three power-ups you take by
drawing through them: freeze, shield and slow. Flight (planes) and Drive (cars) looks.

**Come back to it** — Your run is saved as you play and offered as *Resume run*. Records (best score, best clear, levels won,
your daily streak) stay in your browser. Installable, and playable offline after the first visit.

**Share it** — A **daily** board, the same for everyone on the same date: three lives, no restarts, only your first run of the
day counts, and there is a streak. Share the result with the system share sheet, or copy it.

**Anywhere** — Phones (the board turns upright in portrait), tablets and desktops; touch, mouse and keyboard; a reduced-motion
mode; sound and vibration you can switch off.

## Why it's different

- **No waiting.** The first prototype of this game aimed a straight line and grew it after you let go, a wait of about a
  second. Here the route is laid cell by cell inside the pointer event itself, so what you draw is what is on the board, and a
  patrol that touches it costs a life at once.
- **Physics you can trust.** A fixed 1/120 s step with sub-steps, so motion is the same at 60, 90, 120 and 144 Hz and nothing
  tunnels through a wall. Bounces follow the true direction of the wall, staircase edges included; patrols collide with each
  other; speed never drifts.
- **One board for everyone.** The daily board is generated from the date alone, with separate random streams for layout and
  for events, so nothing a player does can change a later level, and two devices with different screens see the same game.
- **Tested like a product.** About a thousand test runs (around 500 tests on each of Chromium and WebKit) guard every change:
  real touch input over the DevTools protocol, a bot that plays thousands of steps checking invariants, a layout check at eleven screen sizes, and
  the offline and update flow. The tests were themselves attacked with deliberate bugs to prove they can fail.

## Technical notes

- **No build step and no dependencies.** Plain HTML, CSS and ES modules under `site/`; what is in the repository is what the
  browser runs. The two fonts (DM Mono, Space Grotesk) are self-hosted, so nothing loads from anywhere else. The suite runs in CI on Chromium (Chrome, Edge) and WebKit (Safari), and it also passes on Firefox when run locally.
- **Small modules.** `grid` (cells, flood fill), `level` (seeded layouts), `physics`, `route` (the input-agnostic route
  engine), `tracers`, `powerups`, `game` (state machine and a game-clock scheduler), `input` and `pilot` (pointer and
  keyboard), `view` and `render` (fitting, DPR, the portrait rotation, a cached static layer), `snapshot`, `daily`, `pwa`.
- **Strict Content-Security-Policy** (a meta tag, as GitHub Pages sends no headers): scripts, styles, images, fonts,
  connections, the manifest and the worker may all only come from the site itself, and there is no inline script or style.
- **Offline and updates.** A service worker precaches the whole app under a name made from its version and a hash of its files,
  serves it cache-first, and never swaps versions under a running game: a new version installs completely, waits, and takes over
  when you tap *Update ready* or the next time the game opens on its title screen. `tools/make_sw.py` writes the file list and
  hash; a test fails if you forget to run it.
- **Storage** is one versioned, sanitised blob; a saved run is validated strictly before it is offered; every read and write
  tolerates storage being blocked.
- **Deploys are gated.** GitHub Actions runs the whole suite on Chromium and WebKit and publishes `site/` to GitHub Pages only
  when it passes.

## Running locally

```sh
python3 tools/serve.py        # then open http://127.0.0.1:8000/
```

Opening `index.html` as a `file://` URL will not work: ES modules and the service worker need a real origin. Add `?debug=1`
to the address to load the test hooks (`window.__pp`) and skip the service worker.

Tests (Python, Playwright, pytest):

```sh
make setup      # once: a virtual environment, pinned Playwright and pytest, the WebKit build
make test       # the whole suite on Chrome and WebKit
make sw         # after ANY change under site/: rewrites the file list and hash in site/sw.js
```

## Keyboard

<kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> or the arrow keys draw · <kbd>Backspace</kbd> cancels the route ·
<kbd>P</kbd> / <kbd>Esc</kbd> pause · <kbd>R</kbd> <kbd>R</kbd> restart the level · <kbd>M</kbd> mute · <kbd>T</kbd> switch
Flight / Drive · <kbd>H</kbd> / <kbd>?</kbd> help · <kbd>Space</kbd> / <kbd>Enter</kbd> start, resume or go on ·
<kbd>Tab</kbd> moves between buttons (Safari: <kbd>Option</kbd>+<kbd>Tab</kbd>).

## Disclaimer

Your progress is stored in your browser's local storage. Clearing site data, or playing in a private window, will clear it.
Nothing is backed up anywhere, because nothing is uploaded anywhere. Path Patrol is an independent game in the spirit of the
classic territory games (Qix, JezzBall, the feature-phone "Space War"); it is not affiliated with any of them.

The fonts are licensed under the SIL Open Font License 1.1 (see `site/assets/fonts/`). The code is MIT licensed (see `LICENSE`).

---

From indie dev Jay
