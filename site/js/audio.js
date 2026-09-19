/* Sound: a small Web Audio synthesiser. No sample files, so nothing to download and nothing to cache.

   Rules that exist because of how phones behave:
   - The AudioContext is created only inside a user gesture (pointerdown, touchend, keydown, click) and only when
     sound is on. Browsers refuse to start audio before a gesture, and a context created earlier stays suspended.
   - It falls back to webkitAudioContext (older Safari), and it is resumed whenever it is not running: iOS puts it in
     "interrupted" after a call or an app switch and only a later gesture brings it back.
   - Muting silences everything at once, including the drawing hum, and creates nothing if no context exists yet.

   Only oscillators and gain nodes are used, which keeps every sound easy to describe and to check: a tone is a
   frequency, a length, a shape and a loudness. The drawing hum is driven by polling the route's state every frame
   (update), not by events, so a missed event can never leave it stuck on. */

const MASTER = 0.35;                    // overall loudness; every voice is well under 1 so they can overlap
const semitones = (n) => 2 ** (n / 12);

/* Root notes for the capture chime, by how much of the board the capture claimed. */
const CHIME = [
  { upTo: 2, notes: [0], gain: 0.10 },                 // a small capture: one note
  { upTo: 10, notes: [0, 4], gain: 0.13 },             // a medium one: a third
  { upTo: 25, notes: [0, 4, 7], gain: 0.16 },          // a large one: a triad
  { upTo: Infinity, notes: [0, 4, 7, 12], gain: 0.19 },
];
const C5 = 523.25;

export class Sound {
  constructor({ game, storage }) {
    this.game = game;
    this.storage = storage;
    this.ctx = null;
    this.master = null;
    this.hum = null;                    // { osc, gain } while a route is being drawn
    this._wireGame();
    this._wireGestures();
  }

  get enabled() { return this.storage.settings.sound; }
  get running() { return !!this.ctx && this.ctx.state === 'running'; }

  /* --- the context ------------------------------------------------------------------------------- */

  _wireGestures() {
    const gesture = () => this.unlock();
    for (const type of ['pointerdown', 'touchend', 'keydown', 'click']) window.addEventListener(type, gesture, { capture: true, passive: true });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this._resume(); });
  }

  /* Called from inside a user gesture: makes the context if there is none, and wakes it if it is asleep. */
  unlock() {
    if (!this.enabled) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    if (!this.ctx) {
      try { this.ctx = new Ctx(); } catch { return; }
      this.master = this.ctx.createGain();
      this.master.gain.value = MASTER;
      this.master.connect(this.ctx.destination);
    }
    this._resume();
  }

  _resume() {
    const ctx = this.ctx;
    if (!ctx || ctx.state === 'running' || typeof ctx.resume !== 'function') return;
    const result = ctx.resume();                          // 'suspended' at first, 'interrupted' on iOS after a call or app switch
    if (result && typeof result.catch === 'function') result.catch(() => {});
  }

  /* Sound was switched on or off (the toggle click is itself a gesture): follow it. */
  sync() {
    if (!this.enabled) this._stopHum();
    else this.unlock();
  }

  /* --- voices ------------------------------------------------------------------------------------- */

  /* One note: `freq` Hz for `dur` seconds, starting `at` seconds from now, optionally gliding to `glide` Hz. */
  _tone({ freq, dur = 0.12, gain = 0.12, type = 'sine', at = 0, glide = 0 }) {
    if (!this.enabled || !this.running) return;
    const ctx = this.ctx;
    const t0 = ctx.currentTime + at;
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (glide) osc.frequency.exponentialRampToValueAtTime(glide, t0 + dur);
    amp.gain.setValueAtTime(0.0001, t0);
    amp.gain.exponentialRampToValueAtTime(gain, t0 + Math.min(0.012, dur / 3));       // a click-free attack...
    amp.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);                          // ...and release
    osc.connect(amp);
    amp.connect(this.master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.03);
  }

  tick() { this._tone({ freq: 920, dur: 0.035, gain: 0.05, type: 'triangle' }); }
  ping() { this._tone({ freq: 1480, dur: 0.07, gain: 0.08, type: 'sine' }); }
  lifted() { this._tone({ freq: 330, dur: 0.1, gain: 0.07, type: 'triangle', glide: 210 }); }
  pickup() { this._tone({ freq: 700, dur: 0.09, gain: 0.1, glide: 1250 }); }

  /* Lost a life: a low, short buzz. */
  buzz() {
    this._tone({ freq: 118, dur: 0.3, gain: 0.16, type: 'sawtooth', glide: 66 });
    this._tone({ freq: 59, dur: 0.3, gain: 0.1, type: 'square', glide: 40 });
  }

  /* A capture: more notes the more it claims, a step higher for each notch of combo. */
  chime(gained, combo = 1) {
    const step = CHIME.find((c) => gained < c.upTo);
    const shift = semitones(Math.round((combo - 1) * 4));                              // up to +8 semitones at x3
    step.notes.forEach((n, i) => this._tone({ freq: C5 * semitones(n) * shift, dur: 0.22, gain: step.gain, at: i * 0.07 }));
  }

  extraLife() {
    this._tone({ freq: 587, dur: 0.14, gain: 0.13 });
    this._tone({ freq: 880, dur: 0.24, gain: 0.14, at: 0.12 });
  }

  clear() { [0, 4, 7, 12, 16].forEach((n, i) => this._tone({ freq: C5 * semitones(n), dur: 0.2, gain: 0.14, at: i * 0.09 })); }
  over() { [7, 4, 0].forEach((n, i) => this._tone({ freq: (C5 / 2) * semitones(n), dur: 0.28, gain: 0.13, type: 'triangle', at: i * 0.2 })); }

  /* --- the drawing hum ---------------------------------------------------------------------------- */

  /* Every frame: hum while a route is being drawn, its pitch rising with the route's length. */
  update() {
    const route = this.game.route;
    if (this.enabled && this.running && route.mode === 'drawing') {                     // a pause erases the route, so this is false while paused
      if (!this.hum) this._startHum();
      const pitch = 150 + Math.min(route.cells.length, 240) * 2.2;                     // 150 Hz for a new route, ~680 Hz for a very long one
      this.hum.osc.frequency.setTargetAtTime(pitch, this.ctx.currentTime, 0.05);
    } else {
      this._stopHum();
    }
  }

  _startHum() {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(150, ctx.currentTime);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.045, ctx.currentTime + 0.08);
    osc.connect(gain);
    gain.connect(this.master);
    osc.start();
    this.hum = { osc, gain };
  }

  _stopHum() {
    if (!this.hum) return;
    const { osc, gain } = this.hum;
    this.hum = null;
    const ctx = this.ctx;
    try {
      gain.gain.cancelScheduledValues(ctx.currentTime);
      gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.06);
      osc.stop(ctx.currentTime + 0.08);
    } catch { /* already stopped */ }
  }

  /* --- what the game says -------------------------------------------------------------------------- */

  _wireGame() {
    const { game } = this;
    game.on('route', (event) => {
      if (event.type === 'armed') this.tick();
      else if (event.type === 'closecall') this.ping();
      else if (event.type === 'hit') this.buzz();
      else if (event.type === 'cancel' && (event.reason === 'lift' || event.reason === 'cancel')) this.lifted();
    });
    game.on('capture', (result) => this.chime(result.gained, result.combo));
    game.on('extraLife', () => this.extraLife());
    game.on('clear', () => this.clear());
    game.on('over', () => this.over());
  }
}
