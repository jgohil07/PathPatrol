/* Persistence. Everything goes through here so a blocked, full or corrupt localStorage can never
   stop the game: reads fall back to defaults, writes fall back to memory, and `persistent` tells the
   UI whether progress will survive a reload. */
import { STORAGE_KEY, LEGACY_KEY, SNAPSHOT_KEY, EXPERT_SNAPSHOT_KEY, KIND_NAMES, STARS, EXPERT } from './config.js';
import { isDay } from './daily.js';

const THEMES = ['flight', 'drive'];
const MOTIONS = ['auto', 'reduced', 'full'];

export const defaultData = () => ({
  v: 2,
  settings: { sound: true, haptics: true, theme: 'flight', motion: 'auto', showFps: false, tutorialDone: false, installHintSeen: false, seenKinds: [] },
  records: { bestScore: 0, bestClear: 0, bestLevel: 0, runs: 0, wins: 0, daily: { streak: 0, best: 0, last: '', result: null }, stars: {},
             expert: { best: 0, bestScore: 0, finished: 0, runs: 0 } },
});

const slotKey = (slot) => (slot === 'expert' ? EXPERT_SNAPSHOT_KEY : SNAPSHOT_KEY);
const count = (value, fallback) => (Number.isFinite(value) && value >= 0 ? value : fallback);
const isObject = (value) => value !== null && typeof value === 'object';

/* The daily's record: the streak (consecutive days the daily was started), the longest one, the day of the latest
   counted attempt, and that attempt's result once it ended. A result only stands with a day to belong to. */
function cleanDaily(input) {
  const out = { streak: 0, best: 0, last: '', result: null };
  if (!isObject(input)) return out;
  const days = (n) => (Number.isInteger(n) && n >= 0 && n <= 100000 ? n : 0);
  out.streak = days(input.streak);
  out.best = Math.max(days(input.best), out.streak);
  if (isDay(input.last)) out.last = input.last;
  const r = input.result;
  if (out.last && isObject(r) && Number.isInteger(r.level) && r.level >= 1 && r.level <= 9999 && Number.isFinite(r.clear) && r.clear >= 0 && r.clear <= 100
      && Number.isFinite(r.score) && r.score >= 0 && Number.isFinite(r.progress) && r.progress >= 0 && r.progress <= 1) {
    out.result = { level: r.level, clear: r.clear, score: Math.floor(r.score), progress: r.progress };
  }
  return out;
}

/* Best stars per level: keys "1".."99", values 1..3. Anything else is dropped, key by key. */
function cleanStars(input) {
  const out = {};
  if (!isObject(input) || Array.isArray(input)) return out;
  for (const [key, value] of Object.entries(input)) {
    const level = Number(key);
    if (String(level) === key && Number.isInteger(level) && level >= 1 && level <= STARS.maxLevel && Number.isInteger(value) && value >= 1 && value <= 3) out[key] = value;
  }
  return out;
}

/* Expert mode's own records: the highest level cleared (0-15), the best score, runs finished and runs started. */
function cleanExpert(input) {
  const out = { best: 0, bestScore: 0, finished: 0, runs: 0 };
  if (!isObject(input)) return out;
  const whole = (n) => (Number.isInteger(n) && n >= 0 && n <= Number.MAX_SAFE_INTEGER ? n : 0);
  if (Number.isInteger(input.best) && input.best >= 0 && input.best <= EXPERT.levels) out.best = input.best;
  out.bestScore = whole(input.bestScore);
  out.finished = whole(input.finished);
  out.runs = whole(input.runs);
  return out;
}

/* Merge untrusted JSON over the defaults; unknown keys and wrong types are dropped. */
export function sanitize(input) {
  const out = defaultData();
  const settings = isObject(input) && isObject(input.settings) ? input.settings : {};
  const records = isObject(input) && isObject(input.records) ? input.records : {};
  if (typeof settings.sound === 'boolean') out.settings.sound = settings.sound;
  if (typeof settings.haptics === 'boolean') out.settings.haptics = settings.haptics;
  if (THEMES.includes(settings.theme)) out.settings.theme = settings.theme;
  if (MOTIONS.includes(settings.motion)) out.settings.motion = settings.motion;
  if (typeof settings.showFps === 'boolean') out.settings.showFps = settings.showFps;
  if (typeof settings.tutorialDone === 'boolean') out.settings.tutorialDone = settings.tutorialDone;
  if (typeof settings.installHintSeen === 'boolean') out.settings.installHintSeen = settings.installHintSeen;
  if (Array.isArray(settings.seenKinds)) out.settings.seenKinds = KIND_NAMES.filter((k) => settings.seenKinds.includes(k));       // known kinds only, once each
  for (const key of Object.keys(out.records)) out.records[key] = count(records[key], out.records[key]);       // (the daily's record, the stars and expert's are not numbers: they keep their defaults here, and are read properly next)
  out.records.daily = cleanDaily(records.daily);
  out.records.stars = cleanStars(records.stars);
  out.records.expert = cleanExpert(records.expert);
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
    /* The run in progress, in one of two slots: 'run' (the campaign's or the daily's) and 'expert'. The caller validates
       what comes back: this only keeps and returns it. */
    saveSnapshot(snapshot, slot = 'run') { write(slotKey(slot), JSON.stringify(snapshot)); },
    loadSnapshot(slot = 'run') {
      const key = slotKey(slot);
      const raw = read(key);
      if (!raw) return null;
      try { return JSON.parse(raw); } catch { remove(key); return null; }      // damaged: forget it rather than keep tripping on it
    },
    clearSnapshot(slot = 'run') { remove(slotKey(slot)); },
  };
}
