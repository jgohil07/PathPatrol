/* The DOM side of the game: HUD, overlays, dialogs, settings and the console line.
   It listens to the game and changes game state only through the game's own methods.

   Screen-reader output goes through announce(): messages raised in the same tick are joined into one
   sentence, because a polite live region rewritten twice in a row reads only the last write. */
import { START_LIVES, APP_VERSION, levelInfo } from './config.js';
import { PHASE } from './game.js';

const IDS = [
  'app', 'startButton', 'resumeRunButton', 'savedLine', 'againButton', 'reloadButton', 'pauseButton', 'resumeButton', 'restartButton',
  'pauseRestartButton', 'soundButton', 'helpButton', 'settingsButton',
  'levelLabel', 'lives', 'areaLabel', 'targetLabel', 'progressFill', 'targetMarker', 'runnerLabel', 'scoreLabel', 'comboLabel', 'toast',
  'clearOverlay', 'clearEyebrow', 'clearTotal', 'tally', 'nextLabel', 'clearNote', 'tutorialButton', 'bestScore',
  'titleRecords', 'versionLabel', 'versionLine', 'pauseEyebrow', 'pauseTitle', 'receipt', 'endSummary',
  'crashDetail', 'fpsMeter', 'storageNote', 'announcer',
  'settingsDialog', 'helpDialog', 'soundSwitch', 'flightButton', 'driveButton', 'fpsSwitch',
  'bestClear', 'bestLevel', 'runsPlayed', 'levelsWon', 'resetStatsButton',
];

const RESET_WINDOW_MS = 3000;       // the second tap on "Reset local records" must land within this
const HINT_GAP_MS = 4000;           // "start from an edge" is said at most this often
const NBSP = '\u00a0';          // written as an escape: a literal no-break space is invisible and easy to "fix" by accident

const pad2 = (n) => String(n).padStart(2, '0');
const plural = (n, one, many) => (n === 1 ? one : many);
const number = (n) => Math.round(n).toLocaleString('en-US');       // one format everywhere, whatever the browser's locale

/* A two-column list of rows: [name, value] or [name, value, flag]. */
function fillRows(list, rows) {
  list.replaceChildren(...rows.flatMap(([name, value, flag]) => {
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = name;
    if (flag) {
      const tag = document.createElement('b');
      tag.className = 'flag';
      tag.textContent = flag;
      dd.append(tag);
    }
    dd.append(value);
    return [dt, dd];
  }));
}

function byId(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`index.html has no #${id}`);      // a renamed id should fail loudly at boot
  return node;
}

export class UI {
  constructor({ game, storage, renderer, loop = null, debug = false }) {
    this.game = game;
    this.storage = storage;
    this.renderer = renderer;
    this.loop = loop;
    this.debug = debug;
    this.el = Object.fromEntries(IDS.map((id) => [id, byId(id)]));
    this.motionButtons = [...this.el.settingsDialog.querySelectorAll('[data-motion]')];
    this._reduceQuery = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
    this._toastTimer = 0;
    this._coaching = false;                  // the tutorial's message holds the console line
    this._resetTimer = 0;
    this._resetArmed = false;
    this._livesKey = '';
    this._lastHint = -Infinity;
    this._spoken = [];
    this._speakQueued = false;
    this._lastSpoken = '';
    this._flip = false;
    this._wire();
    this.el.versionLabel.textContent = `v${APP_VERSION}`;
    this.el.versionLine.textContent = `v${APP_VERSION}`;
    this.renderTheme();
    this.renderSound();
    this.renderMotion();
    this.renderFps();
    this.renderStats();
    this.renderHud();
    this.renderSaved();
    this.renderPhase();
  }

