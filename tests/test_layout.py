"""Responsive layout on every screen size from a small phone to a wide desktop, on both engines.

Each size is checked as numbers (nothing overflows, the board is fully visible and as large as it can be,
the HUD never overlaps it, every button is big enough to press) and saved as screenshots under
test-results/layout/ so a person can look at them too. Phones and tablets are emulated with real touch
capabilities, because the layout switches on (pointer: coarse), never on the device's name."""
import pathlib

import pytest

OUT = pathlib.Path(__file__).resolve().parents[1] / 'test-results' / 'layout'

# name, width, height, input, device pixel ratio
SIZES = [
    ('phone-320x568', 320, 568, 'touch', 2),
    ('phone-360x740', 360, 740, 'touch', 3),
    ('phone-390x844', 390, 844, 'touch', 3),
    ('phone-430x932', 430, 932, 'touch', 3),
    ('phone-landscape-844x390', 844, 390, 'touch', 3),
    ('phone-landscape-932x430', 932, 430, 'touch', 3),
    ('tablet-portrait-768x1024', 768, 1024, 'touch', 2),
    ('tablet-landscape-1024x768', 1024, 768, 'touch', 2),
    ('laptop-1280x800', 1280, 800, 'mouse', 1),
    ('desktop-1440x900', 1440, 900, 'mouse', 1),
    ('desktop-1920x1080', 1920, 1080, 'mouse', 1),
]

MEASURE = """() => {
  const box = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
  const shown = (el) => { const s = getComputedStyle(el); return s.display !== 'none' && s.visibility !== 'hidden' && el.getClientRects().length > 0; };
  const q = (s) => document.querySelector(s);
  const stage = q('#stage'), cs = getComputedStyle(stage);
  const content = { w: stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
                    h: stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) };
  const vw = innerWidth, vh = innerHeight;
  const outside = [];
  for (const el of document.querySelectorAll('.chrome *, .hints *, .board')) {
    if (!shown(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (r.left < -0.5 || r.right > vw + 0.5 || r.top < -0.5 || r.bottom > vh + 0.5) outside.push((el.id || el.className || el.tagName) + ' [' + [r.left, r.top, r.right, r.bottom].map(Math.round) + ']');
  }
  const buttons = [...document.querySelectorAll('button')].filter(shown).map((b) => { const r = b.getBoundingClientRect(); return { name: b.id || b.textContent.trim(), w: r.width, h: r.height }; });
  const panel = (sel) => { const p = q(sel); return p && shown(p) ? box(p) : null; };
  const dialog = document.querySelector('dialog[open]');
  const edge = (sel, side) => { const e = q(sel); return e ? e.getBoundingClientRect()[side] : null; };
  const actionEnd = [...document.querySelectorAll('.actions > *')].filter(shown).map((e) => e.getBoundingClientRect().right).pop();
  const actionRows = [...new Set([...document.querySelectorAll('.actions > *')].filter(shown).map((e) => Math.round(e.getBoundingClientRect().top)))];
  return { vw, vh, actionRows, brandLeft: edge('.brand', 'left'), actionEnd, canvas: box(q('#gameCanvas')), board: box(q('#boardFrame')), chrome: box(q('.chrome')), content, outside, buttons,
           scrollable: document.scrollingElement.scrollHeight > vh + 1 || document.scrollingElement.scrollWidth > vw + 1,
           rotated: __pp.state().fit.rotated, coarse: matchMedia('(pointer: coarse)').matches,
           panel: panel('.overlay--title .panel') || panel('.overlay--pause .panel') || panel('.overlay--end .panel'),
           dialog: dialog ? box(dialog) : null, dialogButtons: dialog ? [...dialog.querySelectorAll('button')].filter(shown).map((b) => { const r = b.getBoundingClientRect(); return { name: b.id || b.textContent.trim(), w: r.width, h: r.height }; }) : [] };
}"""


