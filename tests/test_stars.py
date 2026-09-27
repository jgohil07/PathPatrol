"""Stars and level select (round 2).

Stars are worked out by hand, as in test_scoring. Level 1 has no obstacles (31,552 open cells, columns 4..235) and a
target of 65 %. A cut down column c with the patrol parked on the right claims columns 4..c: (c - 3) x 136 cells, so c = 160
is 157/232 = 67.7 % (2.7 over the target) and c = 180 is 177/232 = 76.3 % (11.3 over). Rule, pinned here: one star for a
clear, two with no life lost on the level, three with that and either 8 points over the target or a trap."""
import pytest

from test_layout import SIZES          # the eleven screen sizes of the layout matrix

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend, sanitize } = await import('/js/storage.js');
  const { STEP } = await import('/js/config.js');
  const { FIELD } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const fresh = (patrols = [[110, 64]], storage = createStorage(memoryBackend())) => {
    const game = new Game({ storage }); game.enterTitle(); game.newRun();
    place(game, patrols); return { game, storage }; };
  const place = (game, patrols) => { game.level.patrols.length = 0; for (const [x, y] of patrols) game.level.patrols.push(makePatrol(x, y, 0, 0)); };
  const col = (game, cx, y0 = 0, y1 = 144) => { const g = game.grid, out = []; for (let y = y0; y < y1; y++) if (g.get(cx, y) === FIELD) out.push(g.index(cx, y)); return out; };
  const row = (game, cy) => { const g = game.grid, out = []; for (let x = 0; x < g.w; x++) if (g.get(x, cy) === FIELD) out.push(g.index(x, cy)); return out; };
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- the stars ---------------------------------------------------------------------------------------------------------
def test_one_two_or_three_stars_by_the_rules(page):
    got = js(page, """
      const win = (fn) => { const { game, storage } = fresh(); fn(game); return { stars: game.tally && game.tally.stars, cleared: game.level.cleared, phase: game.phase, best: storage.records.stars[1] }; };
      return {
        two: win((g) => g.commitCapture(col(g, 160))),
        margin: win((g) => g.commitCapture(col(g, 180))),
        lostTwo: win((g) => { g.loseLife(); g.commitCapture(col(g, 160)); }),
        lostMargin: win((g) => { g.loseLife(); g.commitCapture(col(g, 180)); }),
        restarted: win((g) => { g.loseLife(); g.restartLevel(); place(g, [[110, 64]]); g.commitCapture(col(g, 160)); }),
      };""")
    assert got['two']['cleared'] == pytest.approx(157 / 232 * 100) and got['two']['phase'] == 'clear'
    assert got['margin']['cleared'] == pytest.approx(177 / 232 * 100)
    assert got['two']['stars'] == 2 and got['margin']['stars'] == 3
    assert got['lostTwo']['stars'] == 1 and got['lostMargin']['stars'] == 1                 # a lost life caps it at one
    assert got['restarted']['stars'] == 2                                                   # a restart is a fresh chance
    assert got['two']['best'] == 2 and got['margin']['best'] == 3


def test_a_trap_on_the_level_earns_the_third_star_without_the_margin(page):
    """Trap the right-hand patrol in 27 x 35 cells (test_trap's cut), then a cut down column 108 on the other side: 136 + 11,016
    + 10,000 cells = 21,152 of 31,552 = 67.0 %, only 2 over the target."""
    got = js(page, """
      const { game } = fresh([[110, 60], [20, 20]]);
      game.commitCapture(col(game, 208)); game.commitCapture(row(game, 104));
      const r = game.commitCapture(col(game, 108, 0, 104));
      return { stars: game.tally.stars, cleared: game.level.cleared, traps: game.run.stats.traps };""")
    assert got['traps'] == 1 and got['cleared'] == pytest.approx(21152 / 31552 * 100)
    assert got['stars'] == 3


