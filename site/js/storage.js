/* Persistence. Everything goes through here so a blocked, full or corrupt localStorage can never
   stop the game: reads fall back to defaults, writes fall back to memory, and `persistent` tells the
   UI whether progress will survive a reload. */
import { STORAGE_KEY, LEGACY_KEY, SNAPSHOT_KEY } from './config.js';

const THEMES = ['flight', 'drive'];
const MOTIONS = ['auto', 'reduced', 'full'];

export const defaultData = () => ({
  v: 2,
  settings: { sound: true, theme: 'flight', motion: 'auto', showFps: false, tutorialDone: false },
  records: { bestScore: 0, bestClear: 0, bestLevel: 0, runs: 0, wins: 0 },
});

const count = (value, fallback) => (Number.isFinite(value) && value >= 0 ? value : fallback);
const isObject = (value) => value !== null && typeof value === 'object';

/* Merge untrusted JSON over the defaults; unknown keys and wrong types are dropped. */
export function sanitize(input) {
  const out = defaultData();
  const settings = isObject(input) && isObject(input.settings) ? input.settings : {};
  const records = isObject(input) && isObject(input.records) ? input.records : {};
  if (typeof settings.sound === 'boolean') out.settings.sound = settings.sound;
  if (THEMES.includes(settings.theme)) out.settings.theme = settings.theme;
  if (MOTIONS.includes(settings.motion)) out.settings.motion = settings.motion;
  if (typeof settings.showFps === 'boolean') out.settings.showFps = settings.showFps;
  if (typeof settings.tutorialDone === 'boolean') out.settings.tutorialDone = settings.tutorialDone;
  for (const key of Object.keys(out.records)) out.records[key] = count(records[key], out.records[key]);
  return out;
}

/* The prototype stored { bestClear, bestLevel, runs, wins, theme } under color-divide-records-v1.
   The old key is left in place: this only reads it. */
export function migrateLegacy(raw) {
  if (!raw) return null;
  let old;
  try { old = JSON.parse(raw); } catch { return null; }
  if (!isObject(old)) return null;
  return sanitize({ settings: { theme: old.theme }, records: old });
}

export function memoryBackend() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
  };
}

/* localStorage if it really works. Blocked cookies and some private modes make even reading it throw,
   and others accept reads but refuse every write. */
function probeLocalStorage() {
  try {
    const store = globalThis.localStorage;
    const key = '__pathpatrol_probe__';
    store.setItem(key, '1');
    store.removeItem(key);
    return store;
  } catch {
    return null;
  }
}

export function createStorage(backend) {
  let persistent = true;
  if (!backend) {
    backend = probeLocalStorage();
    if (!backend) { backend = memoryBackend(); persistent = false; }
  }

  const read = (key) => {
    try { return backend.getItem(key); } catch { persistent = false; return null; }
  };
  const write = (key, value) => {
    try { backend.setItem(key, value); } catch { persistent = false; }
  };
  const remove = (key) => {
    try { backend.removeItem(key); } catch { persistent = false; }
  };

  function load() {
    const raw = read(STORAGE_KEY);
    if (raw) {
      try { return sanitize(JSON.parse(raw)); } catch { /* corrupt: fall through to defaults */ }
    }
    return migrateLegacy(read(LEGACY_KEY)) || defaultData();
  }

  let data = load();
  const save = () => write(STORAGE_KEY, JSON.stringify(data));

  return {
    get persistent() { return persistent; },
    get settings() { return data.settings; },
    get records() { return data.records; },
    updateSettings(patch) {
      data.settings = sanitize({ settings: { ...data.settings, ...patch } }).settings;
      save();
      return data.settings;
    },
    updateRecords(mutate) {
      mutate(data.records);
      data.records = sanitize({ records: data.records }).records;
      save();
      return data.records;
    },
    /* Clears the scores and keeps the settings: resetting records must not forget the theme. */
    resetRecords() {
      data.records = defaultData().records;
      save();
      return data.records;
    },
    reload() { data = load(); },
    /* The run in progress. The caller validates what comes back: this only keeps and returns it. */
    saveSnapshot(snapshot) { write(SNAPSHOT_KEY, JSON.stringify(snapshot)); },
    loadSnapshot() {
      const raw = read(SNAPSHOT_KEY);
      if (!raw) return null;
      try { return JSON.parse(raw); } catch { remove(SNAPSHOT_KEY); return null; }      // damaged: forget it rather than keep tripping on it
    },
    clearSnapshot() { remove(SNAPSHOT_KEY); },
  };
}