def settle(page):
    """Let a change to the page reach the layout: the resize observer runs before the next paint, so two frames."""
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def check(m, touch, label):
    tap = 44 if touch else 36
    where = f'[{label}]'
    assert not m['outside'], f'{where} outside the viewport: {m["outside"]}'
    assert not m['scrollable'], f'{where} the page scrolls'
    assert len(m['actionRows']) == 1, f'{where} the action buttons wrap onto {len(m["actionRows"])} rows: tops {m["actionRows"]}'
    c = m['canvas']
    assert c['l'] >= -0.5 and c['t'] >= -0.5 and c['r'] <= m['vw'] + 0.5 and c['b'] <= m['vh'] + 0.5, f'{where} the board is not fully in view: {c}'
    largest = c['w'] >= m['content']['w'] - 1.5 or c['h'] >= m['content']['h'] - 1.5
    assert largest, f'{where} the board could be larger: canvas {c["w"]:.0f}x{c["h"]:.0f} in {m["content"]["w"]:.0f}x{m["content"]["h"]:.0f}'
    assert m['rotated'] == (m['content']['h'] > m['content']['w']), f'{where} rotation does not follow the stage'
    stacked, rail = m['chrome']['b'] <= m['board']['t'] + 0.5, m['chrome']['r'] <= m['board']['l'] + 0.5
    assert stacked or rail, f'{where} the HUD overlaps the board: chrome {m["chrome"]} board {m["board"]}'
    if not touch and m['board']['w'] >= 720:                                  # a desktop: the bar lines up with the board, edge to edge
        assert abs(m['brandLeft'] - m['board']['l']) <= 2 and abs(m['actionEnd'] - m['board']['r']) <= 2, \
            f'{where} the top bar is not aligned with the board: brand {m["brandLeft"]:.0f}, actions end {m["actionEnd"]:.0f}, board {m["board"]["l"]:.0f}..{m["board"]["r"]:.0f}'
    for b in m['buttons'] + m['dialogButtons']:
        assert min(b['w'], b['h']) >= tap - 0.5, f'{where} {b["name"]} is {b["w"]:.0f}x{b["h"]:.0f}, under the {tap}px target'
    if m['panel']:
        p, b = m['panel'], m['board']
        assert p['l'] >= b['l'] - 0.5 and p['r'] <= b['r'] + 0.5 and p['t'] >= b['t'] - 0.5 and p['b'] <= b['b'] + 0.5, f'{where} the overlay does not fit on the board: {p} in {b}'
    if m['dialog']:
        d = m['dialog']
        assert d['l'] >= 0 and d['t'] >= 0 and d['r'] <= m['vw'] and d['b'] <= m['vh'], f'{where} the dialog does not fit the screen: {d}'


@pytest.mark.parametrize('name,width,height,mode,dpr', SIZES, ids=[s[0] for s in SIZES])
def test_every_screen_size_lays_out_cleanly(open_page, engine, name, width, height, mode, dpr):
    touch = mode == 'touch'
    page = open_page(viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    assert page.evaluate("matchMedia('(pointer: coarse)').matches") == touch, 'the emulation must give the pointer type the layout is chosen by'
    OUT.mkdir(parents=True, exist_ok=True)
    shot = lambda phase: page.screenshot(path=str(OUT / f'{engine}-{name}-{phase}.png'))     # noqa: E731

    page.wait_for_function('__pp.state().frames > 3')
    check(page.evaluate(MEASURE), touch, f'{name} title')
    shot('1-title')

    page.click('#startButton') if not touch else page.tap('#startButton')
    assert page.evaluate('__pp.state().phase') == 'playing'
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60, vx: 6, vy: 4 }]); __pp.cutLine("v", 40)')     # some claimed ground to look at
    check(page.evaluate(MEASURE), touch, f'{name} playing')
    shot('2-playing')
    # The widest the HUD gets: a seven-digit score, the top combo, and all five lives.
    page.evaluate('__pp.game.run.score = 1234567; __pp.game.run.combo = 3; __pp.game.run.lives = 5; __pp.game.emit("hud")')
    settle(page)
    check(page.evaluate(MEASURE), touch, f'{name} playing, widest HUD')
    shot('2b-widest-hud')

    # Each screen is asserted to really be the one meant: a check that ran on the wrong screen would pass silently.
    page.keyboard.press('p')
    assert page.evaluate('__pp.state().phase') == 'paused' and page.locator('#pauseOverlay').is_visible()
    check(page.evaluate(MEASURE), touch, f'{name} paused')
    shot('3-paused')
    page.keyboard.press('p')
    assert page.evaluate('__pp.state().phase') == 'playing'

    page.evaluate("__pp.ui.openSettings()")
    page.wait_for_function("document.getElementById('settingsDialog').open")
    check(page.evaluate(MEASURE), touch, f'{name} settings')
    shot('4-settings')
    page.keyboard.press('Escape')
    page.wait_for_function("!document.querySelector('dialog[open]')")
    assert page.evaluate('__pp.state().phase') == 'paused'                    # closing settings leaves the game paused, by design
    page.keyboard.press('p')
    assert page.evaluate('__pp.state().phase') == 'playing'

    page.evaluate('__pp.forceWin()')                                          # the level-clear tally
    assert page.evaluate('__pp.state().phase') == 'clear' and page.locator('#clearOverlay').is_visible()
    check(page.evaluate(MEASURE), touch, f'{name} level clear')
    shot('4b-clear')
    page.evaluate('__pp.game.startLevel(2)')                                  # straight on, without waiting for the tally to time out
    assert page.evaluate('__pp.state().phase') == 'playing'

    for _ in range(5):
        page.evaluate('__pp.game.loseLife()')
    assert page.evaluate('__pp.state().phase') == 'over' and page.locator('#endOverlay').is_visible()
    check(page.evaluate(MEASURE), touch, f'{name} game over')
    shot('5-over')