def test_the_best_stars_are_kept_and_the_daily_and_the_tutorial_record_none(page):
    got = js(page, """
      const storage = createStorage(memoryBackend());
      let { game } = fresh([[110, 64]], storage); game.commitCapture(col(game, 160));          // 2
      ({ game } = fresh([[110, 64]], storage)); game.loseLife(); game.commitCapture(col(game, 160));      // 1: the 2 stays
      const afterWorse = { ...storage.records.stars };
      const daily = new Game({ storage }); daily.enterTitle(); daily.startDaily(); place(daily, [[110, 64]]); daily.commitCapture(col(daily, 180));
      return { afterWorse, dailyStars: daily.tally.stars, stored: { ...storage.records.stars } };""")
    assert got['afterWorse'] == {'1': 2}
    assert got['dailyStars'] == 3 and got['stored'] == {'1': 2}                              # 3 on the daily's tally, never stored over the 2


def test_the_stored_stars_take_only_levels_1_to_99_with_1_to_3_stars(page):
    got = js(page, """
      const hostile = { '1': 3, '2': 0, '3': 4, '4': 2.5, '5': '2', '0': 1, '100': 2, '99': 1, '-1': 2, '07': 2, 'x': 1, '12': 2 };
      return [hostile, [3, 2], 'lots', null, { __proto__: { '1': 3 } }].map((v) => sanitize({ records: { stars: v } }).records.stars);""")
    assert got == [{'1': 3, '99': 1, '12': 2}, {}, {}, {}, {}]


def test_resetting_the_records_forgets_the_stars(page):
    got = js(page, """
      const { game, storage } = fresh(); game.commitCapture(col(game, 180));
      const before = { ...storage.records.stars }; storage.resetRecords(); return { before, after: storage.records.stars };""")
    assert got == {'before': {'1': 3}, 'after': {}}


# ---- whether a life was lost survives a save ----------------------------------------------------------------------------
def test_a_lost_life_on_a_level_is_saved_and_resumed(page):
    got = js(page, """
      const { game, storage } = fresh(); game.loseLife();
      const raw = storage.loadSnapshot();
      const again = new Game({ storage }); again.enterTitle(); again.resumeRun();
      const bad = (fn) => { const c = JSON.parse(JSON.stringify(raw)); fn(c); return validateSnapshot(c, { today: game.today() }) === null; };
      return { saved: raw.lifeLost, resumed: again.level.lifeLost, missing: bad((c) => { delete c.lifeLost; }), text: bad((c) => { c.lifeLost = 'yes'; }) };""")
    assert got == {'saved': True, 'resumed': True, 'missing': True, 'text': True}


# ---- level select ------------------------------------------------------------------------------------------------------
def test_a_replay_plays_the_campaign_board_and_records_stars_and_nothing_else(page):
    got = js(page, """
      const storage = createStorage(memoryBackend());
      const { game } = fresh([[110, 64]], storage);
      game.commitCapture(col(game, 160));                                                    // level 1 won in the campaign: 2 stars, level 2 unlocked
      game.skipClear = game.skipClear; for (let i = 0; i < 120; i++) game.step(STEP); game.skipClear();
      game.persist(); const savedBefore = JSON.stringify(storage.loadSnapshot());
      const recordsBefore = JSON.parse(JSON.stringify(storage.records));
      game.enterTitle();
      const out = { upTo: game.selectableUpTo(), refusedHigh: game.startSelect(3), refusedPlaying: false };
      const campaign = new Game({ storage: createStorage(memoryBackend()) }); campaign.enterTitle(); campaign.newRun(); campaign.startLevel(2);
      out.started = game.startSelect(2);
      out.refusedPlaying = !game.startSelect(1);
      out.sameBoard = JSON.stringify(game.level.patrols.map((p) => [p.x, p.y, p.vx, p.vy])) === JSON.stringify(campaign.level.patrols.map((p) => [p.x, p.y, p.vx, p.vy]))
        && game.grid.cells.every((v, i) => v === campaign.grid.cells[i]);
      out.mode = game.run.mode; out.lives = game.run.lives;
      place(game, [[110, 64]]); const done = []; game.on('selectDone', (e) => done.push(e.level));
      game.commitCapture(col(game, 180));                                                   // 3 stars on level 2
      out.restartAllowed = null;
      for (let i = 0; i < 120; i++) game.step(STEP); game.skipClear();
      out.after = { phase: game.phase, done, stars: { ...storage.records.stars } };
      const r = storage.records;
      out.untouched = r.bestScore === recordsBefore.bestScore && r.bestClear === recordsBefore.bestClear && r.wins === recordsBefore.wins
        && r.bestLevel === recordsBefore.bestLevel && r.runs === recordsBefore.runs && JSON.stringify(storage.loadSnapshot()) === savedBefore;
      return out;""")
    assert got['upTo'] == 2 and got['refusedHigh'] is False and got['started'] is True and got['refusedPlaying'] is True
    assert got['sameBoard'] and got['mode'] == 'select' and got['lives'] == 3
    assert got['after'] == {'phase': 'title', 'done': [2], 'stars': {'1': 2, '2': 3}}
    assert got['untouched']                                                                 # best score, clear, wins, level, runs, the saved run


