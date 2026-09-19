/* Seeded randomness.

   Layouts draw from one stream and in-game events from another, both derived from (seed, level).
   Nothing a player does can change a later level's layout, which is what makes the daily board
   identical for everyone. Do not change hashString() or mulberry32() once the daily is live:
   it would change every player's board. */

/* FNV-1a over the UTF-16 units, then a murmur3-style finaliser so nearby strings diverge. */
export function hashString(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Rng {
  constructor(seed) {
    this.next = mulberry32(typeof seed === 'string' ? hashString(seed) : seed);
  }
  float() { return this.next(); }
  range(min, max) { return min + this.next() * (max - min); }
  int(min, max) { return Math.floor(this.range(min, max)); }      // integer in [min, max)
  pick(list) { return list[this.int(0, list.length)]; }
}

export const layoutRng = (seed, level) => new Rng(`${seed}|layout|${level}`);
export const eventRng = (seed, level) => new Rng(`${seed}|events|${level}`);

/* A fresh seed for an ordinary run. */
export function randomSeed() {
  const words = new Uint32Array(2);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(words);
  else { words[0] = Math.random() * 4294967296; words[1] = Math.random() * 4294967296; }
  return words[0].toString(36) + words[1].toString(36);
}

/* The local calendar day as YYYY-MM-DD, and the seed the daily board derives from it. */
export function dayKey(date = new Date()) {
  const two = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`;
}
export const dailySeed = (key) => `pathpatrol-daily-${key}`;
