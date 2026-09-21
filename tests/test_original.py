"""Nothing the prototype had was lost in the rebuild. The prototype (commit 7f0c570) drew a Flight board of planes over mountains or a
Drive board of cars over city blocks, with obstacles inside the field, a claimed area that looked different from the open one, lives,
a progress bar with the target marked on it, a count of runners, pause (button, P, Esc), restart, sound, records and a line of
messages. These tests read the canvas and the page to show each of them is still on screen and still works."""
import pytest


def region(page, x0, y0, x1, y1):
    """Mean colour and number of distinct (quantised) colours of a rectangle of the board, in board units, as it is on the canvas."""
    return page.evaluate("""([x0, y0, x1, y1]) => {
      const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
      const a = __pp.toClient(x0, y0), b = __pp.toClient(x1, y1), sx = c.width / r.width, sy = c.height / r.height;
      const left = Math.round((Math.min(a.x, b.x) - r.left) * sx), top = Math.round((Math.min(a.y, b.y) - r.top) * sy);
      const w = Math.max(1, Math.round(Math.abs(b.x - a.x) * sx)), h = Math.max(1, Math.round(Math.abs(b.y - a.y) * sy));
      const s = document.createElement('canvas'); s.width = w; s.height = h;
      const g = s.getContext('2d', { willReadFrequently: true }); g.drawImage(c, left, top, w, h, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data; let R = 0, G = 0, B = 0; const seen = new Set();
      const N = 6, cells = Array.from({ length: N * N }, () => [0, 0, 0, 0]);
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 4, cell = cells[Math.min(N - 1, Math.floor(y * N / h)) * N + Math.min(N - 1, Math.floor(x * N / w))];
        R += d[i]; G += d[i + 1]; B += d[i + 2]; cell[0] += d[i]; cell[1] += d[i + 1]; cell[2] += d[i + 2]; cell[3]++;
        seen.add(((d[i] >> 3) << 10) | ((d[i + 1] >> 3) << 5) | (d[i + 2] >> 3));
      }
      const n = d.length / 4; return { mean: [R / n, G / n, B / n], colours: seen.size, cells: cells.map((c) => [c[0] / c[3], c[1] / c[3], c[2] / c[3]]) }; }""", [x0, y0, x1, y1])


def apart(a, b):
    """How far apart two regions' mean colours are (sum of the channel differences)."""
    return sum(abs(p - q) for p, q in zip(a['mean'], b['mean']))


def near(page, x0, y0, x1, y1, rgb, tolerance=90):
    """How many pixels of a rectangle of the board are within `tolerance` (sum of channel differences) of a colour."""
    return page.evaluate("""([x0, y0, x1, y1, rgb, tolerance]) => {
      const c = document.getElementById('gameCanvas'), r = c.getBoundingClientRect();
      const a = __pp.toClient(x0, y0), b = __pp.toClient(x1, y1), sx = c.width / r.width, sy = c.height / r.height;
      const left = Math.round((Math.min(a.x, b.x) - r.left) * sx), top = Math.round((Math.min(a.y, b.y) - r.top) * sy);
      const w = Math.max(1, Math.round(Math.abs(b.x - a.x) * sx)), h = Math.max(1, Math.round(Math.abs(b.y - a.y) * sy));
      const s = document.createElement('canvas'); s.width = w; s.height = h;
      const g = s.getContext('2d', { willReadFrequently: true }); g.drawImage(c, left, top, w, h, 0, 0, w, h);
      const d = g.getImageData(0, 0, w, h).data; let count = 0;
      for (let i = 0; i < d.length; i += 4) if (Math.abs(d[i] - rgb[0]) + Math.abs(d[i + 1] - rgb[1]) + Math.abs(d[i + 2] - rgb[2]) <= tolerance) count++;
      return count; }""", [x0, y0, x1, y1, list(rgb), tolerance])


