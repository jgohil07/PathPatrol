/* The daily challenge's pure parts: which day it is, what number the puzzle is, whether a streak is alive, and the
   text a player shares. Days are local calendar dates as YYYY-MM-DD strings; date arithmetic is done in UTC on the
   year, month and day alone, so a change of clocks can never make a day 23 or 25 hours long. */
import { DAILY } from './config.js';

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const two = (n) => String(n).padStart(2, '0');

/* Is this a real calendar day in that format (2026-02-30 is not)? */
export function isDay(text) {
  const m = typeof text === 'string' ? DAY.exec(text) : null;
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

const dayMs = (day) => { const m = DAY.exec(day); return Date.UTC(+m[1], +m[2] - 1, +m[3]); };
const dayName = (ms) => { const d = new Date(ms); return `${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())}`; };

export const previousDay = (day) => dayName(dayMs(day) - 86400000);
export const daysBetween = (a, b) => Math.round((dayMs(b) - dayMs(a)) / 86400000);

/* Puzzle #1 was the epoch day. A clock set before it still gets #1. */
export const puzzleNumber = (day) => Math.max(1, daysBetween(DAILY.epoch, day) + 1);

/* A streak counts consecutive days on which the daily was started. It is alive if the last such day was today or
   yesterday; otherwise it has already lapsed, though the stored number stays until the next attempt resets it. */
export const streakNow = (daily, today) => (daily.last === today || daily.last === previousDay(today) ? daily.streak : 0);
export const nextStreak = (daily, today) => (daily.last === previousDay(today) ? daily.streak + 1 : 1);

/* What a finished counted attempt is remembered as. A daily starts on level 1 and moves up one level at a time, so
   the levels cleared are just the level it ended on, less one. `progress` is how far the last level's target got. */
export function dailyResult(run, level) {
  return {
    level: level.number,
    clear: Math.round(level.cleared * 10) / 10,
    score: run.score,
    progress: Math.round(Math.min(1, level.cleared / level.info.target) * 1000) / 1000,
  };
}

/* The text a player shares:

     Path Patrol · Daily #12 · 2026-09-19
     L4 · 71.3% · 12,480 pts · ■■■□
     ▰▰▰▱
     https://jgohil07.github.io/PathPatrol/

   ■ is a level cleared and □ the one the run ended on (long runs are shortened with an ellipsis); the row of blocks
   is how far that last level's target was reached. */
export function shareText(day, result) {
  const cleared = result.level - 1;
  const shown = Math.min(cleared, DAILY.pathGlyphs);
  const path = `${cleared > shown ? '…' : ''}${'■'.repeat(shown)}□`;
  const filled = Math.min(DAILY.barLength - 1, Math.floor(result.progress * DAILY.barLength));      // never full: a full bar is a level cleared
  const bar = '▰'.repeat(filled) + '▱'.repeat(DAILY.barLength - filled);
  return [
    `Path Patrol · Daily #${puzzleNumber(day)} · ${day}`,
    `L${result.level} · ${result.clear.toFixed(1)}% · ${result.score.toLocaleString('en-US')} pts · ${path}`,
    bar,
    DAILY.shareUrl,
  ].join('\n');
}