def test_resizing_or_rotating_refits_the_board_without_a_reload(open_page):
    """A phone turned on its side, or a desktop window dragged narrower, must re-lay itself out live."""
    page = open_page(viewport={'width': 390, 'height': 844}, dpr=2, has_touch=True, is_mobile=True)
    portrait = page.evaluate('__pp.state().fit')
    assert portrait['rotated'] is True
    page.set_viewport_size({'width': 844, 'height': 390})
    page.wait_for_function('__pp.state().fit.rotated === false')
    landscape = page.evaluate(MEASURE)
    check(landscape, True, 'rotated to landscape')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_function('__pp.state().fit.rotated === true')
    check(page.evaluate(MEASURE), True, 'rotated back')


def test_the_page_cannot_be_scrolled_or_zoomed_by_dragging_on_the_board(open_page, engine):
    """With touch-action: none on the canvas a drag is ours; the page underneath must not move either."""
    page = open_page(viewport={'width': 390, 'height': 700}, dpr=2, has_touch=True, is_mobile=True)
    page.tap('#startButton')
    assert page.evaluate("getComputedStyle(document.getElementById('gameCanvas')).touchAction") == 'none'
    page.evaluate('window.scrollTo(0, 400)')
    assert page.evaluate('[scrollX, scrollY]') == [0, 0]
    assert page.evaluate("getComputedStyle(document.documentElement).overscrollBehaviorY") == 'none'


def test_a_wide_child_cannot_widen_the_hud_column(open_page):
    """The HUD column is minmax(0, 1fr) so that no child, however wide (a long translated label, say), drags the
    whole HUD past the screen edge. Nothing is that wide today, so the guard is proved by injecting something."""
    page = open_page(viewport={'width': 390, 'height': 844}, dpr=2, has_touch=True, is_mobile=True)
    page.evaluate("""() => { const wide = document.createElement('span'); wide.id = 'injectedWide';
      wide.textContent = 'x'.repeat(200); wide.style.whiteSpace = 'nowrap'; document.querySelector('.bar').append(wide); }""")
    got = page.evaluate("""() => ({ hud: document.querySelector('.hud').getBoundingClientRect().width, chrome: document.querySelector('.chrome').getBoundingClientRect().width, vw: innerWidth })""")
    assert got['hud'] <= got['vw'] and got['chrome'] <= got['vw'], got


