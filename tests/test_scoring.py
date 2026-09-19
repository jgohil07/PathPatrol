"""Scoring: capture points, the combo, close calls, extra lives, the level-clear tally, restarts and records.

The expected numbers are worked out by hand from the rules, not read back from the code. The board is 240 x 144
cells (a cell is a quarter of a board unit squared), its frame is 4 cells thick, so the open field of a level with
no obstacles is 232 x 136 = 31,552 cells = 7,888 u^2. A cut down column x = 40 u (cell 80) with a patrol parked on
the right claims columns 4..80, that is 77 x 136 = 10,472 cells = 2,618 u^2 = 33.19% of the field."""
import pytest

PRELUDE = """
  const { Game, PHASE } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP, LEVEL_CLEAR_DELAY, CLEAR_SKIP_AFTER, SCORE, MAX_LIVES } = await import('/js/config.js');
  const { FIELD } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const fresh = (patrols = [[100, 60]], seed = 'score') => {
    const storage = createStorage(memoryBackend()); const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed });
    game.level.patrols.length = 0; for (const [x, y] of patrols) game.level.patrols.push(makePatrol(x, y, 0, 0));
    return { game, storage }; };
  const run = (game, seconds) => { for (let i = 0; i < Math.round(seconds / STEP); i++) game.step(STEP); };
  const colCells = (game, unitX) => { const g = game.grid, x = Math.floor(unitX * 2), cells = []; for (let y = 0; y < g.h; y++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); return cells; };
  const rowCells = (game, unitY) => { const g = game.grid, y = Math.floor(unitY * 2), cells = []; for (let x = 0; x < g.w; x++) if (g.get(x, y) === FIELD) cells.push(g.index(x, y)); return cells; };
  const pts = (r) => ({ capture: r.capturePoints, close: r.closePoints, total: r.points, combo: r.combo, next: r.nextCombo, gained: r.gained });
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- capture points and the combo --------------------------------------------------------------------
def test_capture_points_are_the_area_in_board_units_times_the_combo(page):
    got = js(page, """
      const { game } = fresh(); const out = { field: game.level.initialPlayable, caps: [] };
      for (const x of [40, 60, 70]) out.caps.push(pts(game.commitCapture(colCells(game, x))));
      out.score = game.run.score; return out;""")
    assert got['field'] == 31552
    # cut 1: 77 cols x 136 = 10,472 cells = 2,618 u2, 33.19% (>= 10%, so x1.5), combo x1.00   -> 3,927
    # cut 2: 40 cols x 136 =  5,440 cells = 1,360 u2, 17.24% (>= 10%, so x1.5), combo x1.25   -> 1,360 x 1.25 x 1.5 = 2,550
    # cut 3: 20 cols x 136 =  2,720 cells =   680 u2,  8.62% (< 10%, so x1),    combo x1.50   ->   680 x 1.5        = 1,020
    assert [c['capture'] for c in got['caps']] == [3927, 2550, 1020]
    assert [c['combo'] for c in got['caps']] == [1, 1.25, 1.5] and [c['next'] for c in got['caps']] == [1.25, 1.5, 1.75]
    assert got['caps'][0]['gained'] == pytest.approx(10472 / 31552 * 100)
    assert got['score'] == 3927 + 2550 + 1020


def test_the_combo_grows_by_a_quarter_up_to_three(page):
    got = js(page, """
      const { game } = fresh(); const combos = [];
      for (const x of [8, 10, 12, 14, 16, 18, 20, 22, 24, 26]) { game.commitCapture(colCells(game, x)); combos.push(game.run.combo); }
      return { combos };""")
    assert got['combos'] == [1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.0, 3.0]        # capped at x3


def test_a_tiny_capture_neither_grows_nor_breaks_the_combo(page):
    """Checked mid-range: at the x3 cap a wrongly-growing combo would be invisible."""
    got = js(page, """
      const { game } = fresh();
      game.commitCapture(colCells(game, 8)); game.commitCapture(colCells(game, 10));            // x1 -> x1.25 -> x1.5
      const before = game.run.combo;
      // one more column beside the wall: 1 col x 136 = 136 cells = 0.43% < 0.5%, too small to count either way
      const tiny = game.commitCapture(colCells(game, 10.5));
      const after = game.run.combo;
      game.commitCapture(colCells(game, 14));                                                     // a real one still grows it
      return { before, gained: tiny.gained, usedCombo: tiny.combo, after, next: game.run.combo };""")
    assert got['before'] == 1.5 and got['after'] == 1.5 and got['gained'] < 0.5
    assert got['usedCombo'] == 1.5 and got['next'] == 1.75


def test_abandoning_a_route_or_being_hit_breaks_the_combo_but_a_pause_a_restart_or_a_jitter_do_not(page):
    got = js(page, """
      const out = {}; const draw = (game, ps) => { const r = game.route; r.begin(ps[0][0], ps[0][1]); for (const [x, y] of ps.slice(1)) r.move(x, y); };
      const up = (game) => { game.commitCapture(colCells(game, 20)); return game.run.combo; };      // a first capture: x1 -> x1.25
      let { game } = fresh([[100, 60]]); out.start = up(game);
      draw(game, [[60, 1], [60, 20]]); game.route.end('lift');                                     // lifted in the field
      out.afterLift = game.run.combo;
      ({ game } = fresh([[100, 60]])); up(game);
      draw(game, [[60, 1], [60, 20]]); game.route.end('cancel');                                   // the browser took the touch away
      out.afterCancel = game.run.combo;
      ({ game } = fresh([[100, 60]])); up(game);
      draw(game, [[60, 1], [60, 20]]); game.pause('manual');                                       // a pause erases the route for free
      out.afterPause = game.run.combo; game.resume();
      ({ game } = fresh([[100, 60]])); up(game);
      draw(game, [[60, 1], [60, 2.6], [60, 1.5]]);                                                 // a 2-cell scribble at the edge is not a route
      out.afterJitter = game.run.combo; out.jitterCells = game.route.cells.length;
      ({ game } = fresh([[60, 20]])); up(game);
      draw(game, [[60, 1], [60, 30]]);                                                             // straight into a parked patrol
      out.afterHit = game.run.combo; out.livesAfterHit = game.run.lives;
      ({ game } = fresh([[100, 60]])); up(game); game.restartLevel(); out.afterRestart = game.run.combo;
      return out;""")
    assert got['start'] == 1.25
    assert got['afterLift'] == 1 and got['afterCancel'] == 1 and got['afterHit'] == 1 and got['livesAfterHit'] == 2
    assert got['afterPause'] == 1.25 and got['afterJitter'] == 1.25            # neither the pause nor the jitter cost the combo
    assert got['afterRestart'] == 1                                             # a restart begins the level again at x1


# ---- close calls -------------------------------------------------------------------------------------
CLOSE_SETUP = """
  const draw = (game, ps, stepsBetween = 0) => { const r = game.route; r.begin(ps[0][0], ps[0][1]);
    for (const [x, y] of ps.slice(1)) { r.move(x, y); if (stepsBetween) run(game, stepsBetween); } };
