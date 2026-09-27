"""Expert mode (round 3): 15 levels on the 1.0.0 curve, compressed; three lives, no extra lives, no restarts, no stars; its
own boards, records and save slot, and never a trace in the campaign's.

The curve is pinned here as literals, level by level (never read back from config.js): level 1 is 1.0.0's level 6 (3 patrols
at 18.9 u/s, 2 obstacles, 1 tracer, 69 %) and level 15 is 1.0.0's peak (8 patrols at 30 u/s, 6 obstacles, 4 tracers, 75 %).
A level is won here by grounding every patrol and cutting once: with no patrol left, the cut claims the whole board."""
import json

import pytest

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend, sanitize } = await import('/js/storage.js');
  const { STEP, LEVEL_CLEAR_DELAY, CLEAR_SKIP_AFTER, expertInfo, levelInfo, infoFor } = await import('/js/config.js');
  const { Grid, FIELD } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { buildLevel } = await import('/js/level.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const tutored = () => { const backend = memoryBackend(); const storage = createStorage(backend); storage.updateSettings({ tutorialDone: true }); return { backend, storage }; };
  const titled = (storage) => { const game = new Game({ storage }); game.enterTitle(); return game; };
  const place = (game, patrols) => { game.level.patrols.length = 0; for (const [x, y] of patrols) game.level.patrols.push(makePatrol(x, y, 0, 0)); };
  const col = (game, cx) => { const g = game.grid, out = []; for (let y = 0; y < g.h; y++) if (g.get(cx, y) === FIELD) out.push(g.index(cx, y)); return out; };
  const win = (game) => { place(game, []); return game.commitCapture(col(game, 60)); };
  const seconds = (game, s) => { for (let i = 0; i < Math.ceil(s / STEP); i++) game.step(STEP); };
  const lose = (game, n) => { for (let i = 0; i < n; i++) game.loseLife(); };
  const play = (game) => { while (game.phase === 'countdown') game.tick(1); return game; };         // a resumed run counts down 3-2-1 first
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


S, SC, B, H, X = 'standard', 'scout', 'bomber', 'hunter', 'boss'
# level: (patrols, speed, target, obstacles, tracers, kinds, special, valley)
CURVE = {
    1: (3, 18.9, 69, 2, 1, [S, S, S], None, False),
    2: (3, 19.7, 69, 2, 1, [S, S, SC], None, False),
    3: (3, 20.5, 69, 2, 1, [S, S, SC], None, False),
    4: (4, 21.3, 70, 2, 1, [S, S, S, SC], None, False),
    5: (4, 22.1, 70, 3, 1, [S, S, S, SC], 'shape', False),
    6: (4, 22.9, 71, 3, 2, [S, S, SC, B], None, True),
    7: (5, 23.7, 71, 3, 2, [S, S, S, SC, B], None, False),
    8: (5, 24.5, 72, 4, 2, [S, S, SC, B, H], None, False),
    9: (5, 25.2, 72, 4, 2, [S, S, SC, B, H], None, False),
    10: (6, 26.0, 72, 4, 2, [X, S, S, SC, B, H], 'boss', False),
    11: (6, 26.8, 73, 4, 3, [S, S, S, SC, B, H], None, True),
    12: (6, 27.6, 73, 5, 3, [S, S, S, SC, B, H], None, False),
    13: (7, 28.4, 74, 5, 3, [S, S, S, S, SC, B, H], None, False),
    14: (7, 29.2, 74, 5, 3, [S, S, S, S, SC, B, H], None, False),
    15: (8, 30.0, 75, 6, 4, [X, S, S, S, S, SC, B, H], 'finale', False),
}
SPEED = {S: 1, SC: 1.35, B: 0.7, H: 0.9, X: 0.6}          # each kind's speed, as a multiple of the level's (round 2's table)


# ---- the curve ---------------------------------------------------------------------------------------------------------
def test_the_expert_curve_level_by_level(page):
    got = js(page, "const out = {}; for (let e = 0; e <= 16; e++) out[e] = expertInfo(e); return out;")
    for e, (patrols, speed, target, obstacles, tracers, kinds, special, valley) in CURVE.items():
        info = got[str(e)]
        assert (info['level'], info['patrols'], info['target'], info['obstacles'], info['tracers']) == (e, patrols, target, obstacles, tracers), e
        assert info['speed'] == pytest.approx(speed, abs=1e-9), e
        assert info['kinds'] == kinds and info['special'] == special and info['valley'] is valley and info['powerups'] is True, e
    assert got['0']['level'] == 1 and got['16']['level'] == 15                 # outside 1-15: the nearest end
    for knob in ('patrols', 'speed', 'target', 'obstacles', 'tracers'):         # no knob ever goes down
        values = [got[str(e)][knob] for e in range(1, 16)]
        assert values == sorted(values), knob


def test_the_mode_picks_the_curve_and_the_campaign_curve_is_unchanged(page):
    got = js(page, """
      const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      const ok = [];
      for (let n = 1; n <= 40; n++) ok.push(same(infoFor('normal', n), levelInfo(n)) && same(infoFor('daily', n), levelInfo(n)) && same(infoFor(null, n), levelInfo(n)));
      for (let n = 1; n <= 15; n++) ok.push(same(infoFor('expert', n), expertInfo(n)));
      return { ok, l10: levelInfo(10), l15: levelInfo(15), l31: levelInfo(31) };""")
    assert all(got['ok'])
    # round 2's campaign, spot-pinned where the kinds code was touched
    assert got['l10']['kinds'] == [X, SC] and got['l10']['special'] == 'boss'
    assert got['l15']['kinds'] == [S, SC, B] and got['l15']['special'] == 'shape'
    assert got['l31']['kinds'] == [S, S, S, SC, B, H] and got['l31']['patrols'] == 6


def test_expert_boards_follow_their_curve_on_their_own_seed(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage); game.startExpert();
      const out = { seed: game.run.seed, levels: {} };
      for (let e = 1; e <= 15; e++) {
        game.startLevel(e);
        const campaign = buildLevel(e, 'pathpatrol-campaign', new Grid(), expertInfo(e));      // the same numbers on the campaign's seed
        out.levels[e] = { kinds: game.level.patrols.map((p) => p.kind).sort(), speeds: game.level.patrols.map((p) => [p.kind, p.speed]),
                          shape: !!game.level.shape, obstacles: game.level.obstacles.length, tracers: game.tracers.list.length,
                          sameAsCampaignSeed: JSON.stringify(campaign.obstacles) === JSON.stringify(game.level.obstacles) };
      }
      return out;""")
    assert got['seed'] == 'pathpatrol-expert'
    for e, (patrols, speed, target, obstacles, tracers, kinds, special, valley) in CURVE.items():
        lv = got['levels'][str(e)]
        assert lv['kinds'] == sorted(kinds), e
        for kind, v in lv['speeds']:
            assert v == pytest.approx(speed * SPEED[kind], abs=1e-9), (e, kind)
        assert lv['shape'] == (e in (5, 15)), e                              # the odd boards: level 5 and the finale
        assert lv['obstacles'] == obstacles and lv['tracers'] == tracers, e
        assert not lv['sameAsCampaignSeed'], e                                # its own boards


# ---- the rules ---------------------------------------------------------------------------------------------------------
def test_an_expert_run_starts_from_the_title_with_three_lives_and_counts_only_its_own_runs(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage);
      const toasts = []; game.on('toast', (t) => toasts.push(t.text));
      const started = game.startExpert();
      const again = game.startExpert();                        // not from a level
      return { started, again, mode: game.run.mode, level: game.level.number, lives: game.run.lives, toast: toasts[0],
               expert: { ...storage.records.expert }, runs: storage.records.runs };""")
    assert got['started'] is True and got['again'] is False
    assert got['mode'] == 'expert' and got['level'] == 1 and got['lives'] == 3
    assert got['toast'] == 'Expert 01/15 · clear 69%'
    assert got['expert'] == {'best': 0, 'bestScore': 0, 'finished': 0, 'runs': 1} and got['runs'] == 0


