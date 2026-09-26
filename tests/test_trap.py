"""Trapping (round 2): a capture that shuts a patrol into a pocket of open ground no bigger than 4 % of the level grounds it.

Numbers are worked out by hand, as in test_scoring. Level 1 has no obstacles: its open field is columns 4..235 by rows
4..139, 232 x 136 = 31,552 cells, so the limit is 0.04 x 31,552 = 1,262.08 cells. A cut down column 208 leaves 27 columns
(209..235) on the right; a cut across row y then leaves 27 x (139 - y) cells below it on that side. Pinned here as
literals: a changed limit must fail these tests, not quietly follow them."""
import pytest

PRELUDE = """
  const { Game } = await import('/js/game.js');
  const { createStorage, memoryBackend } = await import('/js/storage.js');
  const { STEP } = await import('/js/config.js');
  const { FIELD, WALL, BORDER, Grid } = await import('/js/grid.js');
  const { makePatrol } = await import('/js/physics.js');
  const { validateSnapshot } = await import('/js/snapshot.js');
  const fresh = (patrols, { mode = 'normal', seed = 'trap' } = {}) => {
    const storage = createStorage(memoryBackend()); const game = new Game({ storage }); game.enterTitle();
    if (mode === 'tutorial') game.startTutorial(); else if (mode === 'extra') game.startExtra(); else game.newRun({ seed });
    game.level.patrols.length = 0; for (const [x, y] of patrols) game.level.patrols.push(makePatrol(x, y, 0, 0));
    const events = []; game.on('trap', (e) => events.push(e));
    return { game, storage, events }; };
  const col = (game, cx) => { const g = game.grid, out = []; for (let y = 0; y < g.h; y++) if (g.get(cx, y) === FIELD) out.push(g.index(cx, y)); return out; };
  const row = (game, cy, x0 = 0, x1 = 240) => { const g = game.grid, out = []; for (let x = x0; x < x1; x++) if (g.get(x, cy) === FIELD) out.push(g.index(x, cy)); return out; };
  const brief = (r) => ({ trapped: r.trapped, capture: r.capturePoints, trap: r.trapPoints, total: r.points, combo: r.combo, mult: r.trapMult, cells: r.cellsClaimed });
"""


def js(page, body, arg=None):
    return page.evaluate("async (arg) => {" + PRELUDE + body + "}", arg)


@pytest.fixture
def page(open_page):
    return open_page()


# ---- the regions ---------------------------------------------------------------------------------------------------
def test_regions_match_a_brute_force_flood_on_random_grids(page):
    got = js(page, """
      let s = 7; const rnd = () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296;
      const bad = [];
      for (let trial = 0; trial < 300; trial++) {
        const w = 6 + Math.floor(rnd() * 30), h = 6 + Math.floor(rnd() * 20), g = new Grid(w, h);
        for (let i = 0; i < w * h; i++) g.cells[i] = rnd() < 0.38 ? WALL : FIELD;
        const groups = [];
        // a group is a cell, sometimes with the cell to its right (a patrol's seeds touch one another, as these do)
        for (let k = 0, n = Math.floor(rnd() * 6); k < n; k++) { const i = Math.floor(rnd() * w * h); groups.push(rnd() < 0.5 && (i % w) < w - 1 ? [i, i + 1] : [i]); }
        const { sizes, owner } = g.regions(groups);
        // the oracle: flood each group on its own, from scratch
        const flood = (seeds) => { const seen = new Set(); const st = seeds.filter((i) => g.cells[i] === FIELD);
          st.forEach((i) => seen.add(i));
          while (st.length) { const i = st.pop(), x = i % w, y = Math.floor(i / w);
            for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) { const nx = x + dx, ny = y + dy, j = ny * w + nx;
              if (nx >= 0 && ny >= 0 && nx < w && ny < h && g.cells[j] === FIELD && !seen.has(j)) { seen.add(j); st.push(j); } } }
          return seen; };
        const sets = groups.map(flood);
        groups.forEach((q, a) => {
          if (sizes[owner[a]] !== sets[a].size && sets[a].size > 0) bad.push([trial, a, 'size', sizes[owner[a]], sets[a].size]);
          groups.forEach((r, b) => { if (b <= a) return;
            const same = [...sets[a]].some((i) => sets[b].has(i));
            if (sets[a].size && sets[b].size && same !== (owner[a] === owner[b])) bad.push([trial, a, b, 'owner']); });
        });
      }
      return bad.slice(0, 5);""")
    assert got == []