def local(a, b):
    """The largest change in any one part of two views of the same rectangle: a small sprite moves this a lot and the mean hardly at all."""
    return max(sum(abs(p - q) for p, q in zip(ca, cb)) for ca, cb in zip(a['cells'], b['cells']))


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def show(page, theme, patrols, level=1, lines=()):
    page.evaluate(f"__pp.game.newRun({{ seed: 'look' }}); __pp.game.startLevel({level}); __pp.freeze(true); __pp.ui.setTheme('{theme}'); 0")
    page.evaluate(f'__pp.setPatrols({patrols})')
    for line in lines:
        page.evaluate(f'__pp.cutLine("v", {line})')
    page.evaluate('__pp.renderer.invalidate(); 0')
    frame(page)


@pytest.fixture
def board(open_page):
    return open_page(viewport={'width': 1280, 'height': 800})


def test_flight_and_drive_each_paint_their_own_board(board):
    page = board
    show(page, 'flight', '[{ x: 100, y: 60 }]')
    flight = region(page, 10, 10, 30, 20)
    show(page, 'drive', '[{ x: 100, y: 60 }]')
    drive = region(page, 10, 10, 30, 20)
    assert apart(flight, drive) > 20, (flight, drive)                                         # two different palettes for the open field
    assert flight['colours'] > 2 and drive['colours'] > 2                                     # and a texture, not a flat fill (a flat one has one or two)


@pytest.mark.parametrize('theme,runner', [('flight', 'plane'), ('drive', 'car')])
def test_the_runner_is_drawn_where_it_is_and_only_there(board, theme, runner):
    page = board
    spots = {'first': (86, 36, 94, 44), 'second': (16, 56, 24, 64), 'neither': (60, 10, 68, 18)}
    show(page, theme, '[{ x: 90, y: 40 }]')                                                  # the runner at the centre of `first`
    a = {name: region(page, *box) for name, box in spots.items()}
    show(page, theme, '[{ x: 20, y: 60 }]')                                                   # and now at the centre of `second`
    b = {name: region(page, *box) for name, box in spots.items()}
    assert local(a['first'], b['first']) > 30, (runner, local(a['first'], b['first']))          # it was drawn there, and is gone
    assert local(a['second'], b['second']) > 30, (runner, local(a['second'], b['second']))      # it is drawn where it moved to
    assert local(a['neither'], b['neither']) < 10, (runner, local(a['neither'], b['neither']))   # and nothing else on the board changed


SQUARE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="100" height="100"><rect width="10" height="10" fill="%s"/></svg>'


def test_each_theme_draws_its_own_sprite_file(board):
    """The planes come from plane.svg and the cars from car.svg: serve each as a plain square of a colour of its own and look for it."""
    page = board
    page.route('**/assets/sprites/plane.svg', lambda route: route.fulfill(status=200, content_type='image/svg+xml', body=SQUARE % '#ff0000'))
    page.route('**/assets/sprites/car.svg', lambda route: route.fulfill(status=200, content_type='image/svg+xml', body=SQUARE % '#0000ff'))
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    for theme, own, other in (('flight', (255, 0, 0), (0, 0, 255)), ('drive', (0, 0, 255), (255, 0, 0))):
        show(page, theme, '[{ x: 90, y: 40 }]')
        assert near(page, 88, 38, 92, 42, own) > 40 and near(page, 88, 38, 92, 42, other) == 0, theme


def test_a_plane_and_a_car_look_different(board):
    page = board
    show(page, 'flight', '[{ x: 90, y: 40 }]')
    plane = region(page, 88, 38, 92, 42)
    show(page, 'drive', '[{ x: 90, y: 40 }]')
    car = region(page, 88, 38, 92, 42)
    assert local(plane, car) > 30, local(plane, car)


