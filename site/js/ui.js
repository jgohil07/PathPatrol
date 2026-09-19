/* The DOM side of the game: HUD, overlays, toasts and buttons.
   It listens to the game and changes game state only through the game's own methods. */
import { START_LIVES } from './config.js';
import { PHASE } from './game.js';

const $ = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, '0');

export class UI {
  constructor({ game, storage, renderer, debug = false }) {
    this.game = game;
    this.storage = storage;
    this.renderer = renderer;
    this.debug = debug;
    this._toastTimer = 0;
    this._resetTimer = 0;
    this._resetArmed = false;
    this._livesKey = '';
    this._lastHint = -Infinity;
    this.el = {
      start: $('startButton'), again: $('againButton'), reload: $('reloadButton'),
      pause: $('pauseButton'), resume: $('resumeButton'), restart: $('restartButton'),
      sound: $('soundButton'), flight: $('flightButton'), drive: $('driveButton'), reset: $('resetStatsButton'),
      startOverlay: $('startOverlay'), pauseOverlay: $('pauseOverlay'), endOverlay: $('endOverlay'), crashOverlay: $('crashOverlay'),
      pauseEyebrow: $('pauseEyebrow'), pauseTitle: $('pauseTitle'), endSummary: $('endSummary'), crashDetail: $('crashDetail'),
      level: $('levelLabel'), lives: $('lives'), target: $('targetLabel'), area: $('areaLabel'),
      progress: $('progressFill'), marker: $('targetMarker'), runners: $('runnerLabel'),
      toast: $('toast'), bestClear: $('bestClear'), bestLevel: $('bestLevel'), runs: $('runsPlayed'), wins: $('levelsWon'),
      storageNote: $('storageNote'),
    };
    this._wire();
    this.renderTheme();
    this.renderSound();
    this.renderStats();
    this.renderHud();
    this.renderPhase();
  }

  _wire() {
    const { game, el } = this;
    el.start.addEventListener('click', () => game.newRun());
    el.again.addEventListener('click', () => game.newRun());
    el.reload.addEventListener('click', () => location.reload());
    el.pause.addEventListener('click', () => game.togglePause());
    el.resume.addEventListener('click', () => game.resume());
    el.restart.addEventListener('click', () => game.restartLevel());
    el.sound.addEventListener('click', () => this.toggleSound());
    el.flight.addEventListener('click', () => this.setTheme('flight'));
    el.drive.addEventListener('click', () => this.setTheme('drive'));
    el.reset.addEventListener('click', () => this.pressReset());

    game.on('toast', ({ text, ms }) => this.toast(text, ms));
    game.on('hud', () => { this.renderHud(); this.renderStats(); });
    game.on('phase', () => this.renderPhase());
    game.on('countdown', () => this.renderPhase());
    game.on('over', (report) => this.renderOver(report));
    game.on('crash', ({ error }) => this.renderCrash(error));
    game.on('route', (event) => { if (event.type === 'edge-hint') this.hintEdge(); });
  }

  /* --- actions shared by buttons and keys ---------------------------------------------------- */

  toggleSound() {
    const on = !this.storage.settings.sound;
    this.storage.updateSettings({ sound: on });
    this.renderSound();
    this.toast(on ? 'Sound on' : 'Sound off', 800);
  }

  setTheme(theme) {
    if (theme === this.storage.settings.theme) return;
    this.storage.updateSettings({ theme });
    this.renderer.setTheme(theme);
    this.renderTheme();
    this.renderHud();
    this.toast(theme === 'flight' ? 'Flight visuals enabled' : 'Drive visuals enabled', 900);
  }

  toggleTheme() { this.setTheme(this.storage.settings.theme === 'flight' ? 'drive' : 'flight'); }

  /* Two presses within three seconds: a native confirm() dialog is jarring and blocks the page. */
  pressReset() {
    if (!this._resetArmed) {
      this._resetArmed = true;
      this.el.reset.textContent = 'Tap again to reset';
      this._resetTimer = setTimeout(() => this._disarmReset(), 3000);
      return;
    }
    this._disarmReset();
    this.storage.resetRecords();
    this.renderStats();
    this.toast('Local records reset', 1000);
  }

  _disarmReset() {
    clearTimeout(this._resetTimer);
    this._resetArmed = false;
    this.el.reset.textContent = 'Reset local records';
  }

  /* A touch that starts in the middle of the field draws nothing; say why, but not on every attempt. */
  hintEdge() {
    if (performance.now() - this._lastHint < 4000) return;
    this._lastHint = performance.now();
    this.toast('Start on an edge or on claimed ground', 1600);
  }