def test_expert_grants_no_extra_life_but_the_threshold_moves_on(page):
    got = js(page, """
      const { storage } = tutored();
      const expert = titled(storage); expert.startExpert(); expert._addScore(30000);
      const campaign = titled(createStorage(memoryBackend())); campaign.newRun(); campaign._addScore(30000);
      expert.persist();
      return { expert: [expert.run.lives, expert.run.nextLifeAt], campaign: [campaign.run.lives, campaign.run.nextLifeAt],
               readable: validateSnapshot(storage.loadSnapshot('expert'), { slot: 'expert' }) !== null, best: storage.records.expert.bestScore };""")
    assert got['expert'] == [3, 50000]                                      # past 25,000: no life, but the next threshold is above the score
    assert got['campaign'] == [4, 50000]                                    # (the campaign's rule, for contrast)
    assert got['readable'] is True and got['best'] == 30000


def test_expert_cannot_be_restarted(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage); game.startExpert(); game.loseLife();
      const playing = game.restartLevel(); game.pause('manual'); const paused = game.restartLevel();
      return { playing, paused, lives: game.run.lives };""")
    assert got == {'playing': False, 'paused': False, 'lives': 2}


def test_expert_has_no_stars_and_keeps_its_own_records(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage); game.startExpert(); win(game);
      return { phase: game.phase, stars: game.tally.stars, bestStars: game.tally.bestStars, starLine: game.hud().starLine,
               records: JSON.parse(JSON.stringify(storage.records)) };""")
    assert got['phase'] == 'clear' and got['stars'] is None and got['bestStars'] is None and got['starLine'] is None
    r = got['records']
    assert r['stars'] == {} and r['wins'] == 0 and r['bestLevel'] == 0 and r['bestClear'] == 0 and r['bestScore'] == 0 and r['runs'] == 0
    assert r['expert']['best'] == 1 and r['expert']['bestScore'] > 0 and r['expert']['runs'] == 1 and r['expert']['finished'] == 0


