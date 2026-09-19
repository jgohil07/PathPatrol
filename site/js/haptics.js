/* Haptics: short vibrations through navigator.vibrate, where the browser has it (Android; iOS Safari does not).
   They follow the same events as the sound, are off if the player turned them off, and never throw. */

const PATTERNS = {
  hit: [40],
  closecall: [8],
  small: [6],
  medium: [12],
  large: [10, 30, 16],
  extraLife: [15, 40, 15],
  clear: [20, 30, 20, 30, 40],
  over: [60, 40, 60],
};

export class Haptics {
  constructor({ game, storage }) {
    this.game = game;
    this.storage = storage;
    game.on('route', (event) => {
      if (event.type === 'hit') this.pulse('hit');
      else if (event.type === 'closecall') this.pulse('closecall');
    });
    game.on('capture', (result) => this.pulse(result.gained >= 10 ? 'large' : result.gained >= 2 ? 'medium' : 'small'));
    game.on('extraLife', () => this.pulse('extraLife'));
    game.on('power', (event) => { if (event.type === 'start') this.pulse('medium'); });
    game.on('clear', () => this.pulse('clear'));
    game.on('over', () => this.pulse('over'));
  }

  get supported() { return typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function'; }
  get enabled() { return this.supported && this.storage.settings.haptics; }

  pulse(name) {
    if (!this.enabled) return false;
    try { return navigator.vibrate(PATTERNS[name]); } catch { return false; }
  }
}