@pytest.mark.parametrize('theme', ['flight', 'drive'])
def test_obstacles_are_drawn_inside_the_field_where_the_level_says(board, theme):
    page = board
    show(page, theme, '[{ x: 100, y: 60 }]', level=11)                                    # two obstacles
    obstacles = page.evaluate('__pp.state().obstacles')
    assert len(obstacles) == 2
    for o in obstacles:
        inside = region(page, o['x'] + 1, o['y'] + 1, o['x'] + o['w'] - 1, o['y'] + o['h'] - 1)
        beside = region(page, o['x'] - o['w'] - 1, o['y'] + 1, o['x'] - 1, o['y'] + o['h'] - 1)
        assert apart(inside, beside) > 15, (theme, o, inside, beside)                         # the block is not the colour of the field around it
        art = region(page, o['x'] + 0.5, o['y'] + 0.5, o['x'] + o['w'] - 0.5, o['y'] + o['h'] - 0.5)
        assert art['colours'] >= 15, (theme, o, art['colours'])                               # and it is a mountain or a city block (24 to 45 colours), not the plain ink of claimed ground (2)
        box = (o['x'] + 0.3, o['y'] + 0.3, o['x'] + o['w'] - 0.3, o['y'] + o['h'] - 0.3)
        snow, windows = near(page, *box, (169, 213, 204), 60), near(page, *box, (231, 200, 109), 60)          # the prototype's snow caps and lit windows
        assert (snow > 2 and windows == 0) if theme == 'flight' else (windows > 2 and snow == 0), (theme, o, snow, windows)


@pytest.mark.parametrize('theme', ['flight', 'drive'])
def test_claimed_ground_looks_different_from_open_field(board, theme):
    page = board
    show(page, theme, '[{ x: 100, y: 60 }]', lines=(40,))
    assert page.evaluate('__pp.state().cleared') > 25
    claimed = region(page, 6, 10, 34, 62)
    open_field = region(page, 46, 10, 74, 50)
    assert apart(claimed, open_field) > 15, (theme, claimed, open_field)


def test_lives_progress_target_and_runner_count_follow_the_game(board):
    page = board
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }, { x: 105, y: 20 }]); 0')
    assert page.locator('#lives').get_attribute('aria-label') == '3 lives' and page.locator('#runnerLabel').inner_text() == '2 PLANES'
    page.evaluate('__pp.game.loseLife(); 0')
    assert page.locator('#lives').get_attribute('aria-label') == '2 lives'
    page.evaluate('__pp.cutLine("v", 40); 0')
    cleared = page.evaluate('__pp.state().cleared')
    assert cleared > 25
    assert page.locator('#areaLabel').inner_text() == f'{cleared:.1f}%'
    fill = page.evaluate("parseFloat(document.getElementById('progressFill').style.width)")
    assert fill == pytest.approx(cleared, abs=0.06)                                            # the bar is the clear percentage
    assert page.evaluate("document.getElementById('targetMarker').style.left") == '65%' and page.locator('#targetLabel').inner_text() == '65%'


def test_pause_by_button_and_by_both_keys_and_restart_and_sound_and_messages_still_work(board):
    page = board
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); 0')
    phase = lambda: page.evaluate('__pp.state().phase')                                       # noqa: E731
    page.click('#pauseButton')
    assert phase() == 'paused'
    page.click('#resumeButton')
    assert phase() == 'playing'
    page.keyboard.press('p')
    assert phase() == 'paused'
    page.keyboard.press('p')
    assert phase() == 'playing'
    page.keyboard.press('Escape')
    assert phase() == 'paused'
    page.click('#resumeButton')
    page.keyboard.press('r')                                                                   # the first press only asks, in the messages line
    assert page.locator('#toast').text_content().startswith('Press R again') and phase() == 'playing'
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40); 0')
    assert page.evaluate('__pp.state().cleared') > 25
    page.keyboard.press('r')
    assert page.evaluate('__pp.state().cleared') == 0                                          # the second restarts the level
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('m')
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'false'
    page.click('#soundButton')
    assert page.locator('#soundButton').get_attribute('aria-pressed') == 'true'


def test_records_are_kept_and_shown(board):
    page = board
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40); 0')
    cleared = page.evaluate('__pp.state().cleared')
    page.evaluate('__pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')                # the run ends: its best clear is a record
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    page.click('#settingsButton')
    assert page.locator('#bestClear').inner_text() == f'{cleared:.1f}%' and page.locator('#runsPlayed').inner_text() == '1'