def test_winning_level_15_finishes_the_run(page):
    got = js(page, """
      const run = (finish) => {
        const { storage } = tutored(); const game = titled(storage); game.startExpert(); game.startLevel(15);
        const savedBefore = storage.loadSnapshot('expert') !== null;
        win(game);
        const atTally = { phase: game.phase, last: game.tally.last, saved: storage.loadSnapshot('expert'), expert: { ...storage.records.expert } };
        finish(game);
        return { savedBefore, atTally, phase: game.phase, report: game.report && { finished: game.report.finished, level: game.report.level, newBest: game.report.newBest } };
      };
      return { waited: run((g) => seconds(g, LEVEL_CLEAR_DELAY + 0.1)), skipped: run((g) => { seconds(g, CLEAR_SKIP_AFTER + 0.05); g.skipClear(); }) };""")
    for how in ('waited', 'skipped'):
        r = got[how]
        assert r['savedBefore'] is True
        assert r['atTally']['phase'] == 'clear' and r['atTally']['last'] is True
        assert r['atTally']['saved'] is None                                 # won: nothing to resume, from the moment of the win
        assert r['atTally']['expert']['finished'] == 1 and r['atTally']['expert']['best'] == 15
        assert r['phase'] == 'over', how                                     # not a level 16
        assert r['report']['finished'] is True and r['report']['level'] == 15 and r['report']['newBest']['level'] is True


def test_an_expert_game_over_clears_only_the_expert_save(page):
    got = js(page, """
      const { storage } = tutored();
      const campaign = titled(storage); campaign.newRun(); campaign.persist(); const campaignSave = JSON.stringify(storage.loadSnapshot('run'));
      const game = titled(storage); game.startExpert(); win(game); seconds(game, LEVEL_CLEAR_DELAY + 0.1); lose(game, 3);
      return { phase: game.phase, finished: game.report.finished, newBest: game.report.newBest, expertSave: storage.loadSnapshot('expert'),
               campaignKept: JSON.stringify(storage.loadSnapshot('run')) === campaignSave, report: game.report.expert };""")
    assert got['phase'] == 'over' and got['finished'] is False and got['expertSave'] is None and got['campaignKept'] is True
    assert got['newBest'] == {'score': True, 'clear': False, 'level': True}
    assert got['report']['best'] == 1


# ---- never a trace in the campaign's, and the other way round -----------------------------------------------------------
CAMPAIGN_KEYS = """
  const records = (storage) => { const r = JSON.parse(JSON.stringify(storage.records)); delete r.expert; return JSON.stringify(r); };
"""