@pytest.mark.parametrize('name,width,height,mode,dpr', SIZES, ids=[s[0] for s in SIZES])
def test_the_title_with_a_saved_run_on_offer_fits_every_screen_size(open_page, engine, name, width, height, mode, dpr):
    """Resume run adds a second big button and a line of text to the title: the tallest title there is."""
    touch = mode == 'touch'
    page = open_page(viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    page.evaluate('__pp.game.newRun({ seed: "saved" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40); __pp.game.run.score = 1234567; __pp.game.run.nextLifeAt = 1250000; __pp.game.persist()')    # a state the game could really reach
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    page.wait_for_function('__pp.state().frames > 3')
    assert page.locator('#resumeRunButton').is_visible() and page.locator('#savedLine').is_visible()
    check(page.evaluate(MEASURE), touch, f'{name} title with a saved run')
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f'{engine}-{name}-1b-title-saved.png'))


@pytest.mark.parametrize('name,width,height,mode,dpr', SIZES, ids=[s[0] for s in SIZES])
def test_the_tutorial_screens_fit_every_screen_size(open_page, engine, name, width, height, mode, dpr):
    """The coached board (with the console line in use and the header button turned into Skip) and the finish screen."""
    touch = mode == 'touch'
    page = open_page(tutorial=True, viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    OUT.mkdir(parents=True, exist_ok=True)
    shot = lambda phase: page.screenshot(path=str(OUT / f'{engine}-{name}-{phase}.png'))     # noqa: E731
    page.click('#startButton') if not touch else page.tap('#startButton')
    assert page.evaluate('__pp.game.run.mode') == 'tutorial' and page.evaluate('__pp.state().phase') == 'playing'
    page.evaluate('__pp.freeze(true); __pp.game.tutorial._go(2)')                          # the ghost is mid-sweep on step 2
    page.evaluate('new Promise((resolve) => setTimeout(resolve, 900))')
    settle(page)
    assert page.locator('#toast').is_visible() and page.evaluate('__pp.renderer.ghost') is not None
    check(page.evaluate(MEASURE), touch, f'{name} tutorial coach')
    shot('6-tutorial')
    page.evaluate('__pp.game.finishTutorial({ percent: 33.2, gained: 33.2 })')
    assert page.evaluate('__pp.state().phase') == 'clear' and page.locator('#clearOverlay').is_visible() and page.locator('#clearNote').is_visible()
    check(page.evaluate(MEASURE), touch, f'{name} tutorial finish')
    shot('7-tutorial-done')


@pytest.mark.parametrize('name,width,height,mode,dpr', SIZES, ids=[s[0] for s in SIZES])
def test_power_up_chips_and_a_pickup_sit_on_the_board_on_every_screen_size(open_page, engine, name, width, height, mode, dpr):
    """Three effects at once (the most there can be) as chips over the board's corner, and a pickup on the field."""
    touch = mode == 'touch'
    page = open_page(viewport={'width': width, 'height': height}, dpr=dpr, has_touch=touch, is_mobile=touch)
    page.evaluate('__pp.game.newRun({ seed: "chips" }); __pp.game.startLevel(3); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.freeze(true); __pp.game.powerups.place("shield", 60, 36)')
    page.evaluate('const p = __pp.game.powerups, now = __pp.game.clock.now; p.until.freeze = now + 2.4; p.until.shield = now + 4; p.until.slow = now + 1')
    settle(page)
    chips = page.evaluate("[...document.querySelectorAll('.power')].map((c) => { const r = c.getBoundingClientRect(); return { kind: c.dataset.kind, l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; })")
    assert [c['kind'] for c in chips] == ['freeze', 'shield', 'slow']
    board = page.evaluate("(() => { const r = document.getElementById('gameCanvas').getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; })()")
    for c in chips:
        assert c['l'] >= board['l'] - 0.5 and c['r'] <= board['r'] + 0.5 and c['t'] >= board['t'] - 0.5 and c['b'] <= board['b'] + 0.5, f'[{name}] a {c["kind"]} chip leaves the board: {c} in {board}'
        assert 28 <= c['w'] <= 40 and abs(c['w'] - c['h']) < 0.5, f'[{name}] a {c["kind"]} chip is {c["w"]:.0f}x{c["h"]:.0f}'
    assert chips[0]['r'] <= chips[1]['l'] + 0.5 and chips[1]['r'] <= chips[2]['l'] + 0.5, f'[{name}] chips overlap'
    check(page.evaluate(MEASURE), touch, f'{name} power-ups')
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f'{engine}-{name}-8-powerups.png'))