# ---- a trap, scored by hand ------------------------------------------------------------------------------------------
def test_a_patrol_shut_in_a_small_pocket_is_grounded_scored_and_raises_the_multiplier(page):
    got = js(page, """
      const { game, events } = fresh([[110, 60], [20, 20]]);
      const out = { caps: [] };
      out.caps.push(brief(game.commitCapture(col(game, 208))));            // splits the field: no pocket small enough yet
      out.after1 = game.level.patrols.length;
      out.caps.push(brief(game.commitCapture(row(game, 104))));            // the right-hand patrol is left in 27 x 35 = 945 cells
      out.after2 = game.level.patrols.map((p) => [p.x, p.y]);
      out.pocket = game.grid.get(220, 130);                                 // where it was: claimed now
      out.events = events.map((e) => ({ n: e.patrols.length, at: [e.patrols[0].x, e.patrols[0].y], points: e.points, mult: e.multiplier, sweep: e.sweep }));
      out.traps = game.run.stats.traps; out.hud = game.hud().trapMult;
      out.caps.push(brief(game.commitCapture(col(game, 180).filter((i) => Math.floor(i / 240) < 104))));   // 27 x 100 + 100 cells, at trap x1.25
      out.score = game.run.score; out.phase = game.phase;
      return out;""")
    first, second, third = got['caps']
    # 1: the column, 136 cells = 34 u2, 0.43 % (under the combo's 0.5 %): 34 points, no trap
    # (cellsClaimed counts what the fill claimed, not the route's own cells)
    assert first == {'trapped': 0, 'capture': 34, 'trap': 0, 'total': 34, 'combo': 1, 'mult': 1, 'cells': 0}
    assert got['after1'] == 2
    # 2: the row (231) + the empty bottom-left (35 x 204 = 7,140) + the empty top-right (100 x 27 = 2,700) + the pocket
    #    (35 x 27 = 945) = 11,016 cells = 2,754 u2, 34.9 % (x1.5 for a big capture): 4,131; the trap 1,500 x combo 1
    assert second == {'trapped': 1, 'capture': 4131, 'trap': 1500, 'total': 5631, 'combo': 1, 'mult': 1, 'cells': 11016 - 231}
    assert got['after2'] == [[20, 20]] and got['pocket'] == 1              # (1 = WALL)
    assert got['events'] == [{'n': 1, 'at': [110, 60], 'points': 1500, 'mult': 1.25, 'sweep': False}]
    assert got['traps'] == 1 and got['hud'] == 1.25
    # 3: 2,800 cells = 700 u2, 8.87 % (no big-capture bonus), combo x1.25 and now trap x1.25: 700 x 1.25 x 1.25 = 1,093.75
    assert third == {'trapped': 0, 'capture': 1094, 'trap': 0, 'total': 1094, 'combo': 1.25, 'mult': 1.25, 'cells': 2800 - 100}
    assert got['score'] == 34 + 5631 + 1094 and got['phase'] == 'playing'


@pytest.mark.parametrize('rows,trapped', [(46, True), (47, False)])
def test_the_pocket_limit_is_four_percent_of_the_level(page, rows, trapped):
    """27 x 46 = 1,242 cells is under 1,262.08; 27 x 47 = 1,269 is over."""
    got = js(page, """
      const { game } = fresh([[110, 68], [20, 20]]);
      game.commitCapture(col(game, 208));
      const r = game.commitCapture(row(game, 139 - arg));
      return { trapped: r.trapped, left: game.level.patrols.length };""", rows)
    assert got == ({'trapped': 1, 'left': 1} if trapped else {'trapped': 0, 'left': 2})


def test_two_patrols_in_one_pocket_are_both_grounded_and_the_trap_pays_times_the_combo(page):
    got = js(page, """
      const { game, events } = fresh([[108, 62], [114, 68], [30, 20]]);
      const warm = game.commitCapture(col(game, 16));                       // columns 4..15: 1,632 cells, 5.2 %: the combo goes to x1.25
      game.commitCapture(col(game, 208));                                   // 0.4 %: the combo stays at x1.25
      const r = brief(game.commitCapture(row(game, 104)));
      return { next: warm.nextCombo, r, left: game.level.patrols.length, traps: game.run.stats.traps, hud: game.hud().trapMult, n: events[0].patrols.length };""")
    assert got['next'] == 1.25 and got['r']['combo'] == 1.25
    assert got['r']['trapped'] == 2 and got['r']['trap'] == 3750 and got['left'] == 1 and got['n'] == 2      # 2 x 1,500 x 1.25
    assert got['traps'] == 2 and got['hud'] == 1.5


def test_the_trap_multiplier_stops_at_two(page):
    got = js(page, """
      const { trapMultiplier } = await import('/js/config.js');
      return [0, 1, 2, 3, 4, 5, 9].map(trapMultiplier);""")
    assert got == [1, 1.25, 1.5, 1.75, 2, 2, 2]


def test_trapping_the_last_patrol_is_a_clean_sweep_that_wins_the_level(page):
    got = js(page, """
      const { game, events } = fresh([[110, 60]]);
      // One L-shaped route round the bottom-right corner: the patrol's side is 27 x 35 = 945 cells, everything else is empty
      const corner = col(game, 208).filter((i) => Math.floor(i / 240) >= 104).concat(row(game, 104, 209, 240));
      const r = brief(game.commitCapture(corner));
      return { r, cleared: game.level.cleared, phase: game.phase, open: game.grid.countField(), sweep: events[0].sweep, patrols: game.level.patrols.length };""")
    assert got['phase'] == 'clear' and got['cleared'] == 100 and got['open'] == 0 and got['patrols'] == 0 and got['sweep'] is True
    assert got['r']['trapped'] == 1