def test_expert_never_touches_the_campaigns_records_stars_or_saved_run(page):
    got = js(page, CAMPAIGN_KEYS + """
      const { backend, storage } = tutored();
      const c = titled(storage); c.newRun(); place(c, [[110, 64]]); c.commitCapture(col(c, 180)); seconds(c, LEVEL_CLEAR_DELAY + 0.1);
      c.commitCapture(col(c, 40)); c.loseLife(); c.persist();                       // a campaign run in progress on level 2, with stars on level 1
      const before = { run: backend.getItem('pathpatrol:v2:run'), records: records(storage) };
      let g = titled(storage); g.startExpert(); g.loseLife(); win(g); seconds(g, LEVEL_CLEAR_DELAY + 0.1); g.persist();
      g = titled(storage); g.startExpert(); play(g); lose(g, 2);                  // resumed, then over
      g = titled(storage); g.startExpert(); g.startLevel(15); g._addScore(80000); win(g); seconds(g, LEVEL_CLEAR_DELAY + 0.1);     // finished
      const over = g.report.finished;
      g = titled(storage); g.startExpert(); win(g);                              // a lower level won later: the best stays 15
      const after = { run: backend.getItem('pathpatrol:v2:run'), records: records(storage) };
      const back = titled(storage);
      return { before, after, stars: storage.records.stars, expert: storage.records.expert, offered: back.saved && back.saved.level, over };""")
    assert got['before']['run'] is not None and got['stars'] == {'1': 3}
    assert got['after'] == got['before']                                       # byte for byte
    assert got['offered'] == 2 and got['over'] is True
    assert got['expert'] == {'best': 15, 'bestScore': got['expert']['bestScore'], 'finished': 1, 'runs': 3} and got['expert']['bestScore'] >= 80000


def test_the_campaign_and_the_daily_never_touch_expert_records_or_its_save(page):
    got = js(page, """
      const { backend, storage } = tutored();
      const g = titled(storage); g.startExpert(); g._addScore(1234); win(g); seconds(g, LEVEL_CLEAR_DELAY + 0.1); g.loseLife();
      const before = { save: backend.getItem('pathpatrol:v2:expert'), expert: JSON.stringify(storage.records.expert) };
      const c = titled(storage); c.newRun(); c._addScore(999999); place(c, [[110, 64]]); c.commitCapture(col(c, 180)); seconds(c, LEVEL_CLEAR_DELAY + 0.1); lose(c, 9);
      const d = titled(storage); d.startDaily(); lose(d, 3);
      const back = titled(storage);
      return { before, after: { save: backend.getItem('pathpatrol:v2:expert'), expert: JSON.stringify(storage.records.expert) },
               offered: back.savedExpert && [back.savedExpert.level, back.savedExpert.run.lives] };""")
    assert got['before']['save'] is not None
    assert got['after'] == got['before']
    assert got['offered'] == [2, 2]


# ---- storage and saves -------------------------------------------------------------------------------------------------
def test_the_stored_expert_records_are_sanitised_field_by_field(page):
    cases = [None, 'x', 7, [], {}, {'best': 16}, {'best': -1}, {'best': 3.5}, {'best': '7'},
             {'best': 7, 'bestScore': -5, 'finished': 'a', 'runs': 1e300}, {'best': 15, 'bestScore': 123, 'finished': 2, 'runs': 9, 'extra': 'x'}]
    got = js(page, "return arg.map((expert) => sanitize({ records: { expert } }).records.expert);", cases)
    zero = {'best': 0, 'bestScore': 0, 'finished': 0, 'runs': 0}
    assert got[:9] == [zero] * 9
    assert got[9] == {'best': 7, 'bestScore': 0, 'finished': 0, 'runs': 0}
    assert got[10] == {'best': 15, 'bestScore': 123, 'finished': 2, 'runs': 9}