"""


def test_a_close_call_is_banked_when_the_route_closes_once_per_patrol(page):
    got = js(page, CLOSE_SETUP + """
      const { game } = fresh([[43, 36], [43, 20], [100, 60]]);       // two patrols 2.75-3 u from the line x = 40, one far away
      const calls = []; game.on('route', (e) => { if (e.type === 'closecall') calls.push(e.patrol); });
      const r = game.route; r.begin(40, 1); r.move(40, 25);
      run(game, 0.2); r.move(40, 40); run(game, 0.2);                 // steps while both are near: still only one call each
      const during = { calls: [...calls], scoreBefore: game.run.score, lives: game.run.lives };
      r.move(40, 71);                                                  // the route closes
      return { during, score: game.run.score, stats: game.run.stats, lastCloseCalls: game.run.stats.closeCalls, lives: game.run.lives, cleared: game.level.cleared }; """)
    assert got['during']['calls'] == [1, 0]                                                  # each patrol once, in the order the route reached them
    assert got['during']['scoreBefore'] == 0 and got['during']['lives'] == 3                # banked only on closing, and nothing hit
    assert got['lastCloseCalls'] == 2
    # the patrols sit on the right, so the left side is claimed: 3,927 for the area, plus 2 close calls x 250 x combo 1
    assert got['score'] == 3927 + 2 * 250


def test_a_close_call_is_not_banked_by_a_route_that_is_lifted_or_far_away(page):
    got = js(page, CLOSE_SETUP + """
      const out = {};
      let { game } = fresh([[43, 36]]);
      draw(game, [[40, 1], [40, 36]], 0.1); run(game, 0.2);
      out.sawIt = game.route.closeCalls.size;                                                    // it really did come close...
      game.route.end('lift');                                                                    // ...then lifted: nothing is paid
      out.lifted = { score: game.run.score, closeCalls: game.run.stats.closeCalls };
      ({ game } = fresh([[46, 36]]));                                                           // 5.75 u away is not a close call
      draw(game, [[40, 1], [40, 36]]); run(game, 0.2); game.route.move(40, 71);
      out.far = { closeCalls: game.run.stats.closeCalls, score: game.run.score };
      ({ game } = fresh([[43, 36]]));                                                           // the same near patrol, then a clean route elsewhere
      draw(game, [[40, 1], [40, 36]]); run(game, 0.2); game.route.end('lift');
      draw(game, [[20, 1], [20, 71]]); out.next = game.run.stats.closeCalls; out.nextScore = game.run.score;     // a new route starts with a clean slate
      return out;""")
    assert got['sawIt'] == 1                                                     # the patrol was near enough to count...
    assert got['lifted'] == {'score': 0, 'closeCalls': 0}                         # ...but a lifted route pays nothing
    assert got['far']['closeCalls'] == 0
    assert got['next'] == 0 and got['nextScore'] > 0                             # the next, clean route scores only for its area


# ---- extra lives -------------------------------------------------------------------------------------
def test_an_extra_life_at_every_25000_points_up_to_five_lives(page):
    got = js(page, """
      const out = {}; const events = [];
      let { game } = fresh(); game.on('extraLife', (e) => events.push(e.lives));
      game.run.score = 24900; game.commitCapture(colCells(game, 40));                  // worth 3,927: crosses 25,000
      out.crossed = { lives: game.run.lives, next: game.run.nextLifeAt, events: [...events] };
      ({ game } = fresh()); game.run.lives = MAX_LIVES; game.run.score = 24900; game.commitCapture(colCells(game, 40));
      out.atMax = { lives: game.run.lives, next: game.run.nextLifeAt };                  // no sixth life, but the threshold moves on
      ({ game } = fresh()); game._addScore(80000);                                       // three thresholds at once: 25k, 50k, 75k
      out.jump = { lives: game.run.lives, next: game.run.nextLifeAt };
      return out;""")
    assert got['crossed'] == {'lives': 4, 'next': 50000, 'events': [4]}
    assert got['atMax'] == {'lives': 5, 'next': 50000}
    assert got['jump'] == {'lives': 5, 'next': 100000}                                    # 3 + 2 (capped), thresholds 25k 50k 75k passed


def test_a_restart_forgets_the_points_but_cannot_earn_the_same_life_twice(page):
    got = js(page, """
      const { game } = fresh(); game.run.score = 24000; game.run.stats.captures = 5;
      game.level.scoreAtStart = 24000; game.level.statsAtStart = { ...game.run.stats };       // as if this level began with 24,000 points and 5 captures
      game.commitCapture(colCells(game, 40));
      const first = { score: game.run.score, lives: game.run.lives, next: game.run.nextLifeAt, captures: game.run.stats.captures };
      game.restartLevel();
      const restarted = { score: game.run.score, lives: game.run.lives, next: game.run.nextLifeAt, captures: game.run.stats.captures, combo: game.run.combo };
      game.level.patrols.length = 0; game.level.patrols.push(makePatrol(100, 60, 0, 0));
      game.commitCapture(colCells(game, 40));                                             // the same capture again
      return { first, restarted, again: { score: game.run.score, lives: game.run.lives, next: game.run.nextLifeAt } };""")
    assert got['first'] == {'score': 24000 + 3927, 'lives': 4, 'next': 50000, 'captures': 6}
    assert got['restarted'] == {'score': 24000, 'lives': 4, 'next': 50000, 'captures': 5, 'combo': 1}     # points and stats roll back, the life stays
    assert got['again'] == {'score': 24000 + 3927, 'lives': 4, 'next': 50000}                               # and it is not earned a second time


# ---- the level-clear tally ---------------------------------------------------------------------------
def test_the_tally_adds_the_bonuses_for_overshoot_lives_and_time(page):
    got = js(page, """
      const out = {};
      let { game } = fresh([]); game.commitCapture(rowCells(game, 36));              // no patrol: the whole field is claimed, 100%
      out.instant = { tally: { ...game.tally }, score: game.run.score, phase: game.phase };
      ({ game } = fresh([])); run(game, 30); game.loseLife(); game.commitCapture(rowCells(game, 36));
      out.slowWithALifeLost = { ...game.tally };
      ({ game } = fresh([])); run(game, 100); game.commitCapture(rowCells(game, 36));
      out.tooSlow = { timeBonus: game.tally.timeBonus };
      ({ game } = fresh([])); game.pause('manual'); run(game, 200); game.resume(); game.commitCapture(rowCells(game, 36));
      out.pausedFirst = { seconds: game.tally.seconds, timeBonus: game.tally.timeBonus };      // a pause is not play time
      return out;""")
    t = got['instant']['tally']
    # whole field: 7,888 u2 x 1.5 = 11,832. Above target: (100 - 65) x 100 = 3,500. Lives 3 x 500 = 1,500. Time (75 - 0) x 10 = 750.
    assert t['capturePoints'] == 11832 and t['overshootBonus'] == 3500 and t['livesBonus'] == 1500 and t['timeBonus'] == 750
    assert t['bonus'] == 5750 and t['total'] == 17582 and t['level'] == 1 and t['lives'] == 3
    assert got['instant']['score'] == 17582 and got['instant']['phase'] == 'clear'
    s = got['slowWithALifeLost']                                                              # 30 s: (75 - 30) x 10 = 450; 2 lives: 1,000
    assert s['timeBonus'] == 450 and s['livesBonus'] == 1000 and s['lives'] == 2
    assert got['tooSlow']['timeBonus'] == 0                                                   # never negative
    assert got['pausedFirst']['timeBonus'] == 750 and got['pausedFirst']['seconds'] == 0


def test_the_win_screen_can_be_skipped_but_not_by_the_tap_that_won(page):
    got = js(page, """
      const { game } = fresh([]); game.commitCapture(rowCells(game, 36));
      const out = { phase: game.phase, pending: game.clock.pending };
      out.tooSoon = game.skipClear();                                                 // the finishing tap must not skip the tally
      run(game, CLEAR_SKIP_AFTER + 0.1);
      out.skipped = game.skipClear();
      out.next = { phase: game.phase, level: game.level.number, combo: game.run.combo, pending: game.clock.pending, tally: game.tally };
      run(game, LEVEL_CLEAR_DELAY + 1);                                               // the cancelled auto-advance must not fire a second time
      out.later = { phase: game.phase, level: game.level.number };
      out.notClear = game.skipClear();
      return out;""")
    assert got['phase'] == 'clear' and got['pending'] == 1 and got['tooSoon'] is False
    assert got['skipped'] is True
    assert got['next'] == {'phase': 'playing', 'level': 2, 'combo': 1, 'pending': 0, 'tally': None}
    assert got['later'] == {'phase': 'playing', 'level': 2} and got['notClear'] is False


# ---- records and the game-over report ------------------------------------------------------------------
def test_best_score_is_kept_live_and_the_report_flags_only_real_records(page):
    got = js(page, """
      const storage = createStorage(memoryBackend()); const out = {};
      const play = (points) => { const game = new Game({ storage }); game.enterTitle(); game.newRun({ seed: 'r' });
        game.level.patrols.length = 0; game.level.patrols.push(makePatrol(100, 60, 0, 0));
        game._addScore(points); const live = storage.records.bestScore;
        game.loseLife(); game.loseLife(); game.loseLife(); return { live, report: game.report }; };
      out.first = play(5000); out.lower = play(3000); out.higher = play(9000); out.tie = play(9000);
      out.stored = storage.records.bestScore; return out;""")
    assert got['first']['live'] == 5000 and got['first']['report']['newBest']['score'] is True
    assert got['lower']['live'] == 5000 and got['lower']['report']['newBest']['score'] is False
    assert got['higher']['report']['newBest']['score'] is True and got['tie']['report']['newBest']['score'] is False   # a tie is not a new best
    assert got['stored'] == 9000
    assert got['first']['report']['score'] == 5000 and got['first']['report']['stats'] == {'captures': 0, 'closeCalls': 0, 'levelsCleared': 0}


# ---- what the player sees --------------------------------------------------------------------------------
def test_the_hud_shows_score_and_combo_and_the_board_never_moves_as_they_grow(open_page):
    """A score gaining digits, a combo appearing and a fifth life must not change the HUD's height: if the HUD
    wrapped onto a third row the board would shrink and jump in the middle of a level."""
    for width, height_px in ((320, 568), (360, 740), (390, 844), (430, 932), (1280, 800)):
        page = open_page(viewport={'width': width, 'height': height_px}, has_touch=width < 700, is_mobile=width < 700)
        page.evaluate('__pp.game.newRun({ seed: "hud" }); __pp.setPatrols([{ x: 100, y: 60 }])')
        geometry = lambda: page.evaluate("""(() => { const r = (s) => { const b = document.querySelector(s).getBoundingClientRect(); return [b.top, b.height, b.width]; };
          return { hud: r('.hud'), canvas: r('#gameCanvas'), fit: __pp.state().fit }; })()""")          # noqa: E731
        settle = lambda: page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')     # noqa: E731
        before = geometry()
        assert page.locator('#scoreLabel').inner_text() == '0' and page.locator('#comboLabel').is_hidden()
        page.evaluate('__pp.cutLine("v", 40)')
        settle()
        assert page.locator('#scoreLabel').inner_text() == '3,927'
        assert page.locator('#comboLabel').is_visible() and page.locator('#comboLabel').text_content() == 'x1.25'
        assert geometry() == before, f'{width}px: the combo appearing moved or resized something'
        page.evaluate('__pp.game.run.score = 1234567; __pp.game.run.combo = 3; __pp.game.run.lives = 5; __pp.game.emit("hud")')
        settle()
        assert page.locator('#scoreLabel').inner_text() == '1,234,567' and page.locator('#comboLabel').text_content() == 'x3.00'
        assert geometry() == before, f'{width}px: a seven-digit score, x3.00 and five lives moved or resized something'


def test_the_win_screen_shows_the_tally_and_moves_on_by_tap_key_or_time(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate('__pp.game.newRun({ seed: "win" }); __pp.freeze(true); __pp.forceWin()')
    assert page.evaluate('__pp.state().phase') == 'clear' and page.locator('#clearOverlay').is_visible()
    assert page.locator('#clearEyebrow').text_content() == 'Level 01 cleared'
    assert page.locator('#clearTotal').text_content() == '+17,582'
    rows = page.evaluate("Object.fromEntries([...document.querySelectorAll('#tally dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent]))")
    assert rows == {'Captures': '+11,832', 'Overshoot 35.0%': '+3,500', 'Lives x3': '+1,500', 'Time 0 s': '+750'}
    assert page.locator('#scoreLabel').inner_text() == '17,582'
    page.keyboard.press('Enter')                                                  # straight away: refused, the tally has not been seen yet
    assert page.evaluate('__pp.state().phase') == 'clear'
    page.evaluate('__pp.step(90)')                                                # 0.75 s of game time
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('__pp.state().level') == 2
    assert page.locator('#clearOverlay').is_hidden()

    page.evaluate('__pp.forceWin(); __pp.step(90)')                                # a click on the overlay, and on its button
    page.locator('#nextButton').click()
    assert page.evaluate('__pp.state().level') == 3


def test_the_game_over_receipt_carries_the_score_and_flags_a_new_best(open_page):
    page = open_page()
    page.evaluate('__pp.game.newRun({ seed: "over" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40)')
    for _ in range(3):
        page.evaluate('__pp.game.loseLife()')
    rows = page.evaluate("Object.fromEntries([...document.querySelectorAll('#receipt dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent]))")
    assert rows == {'Score': 'NEW BEST3,927', 'Level reached': '01', 'Best clear': 'NEW BEST33.2%', 'Captures': '1', 'Close calls': '0'}
    assert page.locator('#endSummary').text_content() == 'A new high score. Go again?'
    page.click('#againButton')
    page.evaluate('__pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife()')          # a worse run: no flags
    rows = page.evaluate("Object.fromEntries([...document.querySelectorAll('#receipt dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent]))")
    assert rows['Score'] == '0' and rows['Best clear'] == '33.2%'
    assert page.locator('#endSummary').text_content() == 'Start fresh and find a cleaner line.'


def test_an_extra_life_is_shown_and_announced(open_page):
    page = open_page()
    page.evaluate('__pp.game.newRun({ seed: "life" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.game.run.score = 24900')
    page.evaluate('__pp.cutLine("v", 40)')                               # its own tick, so the announcer holds only this capture's sentence
    assert page.locator('#lives .life:not(.lost)').count() == 4 and page.locator('#lives').get_attribute('aria-label') == '4 lives'
    heard = page.locator('#announcer').text_content()
    assert heard == '33.2 percent cleared, 3,927 points. Extra life · 4 lives'      # one sentence, and the extra life is said once
