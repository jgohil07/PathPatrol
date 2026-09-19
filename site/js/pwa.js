/* Everything that makes this an installable, offline app, apart from the service worker itself (sw.js):
     - registering it, and knowing whether an offline copy is ready or an update is waiting
     - taking an update over only when that is safe: when asked, or when the page has just loaded onto the title screen
       (never in the middle of a run: a new version is a reload)
     - the browser's install prompt, and the one-time "Add to Home Screen" hint for iOS, which has no prompt
     - keeping the screen awake while a run is being played
   Nothing here may break the game. Every feature is detected and every failure swallowed; `onChange` is called whenever
   something the screens show has changed. */
import { PHASE } from './game.js';

const UPDATE_CHECK_EVERY_MS = 60 * 60 * 1000;           // a long-lived (installed) session looks for a new version at most this often

export class Pwa {
  constructor({ game, storage, register = true, onChange = () => {} }) {
    this.game = game;
    this.storage = storage;
    this.shouldRegister = register;
    this.onChange = onChange;
    this.offline = 'unsupported';        // 'unsupported', 'pending' (installing the offline copy) or 'ready'
    this.update = false;                 // a new version has installed and is waiting to take over
    this.installPrompt = null;           // the browser's deferred install prompt, if it offered one
    this.installed = false;
    this.registration = null;
    this._hadController = false;
    this._applying = false;              // this page asked for the takeover
    this._reloadWhenIdle = false;        // another tab took an update over while this one was mid-run
    this._lastCheck = 0;
    this._wake = null;
    this._wakeWanted = false;
    this._wakeBusy = false;
  }

  start() {
    window.addEventListener('beforeinstallprompt', (event) => {
      event.preventDefault();                            // no mini-infobar: the game offers Install itself
      this.installPrompt = event;
      this.onChange();
    });
    window.addEventListener('appinstalled', () => {
      this.installed = true;
      this.onChange();
    });
    this.game.on('phase', () => { this._syncWake(); if (this._reloadWhenIdle && this.game.phase === PHASE.TITLE) location.reload(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this._check(); });
    if (this.shouldRegister) {
      if (document.readyState === 'complete') this._register();
      else window.addEventListener('load', () => this._register(), { once: true });      // after the game is up: the worker's downloads never compete with it
    }
  }

  /* --- the offline copy and its updates ------------------------------------------------------------------ */

  async _register() {
    try {
      this._hadController = !!navigator.serviceWorker.controller;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!this._hadController) { this._hadController = true; return; }     // the very first worker claiming the page: nothing to reload, but from now on it has a controller, so a takeover is an update
        // A new version has taken over, so this page should restart to run it. If this page asked, now. If another tab did, it
        // may be mid-run here: the modules it loaded are all in memory and it can play on, so wait until it is back on the title.
        if (this._applying || this.game.phase === PHASE.TITLE) location.reload();
        else this._reloadWhenIdle = true;
      });
      this.offline = 'pending';
      const registration = await navigator.serviceWorker.register('./sw.js', { scope: './' });
      this.registration = registration;
      navigator.serviceWorker.ready.then(() => { this.offline = 'ready'; this.onChange(); });
      registration.addEventListener('updatefound', () => this._watch(registration.installing));
      if (registration.installing) this._watch(registration.installing);
      if (registration.waiting && navigator.serviceWorker.controller) {
        // A version finished installing in an earlier visit and never took over. The page has only just loaded: if it is
        // still on the title, that is the safe moment.
        this.update = true;
        if (this.game.phase === PHASE.TITLE) this.applyUpdate();
      }
      this.onChange();
    } catch {
      this.offline = 'unsupported';                       // blocked here (some private modes), or not a secure page
      this.onChange();
    }
  }

  _watch(worker) {
    worker.addEventListener('statechange', () => {
      if (worker.state === 'installed' && navigator.serviceWorker.controller) { this.update = true; this.onChange(); }
    });
  }

  /* Look for a new version now and then while the page stays open (the browser checks on every load by itself). */
  _check() {
    const now = Date.now();
    if (!this.registration || now - this._lastCheck < UPDATE_CHECK_EVERY_MS) return;
    this._lastCheck = now;
    this.registration.update().catch(() => {});
  }

  /* Let the waiting version take over; the page reloads itself when it has, and the run in progress is saved as any page is when it goes
     (pagehide) and offered again. (Another tab may have taken it already.) */
  applyUpdate() {
    const waiting = this.registration && this.registration.waiting;
    if (!waiting) return;
    this._applying = true;
    waiting.postMessage('SKIP_WAITING');
  }

  /* --- installing ----------------------------------------------------------------------------------------- */

  get standalone() {
    return navigator.standalone === true || matchMedia('(display-mode: standalone)').matches || matchMedia('(display-mode: fullscreen)').matches;
  }

  get isIos() {
    return /iphone|ipad/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);      // (an iPod touch says 'iPhone OS'; an iPad since iPadOS 13 says it is a Mac)
  }

  get canInstall() { return !!this.installPrompt && !this.installed && !this.standalone; }

  /* iOS has no install prompt: say once where the button is, unless it is already installed or the hint was dismissed. */
  get iosHint() { return this.isIos && !this.standalone && !this.storage.settings.installHintSeen; }

  dismissHint() {
    this.storage.updateSettings({ installHintSeen: true });
    this.onChange();
  }

  /* Shows the browser's install prompt; true if the person accepted it. */
  async install() {
    const prompt = this.installPrompt;
    this.installPrompt = null;                            // a prompt can be shown once; the browser offers a new one if it wants
    this.onChange();
    try {
      await prompt.prompt();
      if ((await prompt.userChoice).outcome !== 'accepted') return false;
      this.installed = true;
      this.onChange();
      return true;
    } catch {
      return false;
    }
  }

  /* --- the screen stays awake while playing ------------------------------------------------------------------ */

  /* Held from the moment a run is being played until it stops being played (paused, over, cleared). Hiding the page pauses
     the game, so the system's own letting go of the lock at that moment is followed by ours. */
  async _syncWake() {
    this._wakeWanted = this.game.phase === PHASE.PLAYING;
    if (this._wakeBusy) return;
    this._wakeBusy = true;                                // one request or release at a time; the loop settles on what is wanted now
    while (this._wakeWanted !== !!this._wake) {
      if (this._wakeWanted) {
        try { this._wake = await navigator.wakeLock.request('screen'); }
        catch { break; }                                  // no Wake Lock here, or it was refused (battery saver, no permission): play on with the screen as it is
      } else {
        const lock = this._wake;
        this._wake = null;
        await lock.release();
      }
    }
    this._wakeBusy = false;
  }
}