@pytest.mark.parametrize('mode', ['tutorial', 'extra'])
def test_practice_boards_never_trap(page, mode):
    got = js(page, """
      const { game, events } = fresh([[110, 66]], { mode: arg });
      // One L-shaped route shuts the patrol in the bottom-right corner (a pocket under the limit) in a single capture, so the
      // pocket really forms before the practice board can finish.
      const corner = col(game, 208).filter((i) => Math.floor(i / 240) >= 104).concat(row(game, 104, 209, 240));
      const r = game.commitCapture(corner);
      return { captured: r !== null && r.cellsClaimed > 0, trapped: r && r.trapped, left: game.level.patrols.length, events: events.length };""", mode)
    assert got == {'captured': True, 'trapped': 0, 'left': 1, 'events': 0}


# ---- saved runs and restarts --------------------------------------------------------------------------------------------
def test_a_trap_survives_a_save_and_resume_and_a_restart_takes_it_back(page):
    got = js(page, """
      const { game, storage } = fresh([[110, 60], [20, 20]]);
      game.commitCapture(col(game, 208)); game.commitCapture(row(game, 104));
      const raw = storage.loadSnapshot();
      const valid = validateSnapshot(raw, { today: game.today() });
      const again = new Game({ storage }); again.enterTitle();
      const resumed = again.resumeRun();
      const out = { valid: !!valid, v: raw.v, traps: raw.run.stats.traps, resumed, patrols: again.level.patrols.length, hud: again.hud().trapMult,
                    cell: again.grid.get(220, 130) };
      for (let i = 0; i < 400; i++) again.tick(STEP);                        // the 3-2-1 countdown
      again.restartLevel();
      out.afterRestart = { traps: again.run.stats.traps, hud: again.hud().trapMult, patrols: again.level.patrols.length };
      return out;""")
    assert got['valid'] and got['v'] == 3 and got['traps'] == 1 and got['resumed'] is True
    assert got['patrols'] == 1 and got['hud'] == 1.25 and got['cell'] == 1
    assert got['afterRestart']['traps'] == 0 and got['afterRestart']['hud'] == 1


def test_the_validator_accepts_a_level_with_no_patrol_and_rejects_a_bad_trap_count(page):
    got = js(page, """
      const { game, storage } = fresh([[110, 60], [20, 20]]);
      game.commitCapture(col(game, 208));
      const raw = storage.loadSnapshot();
      const out = {};
      out.none = !!validateSnapshot({ ...raw, patrols: [] }, { today: game.today() });
      for (const traps of [-1, 1.5, '2', null, undefined]) {
        const bad = JSON.parse(JSON.stringify(raw)); bad.run.stats.traps = traps; out[String(traps)] = !!validateSnapshot(bad, { today: game.today() }); }
      const old = JSON.parse(JSON.stringify(raw)); old.v = 2; out.v2 = !!validateSnapshot(old, { today: game.today() });
      return out;""")
    assert got == {'none': True, '-1': False, '1.5': False, '2': False, 'null': False, 'undefined': False, 'v2': False}


# ---- how it feels ----------------------------------------------------------------------------------------------------------
def test_a_trap_shows_sparks_a_ring_and_its_word_holds_still_briefly_and_buzzes(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800}, init=['navigator.vibrate = (p) => { (window.__buzz = window.__buzz || []).push(Array.from(p)); return true; };'])
    page.evaluate("__pp.game.newRun({ seed: 'trap' }); __pp.freeze(true); __pp.setPatrols([{ x: 110, y: 60 }, { x: 20, y: 20 }]); 0")
    page.evaluate('__pp.cutLine("v", 104); 0')
    page.evaluate('__pp.fx.clear(); window.__buzz = []; 0')
    page.evaluate('__pp.cutLine("h", 52); 0')
    st = page.evaluate('__pp.fx.stats()')
    words = page.evaluate('__pp.fx.popups.map((p) => p.text)')
    assert 'TRAPPED' in words and st['rings'] >= 1 and st['particles'] >= 36
    hold = page.evaluate('__pp.loop.holdUntil - performance.now()')
    assert 0 < hold <= 70
    assert [30, 20, 12, 20, 12] in page.evaluate('window.__buzz')
    assert page.locator('#comboLabel').text_content().endswith('trap x1.25')


def test_with_reduced_motion_a_lost_life_or_a_trap_does_not_hold_the_board(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_function('__pp.renderer.reducedMotion === true')
    page.evaluate("__pp.game.newRun({ seed: 'trap' }); __pp.freeze(true); __pp.setPatrols([{ x: 110, y: 60 }, { x: 20, y: 20 }]); 0")
    page.evaluate('__pp.cutLine("v", 104); __pp.cutLine("h", 52); __pp.game.loseLife(); 0')
    assert page.evaluate('__pp.state().lives') == 2
    assert page.evaluate('__pp.loop.holdUntil') == float('-inf')


def test_a_lost_life_holds_the_board_for_a_moment(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.evaluate("__pp.game.newRun({ seed: 'trap' }); __pp.freeze(true); __pp.game.loseLife(); 0")
    hold = page.evaluate('__pp.loop.holdUntil - performance.now()')
    assert 0 < hold <= 70