  toast(text, ms = 1200) {
    clearTimeout(this._toastTimer);
    this.el.toast.textContent = text;
    this.el.toast.classList.add('visible');
    this._toastTimer = setTimeout(() => this.el.toast.classList.remove('visible'), ms);
  }

  /* --- rendering ----------------------------------------------------------------------------- */

  renderHud() {
    const { el, game } = this;
    const h = game.hud();
    el.level.textContent = pad2(h.level);
    el.target.textContent = `${h.target}%`;
    el.area.textContent = `${h.cleared.toFixed(1)}%`;
    el.progress.style.width = `${Math.min(100, h.cleared)}%`;
    el.marker.style.left = `${h.target}%`;
    const word = this.storage.settings.theme === 'flight' ? 'PLANE' : 'CAR';
    el.runners.textContent = `${h.patrols} ${word}${h.patrols === 1 ? '' : 'S'}`;

    const total = Math.max(START_LIVES, h.lives);
    const key = `${total}:${h.lives}`;
    if (key !== this._livesKey) {
      this._livesKey = key;
      const hearts = Array.from({ length: total }, (_, i) => {
        const heart = document.createElement('i');
        heart.className = i < h.lives ? 'life' : 'life lost';
        return heart;
      });
      el.lives.replaceChildren(...hearts);
      el.lives.setAttribute('aria-label', `${h.lives} ${h.lives === 1 ? 'life' : 'lives'}`);
    }
  }

  renderStats() {
    const { el, storage } = this;
    const r = storage.records;
    el.bestClear.textContent = `${r.bestClear.toFixed(1)}%`;
    el.bestLevel.textContent = r.bestLevel ? pad2(r.bestLevel) : '—';
    el.runs.textContent = String(r.runs);
    el.wins.textContent = String(r.wins);
    el.storageNote.textContent = storage.persistent ? 'All progress stays on this device.' : "Storage is blocked here, so progress won't be saved.";
  }

  renderTheme() {
    const theme = this.storage.settings.theme;
    for (const [name, button] of [['flight', this.el.flight], ['drive', this.el.drive]]) {
      button.classList.toggle('active', theme === name);
      button.setAttribute('aria-pressed', String(theme === name));
    }
  }

  renderSound() { this.el.sound.setAttribute('aria-pressed', String(this.storage.settings.sound)); }

  renderPhase() {
    const { el, game } = this;
    const phase = game.phase;
    const paused = phase === PHASE.PAUSED || phase === PHASE.COUNTDOWN;
    el.startOverlay.classList.toggle('hidden', phase !== PHASE.TITLE);
    el.endOverlay.classList.toggle('hidden', phase !== PHASE.OVER);
    el.crashOverlay.classList.toggle('hidden', phase !== PHASE.CRASHED);
    el.pauseOverlay.classList.toggle('hidden', !paused);

    if (phase === PHASE.COUNTDOWN) {
      el.pauseEyebrow.textContent = 'Resuming';
      el.pauseTitle.textContent = String(Math.max(1, Math.ceil(game.countdown)));
    } else {
      el.pauseEyebrow.textContent = 'Run paused';
      el.pauseTitle.textContent = game.pauseReason === 'auto' ? 'Paused while you were away.' : 'Take a breath.';
    }

    this._setPauseLabel(paused ? 'Resume' : 'Pause');
    const live = phase === PHASE.PLAYING || phase === PHASE.CLEAR;
    el.pause.disabled = !(live || paused);
    el.restart.disabled = !(phase === PHASE.PLAYING || paused) || (game.run && game.run.mode === 'daily');

    if (phase === PHASE.PAUSED) el.resume.focus({ preventScroll: true });
    if (phase === PHASE.OVER) el.again.focus({ preventScroll: true });
  }

  _setPauseLabel(text) {
    const key = document.createElement('kbd');
    key.textContent = 'P';
    this.el.pause.textContent = `${text} `;
    this.el.pause.append(key);
  }

  renderOver(report) {
    const best = this.storage.records.bestClear;
    this.el.endSummary.textContent = `You reached level ${pad2(report.level)} with ${report.cleared.toFixed(1)}% cleared. Best clear: ${best.toFixed(1)}%. Start fresh and find a cleaner line.`;
  }

  /* The details are for developers (?debug=1); a player only sees "Something broke". WebKit's stack
     omits the message, so build it explicitly. */
  renderCrash(error) {
    let text = '';
    if (this.debug) {
      const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
      const stack = error && error.stack ? String(error.stack) : '';
      text = stack.startsWith(message) ? stack : `${message}\n${stack}`.trim();
    }
    this.el.crashDetail.textContent = text;
  }
}
