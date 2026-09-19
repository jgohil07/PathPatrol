"""The daily challenge: one board a day, the same for everyone; three lives and no restarts; only the first attempt of a day
counts (towards the streak and the shareable result), later ones are practice; and a result that can be shared as text.

The logic is tested on in-page games with the calendar day pinned (`game.today`), so every date is exact; the screens are
tested through the real page, with `navigator.share` and the clipboard stood in for so each way of sharing can be forced."""
import json

import pytest

DESKTOP = {'width': 1280, 'height': 800}
PHONE = {'width': 390, 'height': 844}

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, sanitize, defaultData } = await import('/js/storage.js');
  const { STEP, DAILY, levelInfo } = await import('/js/config.js');
  const D = await import('/js/daily.js');
  const { makePatrol } = await import('/js/physics.js');
  const { dailySeed } = await import('/js/rng.js');
  const backendOf = (initial = {}) => { const map = new Map(Object.entries(initial));
    return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }, removeItem: (k) => { map.delete(k); } }; };
  /* A game on the title, its calendar pinned to `day`. */
  const fresh = (day = '2026-09-25', backend = backendOf()) => { const game = new Game({ storage: createStorage(backend) }); game.today = () => day; game.enterTitle(); return game; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  const colCells = (game, unitX) => { const g = game.grid, x = Math.floor(unitX * 2), cells = []; for (let y = 0; y < g.h; y++) if (g.get(x, y) === 0) cells.push(g.index(x, y)); return cells; };
  /* Clear the level in hand: the patrol goes to the far right, the ground up to x = 90 is claimed (well over any target). */
  const win = (game) => { game.level.patrols.length = 0; game.level.patrols.push(makePatrol(112, 64, 0, 0)); game.commitCapture(colCells(game, 90)); run(game, 1); return game.skipClear(); };
  const die = (game) => { game.loseLife(); game.loseLife(); game.loseLife(); };
"""


def js(page, body):
    return page.evaluate("async () => {" + PRELUDE + body + "\n}")


@pytest.fixture
def page(open_page):
    return open_page()


# ---- days, numbers, streaks -----------------------------------------------------------------------------------------
def test_only_real_calendar_days_are_days_and_yesterday_is_exact(page):
    got = js(page, """
      const bad = ['2026-02-30', '2026-13-01', '2026-00-10', '2026-1-1', '26-01-01', '2026-01-32', '', null, undefined, 20260925, '2026-09-25T00:00', ' 2026-09-25'];
      return { good: ['2026-09-25', '2028-02-29', '2000-02-29', '2026-12-31'].map(D.isDay), bad: bad.map(D.isDay),
               notLeap: D.isDay('2027-02-29'), century: D.isDay('1900-02-29'),
               prev: ['2026-09-25', '2026-03-01', '2028-03-01', '2027-01-01', '2026-10-01'].map(D.previousDay) };""")
    assert got['good'] == [True] * 4 and got['bad'] == [False] * 12 and got['notLeap'] is False and got['century'] is False
    assert got['prev'] == ['2026-09-24', '2026-02-28', '2028-02-29', '2026-12-31', '2026-09-30']


def test_puzzle_numbers_count_days_from_the_epoch_and_a_change_of_clocks_cannot_move_them(page):
    got = js(page, """
      const same = ['2026-09-19', '2026-09-20', '2026-10-01', '2027-09-19', '2028-03-01'].map(D.puzzleNumber);
      const dst = [['2027-03-13', '2027-03-14'], ['2027-03-14', '2027-03-15'], ['2026-10-31', '2026-11-01'], ['2026-11-01', '2026-11-02']].map(([a, b]) => D.daysBetween(a, b));
      return { epoch: DAILY.epoch, same, before: [D.puzzleNumber('2026-09-18'), D.puzzleNumber('2020-01-01')], dst,
               span: D.daysBetween('2026-09-19', '2027-09-19'), back: D.daysBetween('2026-09-25', '2026-09-19') };""")
    assert got['epoch'] == '2026-09-19'
    assert got['same'] == [1, 2, 13, 366, 530]                                          # puzzle #1 is the epoch day (and 2028 is a leap year)
    assert got['before'] == [1, 1]                                                       # a clock set earlier than launch is still #1
    assert got['dst'] == [1, 1, 1, 1] and got['span'] == 365 and got['back'] == -6       # every day is one day, whatever the clocks did


@pytest.mark.parametrize('last,streak,today,alive,next_streak', [
    ('', 0, '2026-09-25', 0, 1),                    # never played
    ('2026-09-25', 4, '2026-09-25', 4, 1),          # played today: alive (the next counted attempt is tomorrow's, but "next" only asks about consecutive-ness)
    ('2026-09-24', 4, '2026-09-25', 4, 5),          # yesterday: alive, and today extends it
    ('2026-09-23', 4, '2026-09-25', 0, 1),          # a day missed: lapsed, and today starts again
    ('2026-08-01', 30, '2026-09-25', 0, 1),
    ('2026-09-26', 4, '2026-09-25', 0, 1),          # a "last" day in the future (a clock set back): not consecutive
    ('2026-12-31', 7, '2027-01-01', 7, 8),          # across a year
    ('2028-02-28', 2, '2028-02-29', 2, 3),          # and a leap day
    ('2028-02-29', 2, '2028-03-01', 2, 3),
])
def test_a_streak_lives_for_a_day_and_grows_by_consecutive_days(page, last, streak, today, alive, next_streak):
    got = js(page, f"""const d = {{ streak: {streak}, best: {streak}, last: '{last}', result: null }};
      return {{ alive: D.streakNow(d, '{today}'), next: D.nextStreak(d, '{today}') }};""")
    assert got['alive'] == alive
    if last != today:
        assert got['next'] == next_streak


# ---- what is shared -------------------------------------------------------------------------------------------------------
def test_the_shared_text_has_the_planned_shape(page):
    got = js(page, """
      const t = (day, result) => D.shareText(day, result);
      return {
        plan: t('2026-09-30', { level: 4, clear: 71.3, score: 12480, progress: 0.9 }),
        first: t('2026-09-19', { level: 1, clear: 5, score: 0, progress: 0 }),
        bars: [0, 0.24, 0.25, 0.49, 0.5, 0.74, 0.75, 0.99, 1].map((p) => t('2026-09-19', { level: 2, clear: 10, score: 1, progress: p }).split('\\n')[2]),
        long: t('2026-09-19', { level: 16, clear: 30.04, score: 1234567, progress: 0.4 }).split('\\n')[1],
        exactlyAtTheLimit: t('2026-09-19', { level: 12, clear: 30, score: 1, progress: 0.4 }).split('\\n')[1],
        justOver: t('2026-09-19', { level: 13, clear: 30, score: 1, progress: 0.4 }).split('\\n')[1],
      };""")
    assert got['plan'] == ('Path Patrol · Daily #12 · 2026-09-30\n'
                           'L4 · 71.3% · 12,480 pts · ■■■□\n'
                           '▰▰▰▱\n'
                           'https://jgohil07.github.io/PathPatrol/')                      # the plan's example: 71.3 % of level 4, and how far its target got
    assert got['first'] == ('Path Patrol · Daily #1 · 2026-09-19\n'
                            'L1 · 5.0% · 0 pts · □\n'
                            '▱▱▱▱\n'
                            'https://jgohil07.github.io/PathPatrol/')
    assert got['bars'] == ['▱▱▱▱', '▱▱▱▱', '▰▱▱▱', '▰▱▱▱', '▰▰▱▱', '▰▰▱▱', '▰▰▰▱', '▰▰▰▱', '▰▰▰▱']       # a quarter per block, and never full: full would be a level cleared
    assert got['long'] == 'L16 · 30.0% · 1,234,567 pts · …' + '■' * 11 + '□'                    # long runs are shortened: eleven cleared levels and the one it ended on
    assert got['exactlyAtTheLimit'] == 'L12 · 30.0% · 1 pts · ' + '■' * 11 + '□'
    assert got['justOver'] == 'L13 · 30.0% · 1 pts · …' + '■' * 11 + '□'


def test_a_result_is_what_the_level_stood_at_rounded_the_way_it_is_shown(page):
    got = js(page, """
      const game = fresh(); game.newRun({ seed: 's' });
      game.level.cleared = 71.34; game.run.score = 12480; const a = D.dailyResult(game.run, game.level);
      game.level.cleared = 33.35; const b = D.dailyResult(game.run, game.level);
      game.level.cleared = 90; const c = D.dailyResult(game.run, game.level);
      return { a, b, c, target: game.level.info.target };""")
    t = got['target']
    assert got['a'] == {'level': 1, 'clear': 71.3, 'score': 12480, 'progress': 1}                                    # capped: the target was met
    assert got['b']['clear'] == 33.4 or got['b']['clear'] == 33.3                                                  # one decimal (33.35 is a tie either way)
    assert got['b']['progress'] == pytest.approx(round(33.35 / t, 3), abs=1e-9) and got['c']['progress'] == 1


# ---- the record ---------------------------------------------------------------------------------------------------------------
def test_the_daily_record_survives_storage_and_distrusts_what_it_reads(page):
    got = js(page, """
      const clean = (daily) => sanitize({ records: { daily } }).records.daily;
      const good = { streak: 3, best: 5, last: '2026-09-25', result: { level: 4, clear: 61.5, score: 12480, progress: 0.9 } };
      const backend = backendOf(); const a = createStorage(backend);
      a.updateRecords((r) => { r.daily = { ...good }; }); const b = createStorage(backend);
      return {
        defaults: defaultData().records.daily, good: clean(good), stored: b.records.daily,
        notObject: [clean(null), clean('yes'), clean(5), clean([])],
        badDay: clean({ ...good, last: '2026-02-30' }), noDay: clean({ ...good, last: '' }),
        badStreak: [clean({ ...good, streak: -1 }).streak, clean({ ...good, streak: 1.5 }).streak, clean({ ...good, streak: '3' }).streak, clean({ ...good, streak: 1e9 }).streak],
        bestBelowStreak: clean({ ...good, streak: 9, best: 2 }).best,
        badResults: [{ level: 0 }, { level: 1.5 }, { level: 10000 }, { clear: 101 }, { clear: -1 }, { clear: 'x' }, { score: -5 }, { score: NaN }, { progress: 1.1 }, { progress: -0.1 }, { level: '4' }]
          .map((patch) => clean({ ...good, result: { ...good.result, ...patch } }).result),
        floors: clean({ ...good, result: { ...good.result, score: 12480.9 } }).result.score,
        extras: Object.keys(clean({ ...good, extra: 1, result: { ...good.result, extra: 1 } })).concat(Object.keys(clean({ ...good, result: { ...good.result, extra: 1 } }).result)),
        reset: (() => { const s = createStorage(backendOf()); s.updateRecords((r) => { r.daily = { ...good }; r.runs = 3; }); s.resetRecords(); return s.records.daily; })(),
      };""")
    none = {'streak': 0, 'best': 0, 'last': '', 'result': None}
    good = {'streak': 3, 'best': 5, 'last': '2026-09-25', 'result': {'level': 4, 'clear': 61.5, 'score': 12480, 'progress': 0.9}}
    assert got['defaults'] == none and got['good'] == good and got['stored'] == good
    assert got['notObject'] == [none] * 4
    assert got['badDay'] == {**good, 'last': '', 'result': None}                          # no real day: nothing for a result to belong to
    assert got['noDay'] == {**good, 'last': '', 'result': None}
    assert got['badStreak'] == [0, 0, 0, 0]
    assert got['bestBelowStreak'] == 9                                                     # the best is never below the current streak
    assert got['badResults'] == [None] * 11
    assert got['floors'] == 12480
    assert got['extras'] == ['streak', 'best', 'last', 'result', 'level', 'clear', 'score', 'progress']       # nothing unknown is kept
    assert got['reset'] == none                                                            # resetting the records resets the streak too


# ---- one board a day -----------------------------------------------------------------------------------------------------------
def test_the_daily_board_is_the_same_whatever_was_done_before_and_differs_from_day_to_day(open_page):
    body = """
      const layout = (game, level) => { game.startLevel(level); return JSON.stringify({ o: game.level.obstacles, p: game.level.patrols.map((p) => [p.x, p.y, p.vx, p.vy]), g: Array.from(game.grid.cells).reduce((h, v, i) => (h * 31 + v * (i % 97 + 1)) >>> 0, 7) }); };
      const boards = (day, play) => { const game = fresh(day); game.startDaily(); const out = [layout(game, 1)];
        if (play) { game.commitCapture(colCells(game, 30)); game.loseLife(); game.startLevel(1); }                    // play about, then look again
        for (const level of [2, 3, 5, 8]) out.push(layout(game, level)); return out; };
      return { quiet: boards('2026-09-25', false), busy: boards('2026-09-25', true), tomorrow: boards('2026-09-26', false),
               seed: fresh('2026-09-25').today(), seedName: dailySeed('2026-09-25'), runSeed: (() => { const g = fresh('2026-09-25'); g.startDaily(); return g.run.seed; })() };"""
    results = []
    for viewport in (DESKTOP, PHONE):                                                     # two different screens
        page = open_page(viewport=viewport, has_touch=viewport is PHONE, is_mobile=viewport is PHONE)
        results.append(js(page, body))
    assert results[0]['quiet'] == results[1]['quiet']                                     # the same board on both
    assert results[0]['quiet'] == results[0]['busy']                                      # and nothing a player did changes a later level's layout
    assert results[0]['quiet'] != results[0]['tomorrow'] and all(a != b for a, b in zip(results[0]['quiet'], results[0]['tomorrow']))
    assert results[0]['runSeed'] == results[0]['seedName'] == 'pathpatrol-daily-2026-09-25'


def test_starting_the_daily_sets_up_a_run_with_three_lives_and_no_restart(page):
    got = js(page, """
      const game = fresh('2026-09-25'); game.startDaily();
      const started = { mode: game.run.mode, day: game.run.dayKey, practice: game.run.practice, lives: game.run.lives, level: game.level.number, phase: game.phase };
      const restarted = game.restartLevel(); const lives = game.run.lives;
      return { started, restarted, lives, records: { ...game.storage.records }, runs: game.storage.records.runs };""")
    assert got['started'] == {'mode': 'daily', 'day': '2026-09-25', 'practice': False, 'lives': 3, 'level': 1, 'phase': 'playing'}
    assert got['restarted'] is False and got['lives'] == 3                               # no level restarts
    assert got['records']['daily'] == {'streak': 1, 'best': 1, 'last': '2026-09-25', 'result': None} and got['runs'] == 1


def test_only_the_first_attempt_of_a_day_counts_however_it_ends(page):
    got = js(page, """
      const game = fresh('2026-09-25'); const out = [];
      game.startDaily(); out.push([game.run.practice, game.storage.records.daily.streak]);
      game.enterTitle(); game.startDaily();                                          // left it at once and started again: the first attempt was that one
      out.push([game.run.practice, game.storage.records.daily.streak]);
      die(game); game.newRun({ mode: 'normal' }); game.enterTitle(); game.startDaily();
      out.push([game.run.practice, game.storage.records.daily.streak]);
      return { out, runs: game.storage.records.runs, last: game.storage.records.daily.last };""")
    assert got['out'] == [[False, 1], [True, 1], [True, 1]]                              # the first counts; the rest are practice and change nothing
    assert got['runs'] == 4 and got['last'] == '2026-09-25'                              # every run is still a run


def test_the_streak_grows_over_consecutive_days_and_starts_again_after_a_gap(page):
    got = js(page, """
      const backend = backendOf(); const out = [];
      for (const day of ['2026-09-25', '2026-09-26', '2026-09-27', '2026-09-29', '2026-09-30', '2026-12-01']) {
        const game = fresh(day, backend); game.startDaily(); const d = game.storage.records.daily; out.push([day, d.streak, d.best, d.last, game.run.practice]); }
      return out;""")
    assert got == [['2026-09-25', 1, 1, '2026-09-25', False], ['2026-09-26', 2, 2, '2026-09-26', False], ['2026-09-27', 3, 3, '2026-09-27', False],
                   ['2026-09-29', 1, 3, '2026-09-29', False],                                # a day missed: back to 1, the best stays
                   ['2026-09-30', 2, 3, '2026-09-30', False], ['2026-12-01', 1, 3, '2026-12-01', False]]


def test_a_new_day_starts_a_counted_attempt_again_and_clears_the_old_result(page):
    got = js(page, """
      const backend = backendOf(); const game = fresh('2026-09-25', backend); game.startDaily(); win(game); die(game);
      const yesterday = { ...game.storage.records.daily };
      const next = fresh('2026-09-26', backend); next.startDaily();
      return { yesterday, today: { ...next.storage.records.daily }, practice: next.run.practice };""")
    assert got['yesterday']['result'] is not None and got['yesterday']['last'] == '2026-09-25'
    assert got['today'] == {'streak': 2, 'best': 2, 'last': '2026-09-26', 'result': None} and got['practice'] is False


# ---- how a daily ends ------------------------------------------------------------------------------------------------------------
def test_a_counted_daily_ends_with_a_result_to_share_and_a_practice_run_does_not(page):
    got = js(page, """
      const backend = backendOf(); const game = fresh('2026-09-25', backend); game.startDaily();
      win(game); win(game); game.level.cleared = 33.35; game.run.score = 12480; die(game);                   // cleared two levels, and died on the third
      const report = game.report; const stored = { ...game.storage.records.daily };
      const practice = fresh('2026-09-25', backend); practice.startDaily(); die(practice);
      const after = { ...practice.storage.records.daily };
      return { report: { ...report.daily }, level: report.level, mode: report.mode, stored, practiceReport: { ...practice.report.daily }, after,
               expected: D.shareText('2026-09-25', stored.result) };""")
    r = got['report']
    assert got['mode'] == 'daily' and got['level'] == 3
    assert r['counted'] is True and r['practice'] is False and r['day'] == '2026-09-25' and r['number'] == 7 and r['streak'] == 1
    assert r['result']['level'] == 3 and r['result']['score'] > 0 and 33 < r['result']['clear'] < 34
    assert r['text'] == got['expected'] and r['text'].split('\n')[0] == 'Path Patrol · Daily #7 · 2026-09-25' and '■■□' in r['text'].split('\n')[1]    # two cleared, one it ended on
    assert got['stored']['result'] == r['result']                                                                        # remembered, to share again later
    p = got['practiceReport']
    assert p['counted'] is False and p['practice'] is True and p['result'] is None and p['text'] is None
    assert got['after'] == got['stored']                                                                                 # and it left the day's result and the streak alone


def test_a_result_is_not_kept_for_an_attempt_that_is_no_longer_the_days_counted_one(page):
    """Records reset in another tab while a daily is running: the run's day is no longer the record's, so nothing counts."""
    got = js(page, """
      const game = fresh('2026-09-25'); game.startDaily(); game.storage.resetRecords(); die(game);
      return { report: { ...game.report.daily }, record: { ...game.storage.records.daily } };""")
    assert got['report']['counted'] is False and got['report']['text'] is None and got['record']['result'] is None


def test_the_level_start_line_names_the_kind_of_run(page):
    got = js(page, """
      const seen = []; const game = fresh('2026-09-30'); game.on('toast', (t) => seen.push(t.text));
      game.newRun({ mode: 'normal' }); game.startDaily(); win(game); game.startDaily(); game.startDaily();
      return { seen: seen.filter((t) => t.startsWith('Level')), t1: levelInfo(1).target, t2: levelInfo(2).target };""")
    t1, t2 = got['t1'], got['t2']
    assert got['seen'] == [f'Level 01 · clear {t1}%',                                                # a normal run
                           f'Level 01 · clear {t1}% · daily #12', f'Level 02 · clear {t2}% · daily #12',       # the counted daily, every level
                           f'Level 01 · clear {t1}% · practice', f'Level 01 · clear {t1}% · practice']


# ---- a daily interrupted --------------------------------------------------------------------------------------------------------------
def test_an_interrupted_daily_resumes_on_its_own_day_as_the_same_kind_of_run_and_not_on_another(page):
    got = js(page, """
      const backend = backendOf(); const a = fresh('2026-09-25', backend); a.startDaily(); win(a); a.persist();
      const tomorrow = fresh('2026-09-26', backendOf(Object.fromEntries(backend.map))).saved;      // (on a copy: a game that finds a save unusable throws it away) yesterday's daily is not offered
      const sameDay = fresh('2026-09-25', backend);
      const offered = sameDay.saved && { mode: sameDay.saved.mode, day: sameDay.saved.dayKey, practice: sameDay.saved.run.practice, level: sameDay.saved.level };
      sameDay.resumeRun(); sameDay.tick(3.1);
      const resumedAs = { mode: sameDay.run.mode, day: sameDay.run.dayKey, practice: sameDay.run.practice, lives: sameDay.run.lives };
      die(sameDay);                                                                   // it is still the counted attempt: its result is kept
      return { tomorrow, offered, resumedAs, counted: { counted: sameDay.report.daily.counted, practice: sameDay.report.daily.practice } };""")
    assert got['tomorrow'] is None                                                       # yesterday's daily is not offered today
    assert got['offered'] == {'mode': 'daily', 'day': '2026-09-25', 'practice': False, 'level': 2}
    assert got['resumedAs'] == {'mode': 'daily', 'day': '2026-09-25', 'practice': False, 'lives': 3}
    assert got['counted'] == {'counted': True, 'practice': False}


def test_a_practice_run_that_is_saved_and_resumed_is_still_practice(page):
    got = js(page, """
      const backend = backendOf(); const game = fresh('2026-09-27', backend); game.startDaily(); game.enterTitle(); game.startDaily(); game.persist();
      const again = fresh('2026-09-27', backend); const offered = again.saved && again.saved.run.practice;
      again.resumeRun(); again.tick(3.1); die(again);
      return { offered, practice: again.run.practice, report: { counted: again.report.daily.counted, text: again.report.daily.text } };""")
    assert got['offered'] is True and got['practice'] is True and got['report'] == {'counted': False, 'text': None}


def test_the_snapshot_check_wants_a_boolean_for_whether_a_daily_counts(page):
    got = js(page, """
      const snap = await import('/js/snapshot.js');
      const backend = backendOf(); const game = fresh('2026-09-25', backend); game.startDaily(); game.persist();
      const good = JSON.parse(JSON.stringify(game.storage.loadSnapshot()));
      const edit = (fn) => { const c = JSON.parse(JSON.stringify(good)); fn(c); return snap.validateSnapshot(c, { today: '2026-09-25' }); };
      return { good: !!snap.validateSnapshot(good, { today: '2026-09-25' }), practiceKept: edit((c) => { c.run.practice = true; }).run.practice,
               missing: edit((c) => { delete c.run.practice; }).run.practice, junk: edit((c) => { c.run.practice = 'yes'; }).run.practice,
               wrongDay: snap.validateSnapshot(good, { today: '2026-09-26' }), noDay: edit((c) => { c.dayKey = null; }) };""")
    assert got['good'] is True and got['practiceKept'] is True
    assert got['missing'] is False and got['junk'] is False                              # anything but a real true is "counts"
    assert got['wrongDay'] is None and got['noDay'] is None                              # a daily belongs to its day, and must say which


# ---- the tutorial first -----------------------------------------------------------------------------------------------------------
def test_a_first_time_player_gets_the_tutorial_before_their_daily(open_page):
    page = open_page(tutorial=True)
    page.evaluate("__pp.game.today = () => '2026-09-25'; 0")                             # (a function value would be called by evaluate)
    page.click('#dailyButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial' and page.evaluate('__pp.game.tutorial.origin') == 'daily'
    assert page.evaluate('__pp.storage.records.daily.last') == ''                        # nothing has been counted yet
    page.evaluate('__pp.game.finishTutorial({ percent: 30, gained: 30 })')
    page.evaluate('__pp.game.clock.now += 1')
    assert page.evaluate('__pp.game.skipClear()') is True                                # Play
    assert page.evaluate('({ mode: __pp.game.run.mode, practice: __pp.game.run.practice, day: __pp.game.run.dayKey })') == {'mode': 'daily', 'practice': False, 'day': '2026-09-25'}
    assert page.evaluate('__pp.storage.records.daily.last') == '2026-09-25'


def test_skipping_the_tutorial_that_led_to_the_daily_goes_on_to_the_daily(open_page):
    page = open_page(tutorial=True)
    page.evaluate("__pp.game.today = () => '2026-09-25'; 0")                             # (a function value would be called by evaluate)
    page.click('#dailyButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial'
    page.click('#pauseButton')                                                           # Skip
    assert page.evaluate('({ mode: __pp.game.run.mode, day: __pp.game.run.dayKey })') == {'mode': 'daily', 'day': '2026-09-25'}


# ---- the title -------------------------------------------------------------------------------------------------------------------
RESULT = {'level': 4, 'clear': 61.5, 'score': 12480, 'progress': 0.9}


def pin(page, day='2026-09-25'):
    """Pin the calendar day and redraw what depends on it."""
    page.evaluate(f"__pp.game.today = () => '{day}'; __pp.ui.renderStats(); 0")


def record(page, **daily):
    page.evaluate(f"__pp.storage.updateRecords((r) => {{ Object.assign(r.daily, {json.dumps(daily)}); r.runs = Math.max(r.runs, 1); }}); __pp.ui.renderStats(); 0")


def title(page):
    return page.evaluate("""({ label: document.getElementById('dailyLabel').textContent, line: document.getElementById('dailyLine').textContent,
      share: !document.getElementById('shareTodayButton').hidden, state: document.getElementById('app').dataset.daily,
      streak: document.getElementById('dailyStreak').textContent })""")


def test_the_title_offers_todays_daily_and_says_where_the_streak_stands(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    assert title(page) == {'label': 'Daily #7', 'line': '> daily #7 · a new board', 'share': False, 'state': 'open', 'streak': '0 days (best 0)'}
    record(page, streak=4, best=9, last='2026-09-24')                                    # played yesterday: the streak is alive
    assert title(page) == {'label': 'Daily #7', 'line': '> daily #7 · a new board · streak 4', 'share': False, 'state': 'open', 'streak': '4 days (best 9)'}
    record(page, streak=1, best=9, last='2026-09-24')
    assert title(page)['streak'] == '1 day (best 9)' and title(page)['line'].endswith('streak 1')      # the singular
    record(page, streak=4, best=9, last='2026-09-22')                                    # missed a day: lapsed
    assert title(page) == {'label': 'Daily #7', 'line': '> daily #7 · a new board', 'share': False, 'state': 'open', 'streak': '0 days (best 9)'}


def test_after_todays_first_run_the_same_button_is_a_practice_and_the_result_can_be_shared(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    record(page, streak=6, best=9, last='2026-09-25', result=None)                       # started, and never finished
    assert title(page) == {'label': 'Practice #7', 'line': '> daily #7 started · replays are practice', 'share': False, 'state': 'open', 'streak': '6 days (best 9)'}
    record(page, result=RESULT)
    assert title(page) == {'label': 'Practice #7', 'line': '> daily #7 done · L4 · 12,480 pts', 'share': True, 'state': 'done', 'streak': '6 days (best 9)'}
    assert page.locator('#shareTodayButton').is_visible() and page.locator('#dailyButton').is_visible()


def test_the_daily_button_starts_a_counted_run_the_first_time_and_a_practice_after_that(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    page.click('#dailyButton')
    assert page.evaluate('({ phase: __pp.state().phase, mode: __pp.game.run.mode, practice: __pp.game.run.practice })') == {'phase': 'playing', 'mode': 'daily', 'practice': False}
    assert page.locator('#toast').text_content().strip() == 'Level 01 · clear 65% · daily #7'
    assert page.locator('#restartButton').is_disabled() and page.locator('#pauseRestartButton').is_hidden()          # no restarts in a daily
    page.evaluate('__pp.game.enterTitle()')
    assert title(page)['label'] == 'Practice #7'
    page.click('#dailyButton')
    assert page.evaluate('__pp.game.run.practice') is True and page.locator('#toast').text_content().strip() == 'Level 01 · clear 65% · practice'


def test_a_new_day_arriving_while_the_page_sits_on_the_title_updates_the_button(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    record(page, streak=1, best=1, last='2026-09-25', result=RESULT)
    assert title(page)['label'] == 'Practice #7' and title(page)['share'] is True
    page.evaluate("__pp.game.today = () => '2026-09-26'; document.dispatchEvent(new Event('visibilitychange')); 0")       # midnight passed while the tab was away
    assert title(page) == {'label': 'Daily #8', 'line': '> daily #8 · a new board · streak 1', 'share': False, 'state': 'open', 'streak': '1 day (best 1)'}


def test_settings_and_help_carry_the_streak_and_the_rules(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    record(page, streak=3, best=5, last='2026-09-25', result=RESULT)
    page.click('#settingsButton')
    assert page.locator('#dailyStreak').text_content() == '3 days (best 5)' and page.locator('#dailyStreak').is_visible()
    page.keyboard.press('Escape')
    page.click('#helpButton')
    text = page.locator('.how-daily').text_content()
    assert text.startswith('Daily.') and 'three lives' in text and 'first run of the day counts' in text and 'practice' in text
    page.keyboard.press('Escape')


def test_a_saved_daily_is_offered_as_a_daily_and_a_saved_practice_as_practice(open_page):
    page = open_page(viewport=DESKTOP)
    n = page.evaluate("import('/js/daily.js').then((d) => import('/js/rng.js').then((r) => d.puzzleNumber(r.dayKey())))")
    page.evaluate('__pp.game.startDaily(); __pp.game.persist(); 0')
    page.reload(); page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#savedLine').text_content().startswith(f'daily #{n}: level 01')
    assert page.locator('#resumeRunButton').is_visible()
    page.evaluate('__pp.game.resumeRun(); __pp.game.enterTitle(); __pp.game.startDaily(); __pp.game.persist(); 0')          # today's second: a practice
    page.reload(); page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#savedLine').text_content().startswith('practice run: level 01')
    page.evaluate('__pp.game.resumeRun(); __pp.game.enterTitle(); __pp.game.newRun({ mode: "normal" }); __pp.game.persist(); 0')
    page.reload(); page.wait_for_function('window.__pp !== undefined')
    assert page.locator('#savedLine').text_content().startswith('saved run: level 01')


# ---- the game-over card -------------------------------------------------------------------------------------------------------------
def rows(page):
    return page.evaluate("Object.fromEntries([...document.querySelectorAll('#receipt dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent]))")


def over(page):
    return page.evaluate("""({ phase: __pp.state().phase, eyebrow: document.getElementById('endEyebrow').textContent, summary: document.getElementById('endSummary').textContent,
      share: !document.getElementById('shareButton').hidden, focus: document.activeElement.id, againPrimary: document.getElementById('againButton').classList.contains('btn--primary') })""")


def test_a_counted_daily_ends_on_a_card_that_leads_with_share(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    page.evaluate('__pp.game.startDaily(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    assert over(page) == {'phase': 'over', 'eyebrow': 'Daily #7 · no lives left', 'summary': 'Streak: 1 day. A new board tomorrow.',
                          'share': True, 'focus': 'shareButton', 'againPrimary': False}
    assert rows(page)['Daily'] == '#7' and page.locator('#receipt .flag', has_text='PRACTICE').count() == 0
    assert page.locator('#shareButton').is_visible() and page.locator('#againButton').is_visible()
    assert 'ready to share' in page.locator('#announcer').text_content()


def test_a_practice_daily_ends_with_no_share_and_says_why(open_page):
    page = open_page(viewport=DESKTOP)
    pin(page)
    record(page, streak=1, best=1, last='2026-09-25', result=RESULT)
    page.evaluate('__pp.game.startDaily(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    assert over(page) == {'phase': 'over', 'eyebrow': 'Practice · no lives left', 'summary': "Practice runs don't count towards your streak or your shared result.",
                          'share': False, 'focus': 'againButton', 'againPrimary': True}
    assert rows(page)['Daily'].endswith('#7') and page.locator('#receipt .flag', has_text='PRACTICE').count() == 1
    assert page.evaluate('__pp.storage.records.daily.result') == RESULT and page.evaluate('__pp.storage.records.daily.streak') == 1     # nothing changed


def test_an_ordinary_run_ends_as_it_always_did(open_page):
    page = open_page(viewport=DESKTOP)
    page.evaluate('__pp.game.newRun({ mode: "normal" }); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    got = over(page)
    assert got['eyebrow'] == 'No lives left' and got['share'] is False and got['focus'] == 'againButton' and got['againPrimary'] is True
    assert got['summary'] in ('A new high score. Go again?', 'Start fresh and find a cleaner line.') and 'Daily' not in rows(page)


# ---- sharing --------------------------------------------------------------------------------------------------------------------------
STUB = """(() => {
  window.__shared = []; window.__copied = []; window.__how = [];
  const share = window.__shareMode;
  Object.defineProperty(navigator, 'share', { configurable: true, value: share === 'none' ? undefined : async (data) => {
    window.__shared.push(data);
    if (share === 'abort') throw new DOMException('closed', 'AbortError');
    if (share === 'denied') throw new DOMException('no', 'NotAllowedError');
  } });
  const clip = window.__clipMode;
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: clip === 'none' ? undefined : { writeText: async (text) => {
    if (clip === 'denied') throw new DOMException('no', 'NotAllowedError');
    window.__copied.push(text);
  } } });
})();"""


def sharing_page(open_page, share='ok', clipboard='ok'):
    page = open_page(viewport=DESKTOP, init=[f"window.__shareMode = '{share}'; window.__clipMode = '{clipboard}';", STUB])
    pin(page)
    page.evaluate('__pp.game.startDaily(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    return page


def shared(page):
    return page.evaluate('({ shared: window.__shared, copied: window.__copied, dialog: document.getElementById("shareDialog").open })')


def test_share_uses_the_system_sheet_when_there_is_one(open_page):
    page = sharing_page(open_page, share='ok', clipboard='ok')
    text = page.evaluate('__pp.game.report.daily.text')
    page.click('#shareButton')
    page.wait_for_function('window.__shared.length === 1')
    assert shared(page) == {'shared': [{'text': text}], 'copied': [], 'dialog': False}
    assert text.split('\n')[0] == 'Path Patrol · Daily #7 · 2026-09-25' and text.endswith('https://jgohil07.github.io/PathPatrol/')


def test_share_works_from_the_keyboard_alone(open_page):
    page = sharing_page(open_page, share='ok', clipboard='ok')
    assert page.evaluate('document.activeElement.id') == 'shareButton'                    # the card opens with Share focused
    page.keyboard.press('Enter')
    page.wait_for_function('window.__shared.length === 1')
    assert page.evaluate('__pp.state().phase') == 'over'                                   # sharing does not start anything else


def test_closing_the_share_sheet_is_not_a_failure(open_page):
    page = sharing_page(open_page, share='abort', clipboard='ok')
    page.click('#shareButton')
    page.wait_for_function('window.__shared.length === 1')
    frame(page)
    assert shared(page)['copied'] == [] and shared(page)['dialog'] is False              # no clipboard, no dialog: the person chose not to share
    assert 'copied' not in page.locator('#toast').text_content()


def test_when_the_sheet_fails_the_clipboard_is_next_and_it_says_so(open_page):
    page = sharing_page(open_page, share='denied', clipboard='ok')
    text = page.evaluate('__pp.game.report.daily.text')
    page.click('#shareButton')
    page.wait_for_function('window.__copied.length === 1')
    assert shared(page) == {'shared': [{'text': text}], 'copied': [text], 'dialog': False}
    assert page.locator('#toast').text_content().strip() == 'Result copied to the clipboard'
    assert 'Result copied to the clipboard' in page.locator('#announcer').text_content()


def test_with_no_sheet_at_all_the_clipboard_gets_it(open_page):
    page = sharing_page(open_page, share='none', clipboard='ok')
    text = page.evaluate('__pp.game.report.daily.text')
    page.click('#shareButton')
    page.wait_for_function('window.__copied.length === 1')
    assert shared(page) == {'shared': [], 'copied': [text], 'dialog': False}


def test_with_neither_the_text_is_shown_selected_ready_to_copy(open_page):
    page = sharing_page(open_page, share='none', clipboard='denied')
    text = page.evaluate('__pp.game.report.daily.text')
    page.click('#shareButton')
    page.wait_for_function('document.getElementById("shareDialog").open')
    got = page.evaluate("""(() => { const t = document.getElementById('shareText'); return { value: t.value, start: t.selectionStart, end: t.selectionEnd, readonly: t.readOnly, modal: __pp.ui.isModalOpen(), focus: document.activeElement.id }; })()""")
    assert got == {'value': text, 'start': 0, 'end': len(text), 'readonly': True, 'modal': True, 'focus': 'shareText'}      # focused as well as selected: Ctrl+C copies from the focused box
    page.evaluate("document.getElementById('shareText').setSelectionRange(3, 3)")        # the person clicked in the box, leaving a caret rather than a selection...
    page.click('#copyShareButton')                                                      # ...and pressed Copy: even that is refused here, so it tells the person how
    page.wait_for_function('document.getElementById("copyShareButton").textContent !== "Copy"')
    assert page.locator('#copyShareButton').text_content() == 'Press Ctrl+C or Cmd+C'
    got = page.evaluate("(() => { const t = document.getElementById('shareText'); return [document.activeElement.id, t.selectionStart, t.selectionEnd]; })()")
    assert got == ['shareText', 0, len(text)]                                            # the text is selected and focused again, so the advice works
    page.keyboard.press('Escape')
    assert page.evaluate('document.getElementById("shareDialog").open') is False


def test_the_dialogs_copy_button_works_when_the_clipboard_does(open_page):
    page = open_page(viewport=DESKTOP, init=["window.__shareMode = 'none'; window.__clipMode = 'denied';", STUB])
    pin(page)
    page.evaluate('__pp.game.startDaily(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    page.click('#shareButton')
    page.wait_for_function('document.getElementById("shareDialog").open')
    page.evaluate("window.__clipMode = 'ok'; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (t) => { window.__copied.push(t); } } }); 0")
    page.click('#copyShareButton')
    page.wait_for_function('window.__copied.length === 1')
    assert page.locator('#copyShareButton').text_content() == 'Copied'
    page.mouse.click(4, 4)                                                              # the backdrop closes it, as for the other dialogs
    assert page.evaluate('document.getElementById("shareDialog").open') is False


def test_todays_result_can_be_shared_again_from_the_title_and_reads_the_same(open_page):
    page = sharing_page(open_page, share='ok', clipboard='ok')
    text = page.evaluate('__pp.game.report.daily.text')
    page.evaluate('__pp.game.enterTitle()')
    assert page.locator('#shareTodayButton').is_visible()
    page.click('#shareTodayButton')
    page.wait_for_function('window.__shared.length === 1')
    assert shared(page)['shared'] == [{'text': text}]                                    # the stored result reads exactly as the card's did


def test_todays_stored_result_can_be_shared_from_the_title_of_a_fresh_page(open_page):
    """No game-over card any more (the page was reloaded): the text is rebuilt from the record, and reads as it would have."""
    page = open_page(viewport=DESKTOP, init=["window.__shareMode = 'ok'; window.__clipMode = 'ok';", STUB])
    day = page.evaluate("import('/js/rng.js').then((r) => r.dayKey())")
    page.evaluate(f"__pp.storage.updateRecords((r) => {{ r.daily = {{ streak: 2, best: 2, last: '{day}', result: {json.dumps(RESULT)} }}; r.runs = 1; }}); 0")
    page.reload(); page.wait_for_function('window.__pp !== undefined')
    assert page.evaluate('__pp.game.report') is None and page.locator('#shareTodayButton').is_visible()
    want = page.evaluate(f"import('/js/daily.js').then((d) => d.shareText('{day}', {json.dumps(RESULT)}))")
    page.click('#shareTodayButton')
    page.wait_for_function('window.__shared.length === 1')
    assert shared(page)['shared'] == [{'text': want}]
    assert want.split('\n')[1] == 'L4 · 61.5% · 12,480 pts · ■■■□'


def test_there_is_nothing_to_share_before_a_daily_has_been_finished(open_page):
    page = open_page(viewport=DESKTOP, init=["window.__shareMode = 'ok'; window.__clipMode = 'ok';", STUB])
    pin(page)
    assert page.evaluate('__pp.ui.shareResult()') == 'nothing'
    assert page.evaluate('window.__shared.length') == 0


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