  _wire() {
    const { game, el } = this;
    const click = (node, handler) => node.addEventListener('click', handler);
    click(el.startButton, () => this.startRun());
    click(el.resumeRunButton, () => game.resumeRun());
    click(el.againButton, () => this.startRun());
    click(el.reloadButton, () => location.reload());
    click(el.pauseButton, () => (game.tutorial.active && game.phase === PHASE.PLAYING ? game.skipTutorial() : game.togglePause()));
    click(el.resumeButton, () => game.resume());
    click(el.restartButton, () => game.restartLevel());
    click(el.pauseRestartButton, () => game.restartLevel());
    click(el.soundButton, () => this.toggleSound());
    click(el.soundSwitch, () => this.toggleSound());
    click(el.helpButton, () => this.openHelp());
    click(el.tutorialButton, () => { el.helpDialog.close(); game.startTutorial({ origin: 'help' }); });
    click(el.settingsButton, () => this.openSettings());
    click(el.flightButton, () => this.setTheme('flight'));
    click(el.driveButton, () => this.setTheme('drive'));
    for (const button of this.motionButtons) click(button, () => this.setMotion(button.dataset.motion));
    click(el.fpsSwitch, () => this.setShowFps(!this.storage.settings.showFps));
    click(el.resetStatsButton, () => this.pressReset());
    click(el.clearOverlay, () => game.skipClear());               // the Next button is inside it, so its click lands here too

    for (const dialog of [el.settingsDialog, el.helpDialog]) {
      dialog.addEventListener('click', (event) => {          // a click on the backdrop lands on the dialog itself
        if (event.target !== dialog) return;
        const r = dialog.getBoundingClientRect();
        const inside = event.clientX >= r.left && event.clientX <= r.right && event.clientY >= r.top && event.clientY <= r.bottom;
        if (!inside) dialog.close();
      });
      dialog.addEventListener('close', () => this._dialogClosed());
    }
    if (this._reduceQuery && typeof this._reduceQuery.addEventListener === 'function') {
      this._reduceQuery.addEventListener('change', () => this.renderMotion());
    }

    game.on('toast', ({ text, ms }) => this.toast(text, ms));
    game.on('hud', () => { this.renderHud(); this.renderStats(); });
    game.on('saved', () => this.renderSaved());
    game.on('tutorial', (event) => { this.renderCoach(event); this.renderPhase(); });
    game.on('phase', () => this.renderPhase());
    game.on('countdown', () => this.renderPhase());
    game.on('over', (report) => this.renderOver(report));
    game.on('crash', ({ error }) => this.renderCrash(error));
    game.on('route', (event) => { if (event.type === 'edge-hint') this.hintEdge(); });
    game.on('levelStart', ({ lives }) => this.announce(`${lives} ${plural(lives, 'life', 'lives')}`));
    game.on('life', ({ lives }) => this.announce(`${lives} ${plural(lives, 'life', 'lives')} left`));
    game.on('capture', ({ percent, points }) => this.announce(`${percent.toFixed(1)} percent cleared${points ? `, ${number(points)} points` : ''}`));
    game.on('clear', (tally) => this.renderTally(tally));
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

  setMotion(motion) {
    this.storage.updateSettings({ motion });
    this.renderMotion();
  }

  setShowFps(on) {
    this.storage.updateSettings({ showFps: on });
    this.renderFps();
  }

  /* Two presses within three seconds: a native confirm() dialog is jarring and blocks the page. */
  pressReset() {
    if (!this._resetArmed) {
      this._resetArmed = true;
      this.el.resetStatsButton.textContent = 'Tap again to reset';
      this.announce('Tap again to reset your records');
      this._resetTimer = setTimeout(() => this._disarmReset(), RESET_WINDOW_MS);
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
    this.el.resetStatsButton.textContent = 'Reset local records';
  }

  /* Start run and New run: the very first one is the tutorial. */
  startRun() {
    if (this.storage.settings.tutorialDone) this.game.newRun();
    else this.game.startTutorial({ origin: 'start' });
  }

  /* The tutorial's coach holds the console line (the one place that never covers the board) until it ends. */
  renderCoach(event) {
    const { el } = this;
    this._coaching = event.active;
    clearTimeout(this._toastTimer);
    if (!event.active) { el.toast.classList.remove('visible'); return; }
    el.toast.textContent = event.text;
    el.toast.classList.add('visible');
    this.announce(event.text);
  }

  /* Space or Enter with nothing focused: the obvious next step for the current screen. */
  confirm() {
    switch (this.game.phase) {
      case PHASE.TITLE:
      case PHASE.OVER:
        this.startRun();
        return true;
      case PHASE.PAUSED:
      case PHASE.COUNTDOWN:
        this.game.resume();
        return true;
      case PHASE.CLEAR:
        return this.game.skipClear();
      default:
        return false;
    }
  }

  /* A touch that starts in the middle of the field draws nothing; say why, but not on every attempt. */
  hintEdge() {
    if (performance.now() - this._lastHint < HINT_GAP_MS) return;
    this._lastHint = performance.now();
    this.toast('Start on an edge or on claimed ground', 1600);
  }

  /* One line of console text under the HUD. It sits outside the board so it never covers a place a
     route starts, and it is spoken through announce() rather than being a live region itself. */
  toast(text, ms = 1200) {
    if (this._coaching) return;
    clearTimeout(this._toastTimer);
    this.el.toast.textContent = text;
    this.el.toast.classList.add('visible');
    this._toastTimer = setTimeout(() => this.el.toast.classList.remove('visible'), ms);
    this.announce(text);
  }

  announce(text) {
    this._spoken.push(text);
    if (this._speakQueued) return;
    this._speakQueued = true;
    queueMicrotask(() => {
      this._speakQueued = false;
      const message = this._spoken.join('. ');
      this._spoken.length = 0;
      this._flip = message === this._lastSpoken ? !this._flip : false;     // identical text is not re-read...
      this._lastSpoken = message;
      this.el.announcer.textContent = this._flip ? message + NBSP : message;     // ...unless it changes
    });
  }

  /* --- dialogs ------------------------------------------------------------------------------- */

  isModalOpen() { return this.el.settingsDialog.open || this.el.helpDialog.open; }

  openSettings() { this._openDialog(this.el.settingsDialog); }
  openHelp() { this._openDialog(this.el.helpDialog); }

  /* Opening a dialog pauses a live game, and the dialog owns the keyboard until it closes. The dialog is
     opened first: on close the browser returns focus to whatever had it when the dialog opened, and pausing
     first would move focus to the Resume button in between, so the player would land there instead of on the
     control they used to open the dialog. */
  _openDialog(dialog) {
    if (this.isModalOpen()) return;
    this.renderStats();
    this.renderMotion();
    dialog.showModal();
    const { phase } = this.game;
    if (phase === PHASE.PLAYING || phase === PHASE.CLEAR) this.game.pause('manual');
  }

  _dialogClosed() { this._disarmReset(); }

  /* --- rendering ----------------------------------------------------------------------------- */

  renderHud() {
    const { el, game } = this;
    const h = game.hud();
    el.levelLabel.textContent = pad2(h.level);
    el.targetLabel.textContent = `${h.target}%`;
    el.areaLabel.textContent = `${h.cleared.toFixed(1)}%`;
    el.progressFill.style.width = `${Math.min(100, h.cleared)}%`;
    el.targetMarker.style.left = `${h.target}%`;
    const word = this.storage.settings.theme === 'flight' ? 'PLANE' : 'CAR';
    el.runnerLabel.textContent = `${h.patrols} ${word}${h.patrols === 1 ? '' : 'S'}`;
    el.scoreLabel.textContent = number(h.score);
    el.comboLabel.textContent = `x${h.combo.toFixed(2)}`;
    el.comboLabel.classList.toggle('on', h.combo > 1);

    const total = Math.max(START_LIVES, h.lives);
    const key = `${total}:${h.lives}`;
    if (key !== this._livesKey) {
      this._livesKey = key;
      const pips = Array.from({ length: total }, (_, i) => {
        const pip = document.createElement('i');
        pip.className = i < h.lives ? 'life' : 'life lost';
        return pip;
      });
      el.lives.replaceChildren(...pips);
      el.lives.setAttribute('aria-label', `${h.lives} ${plural(h.lives, 'life', 'lives')}`);
    }
  }

  renderStats() {
    const { el, storage } = this;
    const r = storage.records;
    el.bestScore.textContent = number(r.bestScore);
    el.bestClear.textContent = `${r.bestClear.toFixed(1)}%`;
    el.bestLevel.textContent = r.bestLevel ? pad2(r.bestLevel) : '—';
    el.runsPlayed.textContent = String(r.runs);
    el.levelsWon.textContent = String(r.wins);
    el.storageNote.textContent = storage.persistent ? 'All progress stays on this device.' : "Storage is blocked here, so progress won't be saved.";
    if (!storage.persistent) el.titleRecords.textContent = "Storage is blocked here, so records won't be saved.";
    else if (!r.runs) el.titleRecords.textContent = '> no runs yet';
    else {
      const parts = [];
      if (r.bestScore) parts.push(`best ${number(r.bestScore)}`);
      if (r.bestClear) parts.push(`clear ${r.bestClear.toFixed(1)}%`);
      if (r.bestLevel) parts.push(`top level ${pad2(r.bestLevel)}`);
      parts.push(`${r.runs} ${plural(r.runs, 'run', 'runs')}`);
      el.titleRecords.textContent = `> ${parts.join(' · ')}`;
    }
  }

  /* An interrupted run on offer: the Resume button leads, Start run steps back to a plain button. */
  renderSaved() {
    const { el, game } = this;
    const snap = game.saved;
    el.app.dataset.saved = snap ? 'yes' : 'no';
    el.resumeRunButton.hidden = !snap;
    el.startButton.classList.toggle('btn--primary', !snap);
    el.savedLine.hidden = !snap;
    if (!snap) return;
    const minutes = Math.max(0, Math.round((Date.now() - snap.savedAt) / 60000));
    const ago = minutes < 1 ? 'just now' : minutes < 60 ? `${minutes} min ago` : `${Math.round(minutes / 60)} h ago`;
    el.savedLine.textContent = `saved run: level ${pad2(snap.level)} · ${number(snap.run.score)} points · ${ago}`;
  }

  renderTheme() {
    const theme = this.storage.settings.theme;
    this.el.flightButton.setAttribute('aria-checked', String(theme === 'flight'));
    this.el.driveButton.setAttribute('aria-checked', String(theme === 'drive'));
  }

  renderSound() {
    const on = this.storage.settings.sound;
    this.el.soundButton.setAttribute('aria-pressed', String(on));
    this.el.soundSwitch.setAttribute('aria-checked', String(on));
  }

  /* "Auto" follows the operating system; the choice also decides whether the board animates. */
  reducedMotion() {
    const motion = this.storage.settings.motion;
    return motion === 'reduced' || (motion === 'auto' && !!this._reduceQuery && this._reduceQuery.matches);
  }

  renderMotion() {
    const motion = this.storage.settings.motion;
    document.documentElement.dataset.motion = motion;
    for (const button of this.motionButtons) button.setAttribute('aria-checked', String(button.dataset.motion === motion));
    this.renderer.setReducedMotion(this.reducedMotion());
  }

  renderFps() {
    const { el, loop } = this;
    const on = this.storage.settings.showFps;
    el.fpsSwitch.setAttribute('aria-checked', String(on));
    el.fpsMeter.hidden = !on;
    if (!loop) return;
    loop.onStats = on
      ? (s) => { el.fpsMeter.textContent = `${s.fps} fps · ${s.avgMs.toFixed(1)} ms · max ${s.maxMs.toFixed(1)}`; }
      : null;
  }

  renderPhase() {
    const { el, game } = this;
    const phase = game.phase;
    const paused = phase === PHASE.PAUSED || phase === PHASE.COUNTDOWN;
    const daily = !!game.run && (game.run.mode === 'daily' || game.run.mode === 'tutorial');       // neither can be restarted
    el.app.dataset.phase = phase;

    if (phase === PHASE.COUNTDOWN) {
      el.pauseEyebrow.textContent = 'Resuming';
      el.pauseTitle.textContent = String(Math.max(1, Math.ceil(game.countdown)));
    } else {
      el.pauseEyebrow.textContent = 'Run paused';
      el.pauseTitle.textContent = game.pauseReason === 'auto' ? 'Paused while you were away.' : 'Take a breath.';
    }

    const coaching = game.tutorial.active && phase === PHASE.PLAYING;
    const label = paused ? 'Resume' : coaching ? 'Skip tutorial' : 'Pause';
    el.pauseButton.dataset.state = paused ? 'paused' : coaching ? 'skip' : 'running';
    el.pauseButton.setAttribute('aria-label', label);
    const text = el.pauseButton.querySelector('.btn-text');
    if (text) text.textContent = label;
    el.pauseButton.disabled = !(phase === PHASE.PLAYING || phase === PHASE.CLEAR || paused);
    el.restartButton.disabled = !(phase === PHASE.PLAYING || paused) || daily;
    el.pauseRestartButton.hidden = daily;

    if (this.isModalOpen()) return;                       // a dialog on top keeps the focus it was given
    if (phase === PHASE.PAUSED) el.resumeButton.focus({ preventScroll: true });
    else if (phase === PHASE.OVER) el.againButton.focus({ preventScroll: true });
    else if (phase === PHASE.TITLE && matchMedia('(pointer: fine)').matches) (game.saved ? el.resumeRunButton : el.startButton).focus({ preventScroll: true });
  }

  renderOver(report) {
    const { el, storage } = this;
    const best = report.newBest;
    fillRows(el.receipt, [
      ['Score', number(report.score), best.score ? 'NEW BEST' : ''],
      ['Level reached', pad2(report.level)],
      ['Best clear', `${storage.records.bestClear.toFixed(1)}%`, best.clear ? 'NEW BEST' : ''],
      ['Captures', String(report.stats.captures)],
      ['Close calls', String(report.stats.closeCalls)],
    ]);
    el.endSummary.textContent = best.score ? 'A new high score. Go again?' : 'Start fresh and find a cleaner line.';
    this.announce(`Run over. ${number(report.score)} points, level ${report.level}${best.score ? ', a new best score' : ''}`);
  }

  /* The win screen: what the level's captures scored, then each bonus. */
  renderTally(t) {
    const { el } = this;
    el.nextLabel.textContent = t.tutorial ? 'Play' : 'Next level';
    el.clearNote.hidden = !t.tutorial;
    if (t.tutorial) {
      el.clearEyebrow.textContent = 'Tutorial complete';
      el.clearTotal.textContent = 'Nice work.';
      fillRows(el.tally, [['Claimed', `${t.cleared.toFixed(1)}%`], ['To clear a level', `${levelInfo(1).target}%`]]);
      el.clearNote.textContent = 'A patrol touching a route you are still drawing costs a life. Lifting mid-field is free.';
      this.announce(`Tutorial complete. You claimed ${Math.round(t.cleared)} percent`);
      return;
    }
    el.clearEyebrow.textContent = `Level ${pad2(t.level)} cleared`;
    el.clearTotal.textContent = `+${number(t.total)}`;
    fillRows(el.tally, [
      ['Captures', `+${number(t.capturePoints)}`],
      [`Overshoot ${t.overshoot.toFixed(1)}%`, `+${number(t.overshootBonus)}`],
      [`Lives x${t.lives}`, `+${number(t.livesBonus)}`],
      [`Time ${Math.round(t.seconds)} s`, `+${number(t.timeBonus)}`],
    ]);
    this.announce(`Level ${t.level} cleared. ${number(t.total)} points`);
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