def test_an_expert_run_saves_in_its_own_slot_and_resumes_from_it(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage); game.startExpert(); game.startLevel(3);
      place(game, [[110, 64]]); game.commitCapture(col(game, 40)); game.loseLife();
      const score = game.run.score, cleared = game.level.cleared;
      const back = titled(storage);
      const offered = { expert: back.savedExpert && back.savedExpert.level, campaign: back.saved };
      const resumed = back.startExpert();
      return { offered, resumed, mode: back.run.mode, level: back.level.number, lives: back.run.lives, score: back.run.score === score,
               cleared: Math.abs(back.level.cleared - cleared) < 1e-9, phase: back.phase, runs: storage.records.expert.runs };""")
    assert got['offered'] == {'expert': 3, 'campaign': None}
    assert got['resumed'] is True and got['mode'] == 'expert' and got['level'] == 3 and got['lives'] == 2
    assert got['score'] is True and got['cleared'] is True and got['phase'] in ('paused', 'countdown')
    assert got['runs'] == 1                                                   # a resumed run is not a new one


def test_the_validator_takes_expert_runs_only_from_their_slot_and_only_as_they_can_be(page):
    got = js(page, """
      const { storage } = tutored(); const game = titled(storage); game.startExpert(); game.startLevel(4);
      place(game, [[110, 64]]); game.commitCapture(col(game, 40)); game.persist();
      const raw = storage.loadSnapshot('expert');
      const c = titled(storage); c.newRun(); c.persist(); const campaign = storage.loadSnapshot('run');
      const check = (fn, slot = 'expert') => { const x = JSON.parse(JSON.stringify(raw)); fn(x); return validateSnapshot(x, { slot }) !== null; };
      return {
        good: check(() => {}), inRunSlot: check(() => {}, 'run'),
        campaignInExpertSlot: validateSnapshot(campaign, { slot: 'expert' }) !== null, campaignInItsSlot: validateSnapshot(campaign, { slot: 'run' }) !== null,
        level15: check((x) => { x.level = 15; x.tracers = x.tracers.concat([[0, 0, 1], [0, 0, 1], [0, 0, 1]]); }),
        level16: check((x) => { x.level = 16; x.fresh = true; }), fresh15: check((x) => { x.level = 15; x.fresh = true; }),
        tracers: check((x) => { x.tracers.push([0, 0, 1]); }), campaignTracers: check((x) => { x.mode = 'normal'; }, 'run'),
        lives3: check((x) => { x.run.lives = 3; }), lives4: check((x) => { x.run.lives = 4; }),
        tracerCount: raw.tracers.length,
      };""")
    assert got['tracerCount'] == 1                                            # expert level 4: one tracer (the campaign's level 4 has none)
    assert got['good'] is True and got['inRunSlot'] is False
    assert got['campaignInExpertSlot'] is False and got['campaignInItsSlot'] is True
    assert got['level15'] is True and got['fresh15'] is True and got['level16'] is False
    assert got['tracers'] is False and got['campaignTracers'] is False       # tracers are counted by the mode's own curve
    assert got['lives3'] is True and got['lives4'] is False                   # expert never has more than three


def test_the_tutorial_leads_on_into_expert(page):
    got = js(page, """
      const fresh = () => { const storage = createStorage(memoryBackend()); return titled(storage); };
      const a = fresh(); a.startTutorial({ origin: 'expert' }); const skipped = a.skipTutorial();
      const b = fresh(); b.startTutorial({ origin: 'expert' }); b.finishTutorial({ percent: 12 }); seconds(b, CLEAR_SKIP_AFTER + 0.05); const moved = b.skipClear();
      return { skipped, a: [a.run.mode, a.level.number, a.storage.settings.tutorialDone], moved, b: [b.run.mode, b.level.number] };""")
    assert got['skipped'] is True and got['a'] == ['expert', 1, True]
    assert got['moved'] is True and got['b'] == ['expert', 1]


# ---- the screens ---------------------------------------------------------------------------------------------------------
from test_layout import SIZES, MEASURE, check, settle, OUT, SET_NOTICE, DAILY_DONE          # noqa: E402  (the layout matrix's own sizes and checks)

FRAMES2 = 'new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))'


def test_the_expert_button_is_on_the_title_from_the_first_launch_and_starts_a_run(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    assert page.evaluate('__pp.storage.records.runs') == 0 and page.locator('#expertButton').is_visible()
    assert page.locator('#expertLabel').text_content() == 'Expert'
    assert page.get_attribute('#expertButton', 'aria-label') == 'Expert mode, 15 hard levels'
    page.click('#expertButton')
    assert page.evaluate('[__pp.state().phase, __pp.state().mode, __pp.state().level]') == ['playing', 'expert', 1]
    assert page.locator('#levelLabel').text_content() == 'E01'
    assert page.locator('#starMarker').is_hidden()                                           # no stars in expert
    assert page.locator('#restartButton').is_disabled()                                      # and no restarts
    page.evaluate("__pp.game.pause('manual'); 0")
    assert page.locator('#pauseRestartButton').is_hidden()


def test_the_first_expert_press_on_a_new_device_runs_the_tutorial_first(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800}, tutorial=True)
    page.click('#expertButton')
    assert page.evaluate('[__pp.state().phase, __pp.state().mode]') == ['playing', 'tutorial']
    page.evaluate('__pp.game.skipTutorial(); 0')
    assert page.evaluate('[__pp.state().mode, __pp.state().level]') == ['expert', 1]


def test_a_saved_expert_run_is_offered_on_the_expert_button_and_resumed_from_it(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate('__pp.game.startExpert(); __pp.game.startLevel(7); __pp.game.persist(); __pp.game.enterTitle(); 0')
    assert page.locator('#expertLabel').text_content() == 'Resume expert · 07'
    assert page.get_attribute('#expertButton', 'aria-label') == 'Resume expert run, level 7 of 15'
    assert page.locator('#resumeRunButton').is_hidden()                                     # the campaign's Resume is for the campaign's run only
    page.click('#expertButton')
    page.evaluate('__pp.game.resume(); 0')
    assert page.evaluate('[__pp.state().mode, __pp.state().level]') == ['expert', 7]


def test_the_expert_tally_has_no_stars_and_the_last_level_finishes(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate('__pp.game.startExpert(); __pp.freeze(true); 0')
    page.evaluate(FRAMES2)
    page.evaluate('__pp.forceWin(); 0')
    assert page.evaluate('__pp.state().phase') == 'clear'
    assert page.locator('#clearEyebrow').text_content() == 'Expert 01/15 cleared' and page.locator('#clearStars').is_hidden()
    assert page.locator('#nextLabel').text_content() == 'Next level'
    page.evaluate('__pp.game.startLevel(15); __pp.freeze(true); 0')
    page.evaluate(FRAMES2)
    page.evaluate('__pp.forceWin(); 0')
    assert page.locator('#nextLabel').text_content() == 'Finish'
    page.evaluate("window.__sounds = []; __pp.sound.clear = () => __sounds.push('win'); __pp.sound.over = () => __sounds.push('lose'); __pp.step(90); 0")
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.state().phase') == 'over'
    assert page.evaluate('__sounds') == ['win']                                              # a finish sounds like a win, not a game over
    assert page.locator('#endEyebrow').text_content() == 'Expert · all 15 cleared'
    assert page.locator('#endTitle').text_content() == 'Expert cleared.'
    assert page.locator('#againLabel').text_content() == 'New expert run' and page.locator('#shareButton').is_hidden()
    rows = page.evaluate("[...document.querySelectorAll('#receipt dt')].map((d) => d.textContent)")
    assert rows == ['Score', 'Levels cleared', 'Best level cleared', 'Captures', 'Close calls']
    assert page.locator('#endSummary').text_content() == 'Finished 1 time. Few ever do.'
    page.evaluate('document.activeElement.blur(); 0')
    page.keyboard.press('Enter')                                                             # nothing focused, the obvious next step: another expert run
    assert page.evaluate('[__pp.state().phase, __pp.state().mode, __pp.state().level]') == ['playing', 'expert', 1]
    page.evaluate('__pp.freeze(true); __pp.game.newRun(); __pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    assert page.locator('#endTitle').text_content() == 'Run interrupted.' and page.locator('#endEyebrow').text_content() == 'No lives left'     # a campaign card after the finish card


def test_an_expert_game_over_card_and_new_expert_run(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate("window.__sounds = []; __pp.sound.clear = () => __sounds.push('win'); __pp.sound.over = () => __sounds.push('lose'); 0")
    page.evaluate('__pp.game.startExpert(); __pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    assert page.evaluate('__pp.state().phase') == 'over' and page.evaluate('__sounds') == ['lose']
    assert page.locator('#endEyebrow').text_content() == 'Expert · no lives left' and page.locator('#endTitle').text_content() == 'Run interrupted.'
    assert page.evaluate("[...document.querySelectorAll('#receipt dt')].map((d) => d.textContent)")[1] == 'Level reached'
    page.click('#againButton')
    assert page.evaluate('[__pp.state().phase, __pp.state().mode, __pp.state().level]') == ['playing', 'expert', 1]
    page.evaluate('__pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.newRun(); __pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    assert page.locator('#endTitle').text_content() == 'Run interrupted.' and page.locator('#againLabel').text_content() == 'New run'      # a campaign card after an expert one
    assert page.locator('#endEyebrow').text_content() == 'No lives left'


def test_the_expert_records_show_in_stats_and_on_the_title(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    assert page.locator('#expertRecord').text_content() == '—'
    page.evaluate("__pp.storage.updateRecords((r) => { r.expert = { best: 9, bestScore: 123456, finished: 0, runs: 4 }; }); __pp.ui.renderStats(); 0")
    assert page.locator('#expertRecord').text_content() == 'level 09/15 · best 123,456'
    assert page.locator('#titleRecords').text_content() == '> expert 09/15'                # no campaign run yet: only expert's
    page.evaluate("__pp.storage.updateRecords((r) => { r.expert.finished = 2; r.runs = 3; r.bestScore = 5000; }); __pp.ui.renderStats(); 0")
    assert page.locator('#expertRecord').text_content() == 'level 09/15 · best 123,456 · finished 2×'
    assert page.locator('#titleRecords').text_content() == '> best 5,000 · expert 09/15 · 3 runs'


def test_help_explains_expert(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    text = page.locator('.how-expert').text_content()
    assert 'three lives, no extra lives, no restarts' in text and 'fifteenth' in text


@pytest.mark.parametrize('size', SIZES, ids=[s[0] for s in SIZES])
def test_the_tallest_title_with_expert_fits_every_screen_size(open_page, engine, size):
    """A plain title (records, nothing saved, the daily open) and the tallest title there is (a campaign run and an expert run
    saved, today's daily played, an update on offer). The Expert button is one more row on a narrow phone; the short-screen
    rules make the room."""
    name, width, height, mode, dpr = size
    touch = mode == 'touch'
    page = open_page(viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    OUT.mkdir(parents=True, exist_ok=True)
    page.evaluate("__pp.storage.updateRecords((r) => { r.runs = 12; r.bestScore = 1234567; r.bestClear = 61.5; r.bestLevel = 11; r.stars['1'] = 3; r.expert = { best: 11, bestScore: 987654, finished: 1, runs: 6 }; }); __pp.ui.renderStats(); 0")
    settle(page)
    assert page.evaluate('__pp.state().phase') == 'title' and page.locator('#expertButton').is_visible() and page.locator('#resumeRunButton').is_hidden()
    check(page.evaluate(MEASURE), touch, f'{name} plain title with expert')
    page.screenshot(path=str(OUT / f'{engine}-{name}-19-title-expert-plain.png'))
    page.evaluate('__pp.game.startExpert(); __pp.game.startLevel(12); __pp.game.run.score = 987654; __pp.game.run.nextLifeAt = 1000000; __pp.game.persist(); __pp.game.enterTitle(); 0')
    page.evaluate('__pp.game.newRun({ seed: "saved" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40); __pp.game.run.score = 1234567; __pp.game.run.nextLifeAt = 1250000; __pp.game.persist(); __pp.game.enterTitle(); 0')
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    page.wait_for_function('__pp.state().frames > 3')
    page.evaluate(DAILY_DONE)
    page.evaluate("__pp.storage.updateRecords((r) => { r.expert = { best: 11, bestScore: 987654, finished: 1, runs: 6 }; }); __pp.ui.renderStats(); 0")
    page.evaluate(SET_NOTICE, 'update')
    settle(page)
    assert page.evaluate('__pp.state().phase') == 'title'
    assert page.locator('#resumeRunButton').is_visible() and page.locator('#shareTodayButton').is_visible() and page.locator('#expertButton').is_visible()
    assert page.locator('#expertLabel').text_content() == 'Resume expert · 12'
    check(page.evaluate(MEASURE), touch, f'{name} tallest title with expert')
    page.screenshot(path=str(OUT / f'{engine}-{name}-20-title-expert-tallest.png'))
    # and the expert end card, which has its own rows
    page.evaluate("__pp.game.startExpert(); __pp.game.tick(5); __pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0")      # (the saved run resumes with a 3-2-1)
    settle(page)
    assert page.evaluate('[__pp.state().phase, __pp.state().mode]') == ['over', 'expert']
    check(page.evaluate(MEASURE), touch, f'{name} expert game over')
    page.screenshot(path=str(OUT / f'{engine}-{name}-21-over-expert.png'))