def test_a_replay_can_be_restarted_and_its_game_over_leaves_the_saved_run_alone(page):
    got = js(page, """
      const storage = createStorage(memoryBackend());
      const { game } = fresh([[110, 64]], storage); game.commitCapture(col(game, 40)); game.persist();
      storage.updateRecords((r) => { r.bestLevel = 1; });
      const saved = JSON.stringify(storage.loadSnapshot());
      game.enterTitle(); game.startSelect(2);
      const restarted = game.restartLevel();
      for (let i = 0; i < 3; i++) game.loseLife();
      return { restarted, phase: game.phase, report: game.report.mode, newBest: game.report.newBest, same: JSON.stringify(storage.loadSnapshot()) === saved };""")
    assert got['restarted'] is True and got['phase'] == 'over' and got['report'] == 'select'
    assert got['newBest'] == {'score': False, 'clear': False, 'level': False} and got['same'] is True


def test_the_meter_marks_where_three_stars_begin_and_dims_it_after_a_lost_life(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.click('#startButton')
    page.evaluate("__pp.freeze(true); __pp.setPatrols([{ x: 110, y: 60 }, { x: 20, y: 20 }]); 0")
    mark = lambda: page.evaluate("(() => { const m = document.getElementById('starMarker'); return { left: m.style.left, lost: m.classList.contains('lost'), got: m.classList.contains('got') }; })()")    # noqa: E731
    assert mark() == {'left': '73%', 'lost': False, 'got': False}                           # 65 % + 8
    page.evaluate('__pp.cutLine("v", 104); __pp.cutLine("h", 52); 0')                         # a trap: the third star is already earned
    assert mark()['got'] is True
    page.evaluate('__pp.game.loseLife(); 0')
    assert mark() == {'left': '73%', 'lost': True, 'got': False}


def test_the_levels_button_appears_after_a_win_and_the_list_replays_a_level(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    assert page.locator('#levelsButton').is_hidden()
    page.evaluate("__pp.storage.updateRecords((r) => { r.bestLevel = 4; r.stars['1'] = 3; r.stars['2'] = 1; }); __pp.game.enterTitle(); __pp.ui.renderStats(); 0")
    assert page.locator('#levelsButton').is_visible() and page.locator('#levelsButton').text_content() == 'Levels · ★ 4'
    page.click('#levelsButton')
    cells = page.evaluate("[...document.querySelectorAll('#levelGrid .level-cell')].map((c) => [c.dataset.level, c.dataset.special || '', c.getAttribute('aria-label'), c.querySelectorAll('.on').length])")
    assert cells == [['1', '', 'Level 1, 3 of 3 stars', 3], ['2', '', 'Level 2, 1 of 3 stars', 1], ['3', '', 'Level 3, no stars yet', 0],
                     ['4', '', 'Level 4, no stars yet', 0], ['5', 'shape', 'Level 5, odd board, no stars yet', 0]]      # (a special level is marked on sight too)
    assert page.evaluate("document.activeElement.dataset.level") == '5'                    # the newest level has the focus
    assert page.locator('#levelsTotal').text_content() == '★ 4 of 15'
    page.focus('#levelGrid [data-level="4"]')                                              # (Safari's Tab skips buttons unless Option is held)
    page.keyboard.press('Enter')                                                             # level 4, by keyboard
    assert page.evaluate("[__pp.state().phase, __pp.state().mode, __pp.state().level]") == ['playing', 'select', 4]
    assert not page.locator('#levelsDialog').is_visible()
    page.evaluate("__pp.freeze(true); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0")
    assert page.locator('#againButton').text_content() == 'Back to levels' and page.locator('#endEyebrow').text_content() == 'Replay · no lives left'
    page.click('#againButton')
    assert page.locator('#levelsDialog').is_visible() and page.evaluate("document.activeElement.dataset.level") == '4'


def test_a_replay_win_shows_its_stars_and_goes_back_to_the_list(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate("__pp.storage.updateRecords((r) => { r.bestLevel = 1; }); __pp.game.enterTitle(); __pp.game.startSelect(1); __pp.freeze(true); __pp.setPatrols([{ x: 110, y: 64 }]); 0")
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')    # (a scripted start leaves focus on the hidden Start button until a frame has passed)
    page.evaluate("__pp.game.commitCapture((() => { const g = __pp.game.grid, out = []; for (let y = 0; y < g.h; y++) if (g.get(180, y) === 0) out.push(g.index(180, y)); return out; })()); 0")
    stars = page.evaluate("(() => { const s = document.getElementById('clearStars'); return { hidden: s.hidden, lit: s.querySelectorAll('.on').length, label: s.getAttribute('aria-label') }; })()")
    assert stars == {'hidden': False, 'lit': 3, 'label': '3 of 3 stars'}
    assert page.locator('#nextLabel').text_content() == 'Back to levels'
    page.evaluate('__pp.step(90); 0')
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.state().phase') == 'title' and page.locator('#levelsDialog').is_visible()


# ---- the list on every screen ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize('size', SIZES, ids=[s[0] for s in SIZES])
def test_the_level_list_fits_every_screen_and_its_buttons_are_big_enough_to_tap(open_page, size):
    _, width, height, pointer, dpr = size
    touch = pointer == 'touch'
    page = open_page(viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    page.evaluate("__pp.storage.updateRecords((r) => { r.bestLevel = 40; for (let n = 1; n <= 40; n++) r.stars[n] = 1 + (n % 3); }); __pp.game.enterTitle(); __pp.ui.renderStats(); 0")
    page.click('#levelsButton')
    got = page.evaluate("""(() => { const d = document.getElementById('levelsDialog').getBoundingClientRect(); const cells = [...document.querySelectorAll('#levelGrid .level-cell')];
      const r = cells.map((c) => c.getBoundingClientRect());
      return { d: [d.left, d.top, d.right, d.bottom], vw: innerWidth, vh: innerHeight, n: cells.length, minW: Math.min(...r.map((x) => x.width)), minH: Math.min(...r.map((x) => x.height)),
               pageScroll: document.documentElement.scrollWidth > innerWidth }; })()""")
    assert got['n'] == 41
    assert got['d'][0] >= 0 and got['d'][1] >= 0 and got['d'][2] <= got['vw'] and got['d'][3] <= got['vh'], got      # the dialog is on screen (its list scrolls inside)
    assert got['minW'] >= 44 and got['minH'] >= 44, got
    assert not got['pageScroll']
