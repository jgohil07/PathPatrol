"""The installable-app parts: the manifest and the icons (are they valid, the right size, drawn from one source, safe under
a platform's mask), the head links a browser and iOS look for, and the images that go with them. The service worker, the
offline behaviour and the update flow are tested further down."""
import json
import math
import pathlib
import struct
import subprocess
import sys
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
BG = (7, 11, 18)


def png_info(path):
    data = pathlib.Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f'{path} is not a PNG'
    width, height, depth, colour = struct.unpack('>IIBB', data[16:26])
    return width, height, depth, colour


def png_pixels(path):
    """Decode a PNG that this project's own writer made (8-bit RGBA, every row unfiltered) into a list of rows of (r, g, b, a)."""
    data = pathlib.Path(path).read_bytes()
    width, height, depth, colour = png_info(path)
    assert (depth, colour) == (8, 6), 'not 8-bit RGBA'
    pos, idat = 8, b''
    while pos < len(data):
        length, tag = struct.unpack('>I4s', data[pos:pos + 8])
        if tag == b'IDAT':
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    rows = []
    for y in range(height):
        assert raw[y * stride] == 0, 'a filtered row'
        row = raw[y * stride + 1:(y + 1) * stride]
        rows.append([tuple(row[x * 4:x * 4 + 4]) for x in range(width)])
    return rows


# ---- the manifest ----------------------------------------------------------------------------------------------------
def manifest():
    return json.loads((SITE / 'manifest.webmanifest').read_text())


def test_the_manifest_describes_an_app_that_lives_under_any_path():
    m = manifest()
    assert m['name'] == 'Path Patrol' and m['short_name'] == 'Path Patrol' and m['lang'] == 'en'
    assert m['id'] == './' and m['start_url'] == './' and m['scope'] == './'           # relative: the same file works at / and at /PathPatrol/
    assert not any(str(m[k]).startswith(('/', 'http')) for k in ('id', 'start_url', 'scope'))
    assert m['display'] == 'standalone' and m['display_override'] == ['fullscreen', 'standalone'] and m['orientation'] == 'any'
    assert m['background_color'] == '#070b12' and m['theme_color'] == '#070b12'
    assert m['categories'] == ['games'] and 20 < len(m['description']) < 200


def test_every_icon_and_screenshot_the_manifest_lists_exists_and_is_the_size_it_claims():
    m = manifest()
    by = {(i['sizes'], i['purpose']): i for i in m['icons']}
    assert set(by) == {('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable'), ('any', 'any')}       # what installability asks for, and a vector
    for icon in m['icons']:
        path = SITE / icon['src']
        assert path.is_file(), icon['src']
        if icon['type'] == 'image/png':
            w, h, _, _ = png_info(path)
            assert f'{w}x{h}' == icon['sizes'], icon['src']
        else:
            assert icon['type'] == 'image/svg+xml' and path.read_text().lstrip().startswith('<svg')
    forms = {s['form_factor']: s for s in m['screenshots']}
    assert set(forms) == {'wide', 'narrow'}
    for shot in m['screenshots']:
        w, h, _, _ = png_info(SITE / shot['src'])
        assert f'{w}x{h}' == shot['sizes'] and shot['label']
    ww, wh = map(int, forms['wide']['sizes'].split('x')); nw, nh = map(int, forms['narrow']['sizes'].split('x'))
    assert ww > wh and nh > nw                                                          # a wide one is wide, a narrow one is tall


def test_the_other_images_are_the_sizes_the_page_and_ios_expect():
    assert png_info(SITE / 'icons' / 'apple-touch-icon.png')[:2] == (180, 180)
    assert png_info(SITE / 'og.png')[:2] == (1200, 630)


# ---- the icons --------------------------------------------------------------------------------------------------------
def test_the_icons_are_exactly_what_the_generator_draws(tmp_path):
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'make_icons.py'), str(tmp_path)], check=True, capture_output=True)
    made = sorted(p.name for p in tmp_path.iterdir())
    assert made == ['apple-touch-icon.png', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png', 'icon.svg']
    for name in made:
        assert (tmp_path / name).read_bytes() == (SITE / 'icons' / name).read_bytes(), f'{name} is not what tools/make_icons.py makes: run it'


def test_the_maskable_icon_keeps_everything_inside_the_central_eighty_percent_circle():
    rows = png_pixels(SITE / 'icons' / 'icon-maskable-512.png')
    size = len(rows)
    radius = 0.4 * size                                                                  # the platform-safe zone: a circle of 80 % of the side
    outside_ink, inside_ink = 0, 0
    for y, row in enumerate(rows):
        for x, (r, g, b, a) in enumerate(row):
            assert a == 255                                                              # full bleed: nothing transparent for a mask to expose
            ink = abs(r - BG[0]) + abs(g - BG[1]) + abs(b - BG[2]) > 6
            if ink and math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) > radius:
                outside_ink += 1
            elif ink:
                inside_ink += 1
    assert outside_ink == 0 and inside_ink > 20000                                       # the mark is all inside, and is really there


def test_the_ordinary_icon_has_rounded_transparent_corners_and_the_apple_one_is_solid():
    rows = png_pixels(SITE / 'icons' / 'icon-512.png')
    assert rows[0][0][3] == 0 and rows[0][-1][3] == 0 and rows[-1][0][3] == 0 and rows[-1][-1][3] == 0      # corners are see-through
    assert rows[256][2][3] == 255 and rows[2][256][3] == 255 and rows[256][256][3] == 255                    # the edges and the middle are not
    apple = png_pixels(SITE / 'icons' / 'apple-touch-icon.png')
    assert all(px[3] == 255 for row in apple for px in row)                              # iOS fills anything transparent with black
    assert tuple(apple[0][0][:3]) == BG


def test_the_vector_icon_and_the_png_icons_are_the_same_picture(open_page, engine):
    """The PNGs and the SVG are drawn from the same numbers; render the SVG in a browser and compare it with the 512 PNG."""
    page = open_page()
    diff = page.evaluate("""async () => {
      const load = (src) => new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = src; });
      const pixels = (img) => { const c = document.createElement('canvas'); c.width = c.height = 512; const g = c.getContext('2d', { willReadFrequently: true });
        g.fillStyle = '#ff00ff'; g.fillRect(0, 0, 512, 512); g.drawImage(img, 0, 0, 512, 512); return g.getImageData(0, 0, 512, 512).data; };
      const a = pixels(await load('/icons/icon.svg')), b = pixels(await load('/icons/icon-512.png'));
      let total = 0, worst = 0, off = 0; for (let i = 0; i < a.length; i += 4) { const d = Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]); total += d; if (d > worst) worst = d; if (d > 60) off++; }
      return { mean: total / (a.length / 4), worst, off };
    }""")
    assert diff['mean'] < 1.5 and diff['off'] < 1200, diff                               # the same shapes in the same places: only the edges' anti-aliasing differs (a one-pixel shift would put ~2000 pixels off)


# ---- what the page says about itself -----------------------------------------------------------------------------------
def test_the_page_links_its_icons_and_manifest_and_asks_ios_for_a_full_screen_app(open_page):
    page = open_page()
    got = page.evaluate("""() => ({
      icons: [...document.querySelectorAll('link[rel~="icon"]')].map((l) => [l.getAttribute('href'), l.getAttribute('type'), l.getAttribute('sizes')]),
      apple: document.querySelector('link[rel="apple-touch-icon"]').getAttribute('href'),
      manifest: document.querySelector('link[rel="manifest"]').getAttribute('href'),
      meta: Object.fromEntries([...document.querySelectorAll('meta[name]')].map((m) => [m.name, m.content])) })""")
    assert got['icons'] == [['icons/icon.svg', 'image/svg+xml', None], ['icons/icon-192.png', 'image/png', '192x192']]
    assert got['apple'] == 'icons/apple-touch-icon.png' and got['manifest'] == 'manifest.webmanifest'
    assert not any(str(i[0]).startswith('data:') for i in got['icons'])                  # the placeholder that stopped a favicon 404 is gone
    meta = got['meta']
    assert meta['theme-color'] == '#070b12' and meta['apple-mobile-web-app-capable'] == 'yes' and meta['mobile-web-app-capable'] == 'yes'
    assert meta['apple-mobile-web-app-title'] == 'Path Patrol' and meta['apple-mobile-web-app-status-bar-style'] == 'black-translucent'
    for href in (got['manifest'], got['apple'], got['icons'][0][0], got['icons'][1][0]):
        response = page.request.get(page.url.split('?')[0] + href)
        assert response.status == 200, href
    assert page.request.get(page.url.split('?')[0] + got['manifest']).headers['content-type'].startswith('application/manifest+json')


def test_the_browser_finds_no_favicon_to_fetch_that_is_missing(open_page):
    page = open_page()
    page.wait_for_function('__pp.state().frames > 3')
    assert not [u for u in page.requests if u.endswith('/favicon.ico')]                  # the icon link answers, so the browser never guesses


# ==== the service worker: what is cached, and that it stays current ====================================================
import re  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import serve  # noqa: E402  (tools/serve.py: conftest put it on the path)


def shell_list():
    """The files sw.js precaches, as written in its generated block."""
    text = (SITE / 'sw.js').read_text()
    block = re.search(r'const SHELL = \[(.*?)\];', text, re.S).group(1)
    return re.findall(r"'([^']+)'", block)


def test_the_worker_version_is_the_apps_and_its_generated_block_is_current():
    config = (SITE / 'js' / 'config.js').read_text()
    app = re.search(r"APP_VERSION = '([^']+)'", config).group(1)
    worker = re.search(r"const VERSION = '([^']+)'", (SITE / 'sw.js').read_text()).group(1)
    assert worker == app                                                                 # the cache name carries the version the page shows
    checked = subprocess.run([sys.executable, str(ROOT / 'tools' / 'make_sw.py'), '--check'], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr                                        # a shell file was changed without running tools/make_sw.py: sw.js would not change, so no browser would update


def test_the_shell_is_everything_the_game_needs_offline_and_nothing_it_does_not():
    shell = shell_list()
    assert shell[0] == './' and len(shell) == len(set(shell))
    listed = set(shell[1:])
    on_disk = {p.relative_to(SITE).as_posix() for p in SITE.rglob('*') if p.is_file() and not p.name.startswith('.')}
    for path in listed:
        assert (SITE / path).is_file(), f'{path} is listed but missing'
    assert {p for p in on_disk if p.startswith('js/')} <= listed                        # every module, including the ones loaded later on
    assert {'index.html', 'manifest.webmanifest', 'css/app.css'} <= listed
    assert {p for p in on_disk if p.startswith(('assets/sprites/', 'icons/')) or p.endswith('.woff2')} <= listed
    for left_out in ('sw.js', 'og.png', 'robots.txt', 'sitemap.xml'):
        assert left_out not in listed
    assert not any(p.startswith('screenshots/') or p.endswith(('.txt', '.md')) for p in listed)
    html = (SITE / 'index.html').read_text()
    for ref in re.findall(r'(?:href|src)="([^"#]+)"', html):                             # whatever the page itself asks for is in the shell
        if not ref.startswith(('http', 'data:', '#')):
            assert ref in listed, f'index.html asks for {ref}, which is not cached'


def test_changing_a_shell_file_changes_the_worker_and_forgetting_to_regenerate_is_caught(tmp_path):
    site = tmp_path / 'site'
    shutil.copytree(SITE, site)
    script = [sys.executable, str(ROOT / 'tools' / 'make_sw.py'), '--site', str(site)]
    assert subprocess.run(script + ['--check'], capture_output=True).returncode == 0
    before = (site / 'sw.js').read_bytes()
    (site / 'css' / 'app.css').write_text((site / 'css' / 'app.css').read_text() + '\n/* changed */\n')
    assert subprocess.run(script + ['--check'], capture_output=True).returncode == 1        # a stale worker is reported...
    assert (site / 'sw.js').read_bytes() == before                                         # ...and --check changes nothing
    subprocess.run(script, check=True, capture_output=True)
    after = (site / 'sw.js').read_bytes()
    assert after != before and subprocess.run(script + ['--check'], capture_output=True).returncode == 0       # regenerating changes the worker's own bytes: that is what makes a browser update
    (site / 'js' / 'newmodule.js').write_text('export const x = 1;\n')
    subprocess.run(script, check=True, capture_output=True)
    assert "'js/newmodule.js'" in (site / 'sw.js').read_text()                              # a new file joins the shell
    (site / 'screenshots' / 'wide.png').write_bytes(b'not a png')
    (site / 'og.png').write_bytes(b'not a png')
    assert subprocess.run(script + ['--check'], capture_output=True).returncode == 0        # but the images that are not part of the game do not
    for junk in ('.DS_Store', 'notes.txt', 'README.md'):
        (site / junk).write_text('x')
    assert subprocess.run(script + ['--check'], capture_output=True).returncode == 0        # and neither do OS files or notes


def wait_for(page, expression, timeout=25.0):
    """Poll a condition in the page, riding out the moments when it is reloading."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.evaluate(expression):
                return True
        except Exception:                                                                 # the page is navigating: the context is gone for a moment
            pass
        time.sleep(0.1)
    try:
        where = page.evaluate("""() => ({ url: location.href, label: (document.getElementById('versionLabel') || {}).textContent, phase: __pp.state().phase,
          pwa: { update: __pp.pwa.update, applying: __pp.pwa._applying, idle: __pp.pwa._reloadWhenIdle, hadController: __pp.pwa._hadController, waiting: !!(__pp.pwa.registration && __pp.pwa.registration.waiting) },
          controller: navigator.serviceWorker.controller && navigator.serviceWorker.controller.state, hidden: document.hidden, nav: performance.getEntriesByType('navigation')[0].type })""")
    except Exception as error:
        where = f'the page could not say: {error}'
    raise AssertionError(f'timed out waiting for: {expression}\n{where}')


def controlled(page):
    page.wait_for_function('navigator.serviceWorker && navigator.serviceWorker.controller !== null', timeout=25_000)


# ---- the worker in a page --------------------------------------------------------------------------------------------------
def test_the_worker_takes_the_page_over_without_restarting_it_and_caches_the_whole_shell(open_page):
    page = open_page('/?debug=1&sw=1')
    page.evaluate('window.__mark = 1; 0')
    controlled(page)
    got = page.evaluate("""async () => { const names = await caches.keys(); const cache = await caches.open(names[0]); const keys = (await cache.keys()).map((r) => new URL(r.url).pathname);
      const bad = []; for (const r of await cache.keys()) { const hit = await cache.match(r); if (!hit.ok) bad.push(r.url); }
      return { names, keys, bad, mark: window.__mark, offline: __pp.pwa.offline, scope: (await navigator.serviceWorker.getRegistration()).scope }; }""")
    shell = shell_list()
    assert len(got['names']) == 1 and re.fullmatch(r'pathpatrol-1\.0\.0-[0-9a-f]{10}', got['names'][0])
    assert len(got['keys']) == len(shell) and '/' in got['keys'] and '/index.html' in got['keys'] and '/js/main.js' in got['keys']
    assert got['bad'] == [] and got['mark'] == 1                                        # every file cached whole; and the page was not reloaded when the worker claimed it
    assert got['offline'] == 'ready' and got['scope'].endswith('/')


def test_a_debug_page_registers_no_worker_unless_asked_to(open_page):
    page = open_page('/?debug=1')
    page.wait_for_function('__pp.state().frames > 3')
    assert page.evaluate('navigator.serviceWorker.getRegistrations().then((r) => r.length)') == 0
    assert page.evaluate('__pp.pwa.offline') == 'unsupported'                            # never registered, so nothing to say about offline play
    page = open_page('/?debug=1&sw=1')
    controlled(page)
    assert page.evaluate('navigator.serviceWorker.getRegistrations().then((r) => r.length)') == 1


def test_the_game_loads_and_plays_with_the_network_gone(release_site, open_page):
    """The server is stopped (a real failure to connect, the same in every browser), then the page is reloaded and played."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    release_site.stop()
    page.reload()
    page.wait_for_function('window.__pp !== undefined', timeout=20_000)
    page.wait_for_function('__pp.state().frames > 3')
    assert page.evaluate('document.getElementById("app").dataset.phase') == 'title'
    assert page.evaluate('__pp.pwa.update') is False and page.locator('#appNotice').is_hidden()          # served from the cache it is the version that is cached: nothing waits
    page.click('#startButton')
    assert page.evaluate('__pp.state().phase') == 'playing'
    frames = page.evaluate('__pp.state().frames')
    page.wait_for_function(f'__pp.state().frames > {frames + 5}')                           # it is drawing, from cache
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }]); __pp.game.route.begin(30, 1); __pp.game.route.move(30, 71)')       # (the one patrol is placed far from the line, so it cannot spoil it)
    assert page.evaluate('__pp.state().cleared') > 5                                       # and playing: a route drawn across claims ground
    assert page.locator('#versionLabel').text_content() == 'v1.0.0'
    origin = page.evaluate('location.origin')
    for path in ('/index.html', '/?x=1', '/?debug=1&sw=1'):                                # the app's own addresses, with or without a query
        response = page.goto(origin + path)
        assert response is not None and page.locator('#startButton').count() == 1, path
    assert not [p for p in page.problems if 'sw.js' not in p]                              # (the worker's own check for a newer sw.js finds nobody home: that is expected)
    page.problems.clear()


def test_chromium_finds_nothing_wrong_with_installing_it(open_page, engine):
    if engine != 'chromium':
        pytest.skip('Page.getInstallabilityErrors is a Chromium DevTools call')
    page = open_page('/?debug=1&sw=1')
    controlled(page)
    client = page.context.new_cdp_session(page)
    manifest_info = client.send('Page.getAppManifest')
    assert manifest_info['errors'] == [] and manifest_info['url'].endswith('/manifest.webmanifest')
    errors = [e['errorId'] for e in client.send('Page.getInstallabilityErrors')['installabilityErrors']]
    assert [e for e in errors if e != 'in-incognito'] == [], errors                       # (a test browser's context is always "incognito", which Chromium reports and which is no fault of the app)
    assert set(errors) <= {'in-incognito'}


# ---- a new version ---------------------------------------------------------------------------------------------------------------
class Noting(serve.Handler):
    """Notes every request (its path and Cache-Control header), and holds back a worker's fetch of any path containing a key of `held`
    (the worker asks past the HTTP cache, which a page's own requests do not) until that key's Event is set."""
    seen = held = None

    def do_GET(self):
        self.seen.append((self.path, self.headers.get('Cache-Control')))
        for needle, gate in list(self.held.items()):
            if needle in self.path and self.headers.get('Cache-Control') == 'no-cache':                # (the worker's fetches: a page's own are not held)
                gate.wait(30)
        super().do_GET()


@pytest.fixture
def release_site(tmp_path):
    """A private copy of the site on its own server, that can be 'released' as a new version while a page is running the old one."""
    site = tmp_path / 'site'
    shutil.copytree(SITE, site)
    seen, held = [], {}
    server = serve.make_server(site, handler=type('Recording', (Noting,), {'seen': seen, 'held': held}))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Release:
        url = f'http://127.0.0.1:{server.server_address[1]}'
        directory = site
        requests = seen                                                                       # (path, Cache-Control header) of everything asked for, in order

        def publish(self, version):
            config = site / 'js' / 'config.js'
            config.write_text(re.sub(r"APP_VERSION = '[^']*'", f"APP_VERSION = '{version}'", config.read_text(), count=1))
            worker = site / 'sw.js'
            worker.write_text(re.sub(r"const VERSION = '[^']*'", f"const VERSION = '{version}'", worker.read_text(), count=1))
            subprocess.run([sys.executable, str(ROOT / 'tools' / 'make_sw.py'), '--site', str(site)], check=True, capture_output=True)

        def hold(self, needle):
            """From now on, the worker's fetch of any path containing `needle` waits for the Event this returns."""
            held[needle] = threading.Event()
            return held[needle]

        def stop(self):
            """Stop serving: from here the network is really gone (connection refused), which no browser can tell from being offline."""
            for gate in held.values():
                gate.set()
            if not self.stopped:
                self.stopped = True
                server.shutdown()
                server.server_close()

        stopped = False

    release = Release()
    yield release
    release.stop()


def forgive_reload(page):
    """Requests cut short by our own reload (or by a second reload that overtook the first) are not faults."""
    page.problems[:] = [p for p in page.problems if 'ERR_ABORTED' not in p and not (p.startswith('requestfailed:') and '?debug=1' in p)]


def new_version_waiting(page, release_site, version='1.0.1'):
    """Release `version` and wait until this page has been told it is installed and waiting."""
    release_site.publish(version)
    page.evaluate('__pp.pwa.registration.update().then(() => 0)')
    page.wait_for_function('__pp.pwa.update === true', timeout=25_000)


def running_version(page, version):
    wait_for(page, f"document.getElementById('versionLabel') && document.getElementById('versionLabel').textContent === 'v{version}'")


def test_the_install_fetches_every_file_past_the_browsers_http_cache(release_site, open_page):
    """With cache: 'reload' a file the HTTP cache still holds (a server may say "keep it ten minutes") cannot be filed under the new
    version's name: an old file under a new name is an update that never fixes anything."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    fresh = {path for path, cache_control in release_site.requests if cache_control == 'no-cache'}
    for entry in shell_list():
        assert ('/' if entry == './' else '/' + entry) in fresh, f'{entry} was not fetched past the HTTP cache'


def test_a_change_to_the_files_alone_is_a_new_version_kept_apart_from_the_running_one(release_site, open_page):
    """The version number need not change for the files to: the cache is named for the contents too, so the new copy is built beside
    the old one and the running page never sees a mixture."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    old_name = page.evaluate('caches.keys()')[0]
    css = release_site.directory / 'css' / 'app.css'
    css.write_text(css.read_text() + '\n/* a tweak */\n')
    subprocess.run([sys.executable, str(ROOT / 'tools' / 'make_sw.py'), '--site', str(release_site.directory)], check=True, capture_output=True)
    page.evaluate('__pp.pwa.registration.update().then(() => 0)')
    page.wait_for_function('__pp.pwa.update === true', timeout=25_000)
    names = page.evaluate('caches.keys()')
    assert len(names) == 2 and old_name in names
    new_name = [n for n in names if n != old_name][0]
    assert new_name.startswith('pathpatrol-1.0.0-')                                         # the same version number, other contents
    css_in = lambda name: page.evaluate("(name) => caches.open(name).then((c) => c.match('css/app.css')).then((r) => r.text())", name)      # noqa: E731
    assert 'a tweak' not in css_in(old_name) and 'a tweak' in css_in(new_name)


def test_a_first_visit_says_it_is_saving_an_offline_copy_until_it_has_one(release_site, open_page):
    gate = release_site.hold('/js/game.js')                                                   # the worker cannot finish installing yet
    page = open_page(release_site.url + '/?debug=1&sw=1')
    wait_for(page, "__pp.pwa.offline === 'pending'")
    assert page.locator('#appStatus').text_content() == 'Saving an offline copy…'
    gate.set()
    page.wait_for_function("__pp.pwa.offline === 'ready'", timeout=25_000)
    assert page.locator('#appStatus').text_content() == 'Ready to play offline.'


def test_a_new_version_waits_until_asked_then_takes_over_and_the_old_files_are_removed(release_site, open_page):
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    assert page.locator('#versionLabel').text_content() == 'v1.0.0'
    first = page.evaluate('caches.keys()')
    assert len(first) == 1 and first[0].startswith('pathpatrol-1.0.0-')
    new_version_waiting(page, release_site)
    assert page.locator('#appNotice').is_visible() and page.locator('#appNotice').text_content() == 'Update ready · tap to restart'
    assert page.locator('#versionLabel').text_content() == 'v1.0.0'                       # it has installed, and is waiting: this page still runs the old one
    assert len(page.evaluate('caches.keys()')) == 2                                         # the new files are all there, beside the old ones
    assert 'Update ready' in page.locator('#announcer').text_content()
    page.click('#appNotice')
    running_version(page, '1.0.1')
    page.wait_for_function('__pp.state().frames > 2')
    names = page.evaluate('caches.keys()')
    assert len(names) == 1 and names[0].startswith('pathpatrol-1.0.1-')                    # the old version's files were deleted
    assert page.evaluate("performance.getEntriesByType('navigation')[0].type") == 'reload'
    assert page.evaluate('__pp.pwa.update') is False and page.locator('#appNotice').is_hidden()
    forgive_reload(page)


def test_an_update_leaves_other_caches_on_the_same_origin_alone(release_site, open_page):
    """A GitHub Pages user site serves every project from one origin, and Cache Storage is per origin: clearing out the old versions
    may only touch this app's own."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    page.evaluate("caches.open('other-project-v3').then((c) => c.put('/x', new Response('kept'))).then(() => 0)")
    new_version_waiting(page, release_site)
    page.click('#appNotice')
    running_version(page, '1.0.1')
    names = sorted(page.evaluate('caches.keys()'))
    assert len(names) == 2 and names[0] == 'other-project-v3' and names[1].startswith('pathpatrol-1.0.1-')
    assert page.evaluate("caches.open('other-project-v3').then((c) => c.match('/x')).then((r) => r.text())") == 'kept'
    forgive_reload(page)


def test_a_takeover_this_page_did_not_ask_for_never_restarts_a_run_and_waits_for_the_title(release_site, open_page):
    """Another tab tapping Update (or the browser itself) can make the new version take over under a page that is mid-run. That page
    has every module in memory and can play on: it restarts once it is back on the title."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    page.evaluate("window.__stillHere = 1; __pp.game.newRun({ seed: 'busy' }); __pp.freeze(true); 0")       # a run in progress
    new_version_waiting(page, release_site)
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('window.__stillHere') == 1      # learning of it restarts nothing
    page.click('#settingsButton')                                                        # it can be taken from Settings, by choice (see below)
    assert page.locator('#appButton').is_visible() and page.locator('#appButton').text_content() == 'Restart'
    assert 'A new version is ready.' in page.locator('#appStatus').text_content()
    page.keyboard.press('Escape')
    page.evaluate("navigator.serviceWorker.getRegistration().then((r) => r.waiting.postMessage('SKIP_WAITING')); 0")      # somebody else asks for the takeover: this page does not
    page.wait_for_function('__pp.pwa._reloadWhenIdle === true', timeout=25_000)
    time.sleep(0.5)
    assert page.evaluate('window.__stillHere') == 1 and page.evaluate('__pp.state().phase') in ('playing', 'paused')      # (closing Settings paused it)
    page.evaluate("__pp.game.resume(); __pp.game.pause('manual'); __pp.game.resume(); 0")      # play goes on, pausing and resuming: none of that is the title
    time.sleep(0.3)
    assert page.evaluate('window.__stillHere') == 1
    page.evaluate('__pp.pwa.applyUpdate(); 0')                                          # nothing is waiting any more, so tapping Restart now does nothing at all
    assert page.evaluate('window.__stillHere') == 1
    page.evaluate('__pp.game.enterTitle(); 0')                                              # back on the title: now it may restart
    running_version(page, '1.0.1')
    forgive_reload(page)


SPY_POSTS = """(() => { const real = ServiceWorker.prototype.postMessage;
  ServiceWorker.prototype.postMessage = function (...args) { const log = JSON.parse(sessionStorage.getItem('__posted') || '[]'); log.push(args[0]); sessionStorage.setItem('__posted', JSON.stringify(log)); return real.apply(this, args); }; })();"""


def test_a_launch_that_finds_an_update_waiting_takes_it_from_the_title_and_never_from_a_run(release_site, open_page):
    """A version that finished installing in an earlier visit is waiting when the page loads. On the title the page asks for the
    takeover at once (the launch becomes the update); if a run has already begun it leaves the update for later. (The messages are
    noted in sessionStorage, which outlives the restart that follows.)"""
    page = open_page(release_site.url + '/?debug=1&sw=1', init=[SPY_POSTS])
    controlled(page)
    new_version_waiting(page, release_site)
    page.evaluate("__pp.game.newRun({ seed: 'busy' }); __pp.freeze(true); 0")
    page.evaluate('__pp.pwa._register().then(() => 0)')                                    # the page "loads" again, with the update waiting, but with a run under way
    assert page.evaluate("JSON.parse(sessionStorage.getItem('__posted') || '[]')") == []
    assert page.evaluate('__pp.pwa._applying') is False and page.evaluate('__pp.pwa.update') is True
    page.evaluate('__pp.game.enterTitle(); __pp.pwa._register(); 0')                       # ... and now on the title
    running_version(page, '1.0.1')
    assert page.evaluate("JSON.parse(sessionStorage.getItem('__posted') || '[]')") == ['SKIP_WAITING']
    forgive_reload(page)


def test_taking_an_update_from_settings_mid_run_saves_the_run_and_offers_it_after_the_restart(release_site, open_page):
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    page.evaluate("__pp.game.newRun({ seed: 'midrun' }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine('v', 40); __pp.freeze(true); 0")
    cleared = page.evaluate('__pp.state().cleared')
    assert cleared > 5
    new_version_waiting(page, release_site)
    page.click('#settingsButton')
    page.click('#appButton')
    running_version(page, '1.0.1')
    page.wait_for_function('__pp.state().frames > 2')
    assert page.evaluate("document.getElementById('app').dataset.phase") == 'title' and page.locator('#resumeRunButton').is_visible()
    page.click('#resumeRunButton')
    page.wait_for_function("__pp.state().phase === 'countdown' || __pp.state().phase === 'playing'")
    assert page.evaluate('__pp.state().cleared') == cleared                                  # the run came through the restart, with the ground it had claimed
    forgive_reload(page)


def second_tab(page):
    """Another tab in the same browser, whose console and page errors count against the test like the first one's."""
    tab = page.context.new_page()
    tab.on('console', lambda m: page.problems.append(f'console.{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
    tab.on('pageerror', lambda e: page.problems.append(f'pageerror: {e}'))
    return tab


def test_a_page_opened_while_a_new_version_is_still_installing_hears_when_it_is_ready(release_site, open_page):
    """The install began before this page did. (The browser queues the page's registration behind the install in progress, so the page
    learns of it only once the version is ready. The first page stays open, so the running version keeps a client and the new one waits.)"""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    gate = release_site.hold('/js/game.js')                                                   # the new version cannot finish installing yet
    release_site.publish('1.0.1')
    page.evaluate('__pp.pwa.registration.update().then(() => 0)')
    wait_for(page, 'navigator.serviceWorker.getRegistration().then((r) => !!r.installing)')
    tab = second_tab(page)
    tab.goto(release_site.url + '/?debug=1&sw=1')
    tab.wait_for_function('window.__pp !== undefined')
    assert tab.evaluate('__pp.pwa.update') is False and tab.locator('#appNotice').is_hidden()
    tab.evaluate("const say = __pp.pwa.onChange; __pp.pwa.onChange = () => { if (__pp.pwa.update) sessionStorage.setItem('__heard', '1'); say(); }; 0")      # (a page on the title takes the update at once, so the moment itself is noted)
    gate.set()
    wait_for(tab, "sessionStorage.getItem('__heard') === '1'")
    tab.close()
    forgive_reload(page)


def test_a_page_that_was_controlled_from_the_start_restarts_when_a_version_takes_over(release_site, open_page):
    """The first worker to claim a page is no update, but on any later visit the page is controlled from the start, and whatever takes
    over then is one. (The browser announces a takeover with an event; a synthetic one stands in, clear of the browser's own timing.)"""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    page.reload()                                                                              # now it starts out controlled
    page.wait_for_function('window.__pp !== undefined && __pp.pwa.registration !== null')
    assert page.evaluate('navigator.serviceWorker.controller !== null')
    page.evaluate("window.__marker = 1; navigator.serviceWorker.dispatchEvent(new Event('controllerchange')); 0")
    wait_for(page, 'window.__marker === undefined && window.__pp !== undefined')
    forgive_reload(page)


def test_a_long_lived_page_looks_for_a_new_version_when_it_comes_back_into_view_at_most_once_an_hour(release_site, open_page):
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    asked = lambda: sum(1 for path, _ in release_site.requests if path == '/sw.js')          # noqa: E731
    visibility = lambda hidden: page.evaluate("""(hidden) => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
      document.dispatchEvent(new Event('visibilitychange')); }""", hidden)                # noqa: E731
    before = asked()
    visibility(True)
    time.sleep(0.6)
    assert asked() == before                                                              # going out of view asks for nothing
    visibility(False)
    wait_for(page, 'true')
    end = time.time() + 5
    while asked() == before and time.time() < end:
        time.sleep(0.1)
    assert asked() == before + 1                                                          # coming back does
    visibility(False)
    visibility(True)
    visibility(False)
    time.sleep(0.6)
    assert asked() == before + 1                                                          # but not again within the hour
    page.evaluate('const real = Date.now.bind(Date); Date.now = () => real() + 61 * 60 * 1000; 0')
    visibility(False)
    end = time.time() + 5
    while asked() == before + 1 and time.time() < end:
        time.sleep(0.1)
    assert asked() == before + 2                                                          # and again after it


def test_a_page_that_went_around_the_worker_is_not_offered_an_update_it_could_not_take(release_site, open_page, engine):
    """A hard reload skips the worker: that page has no controller, so an update it asked for would never reach it as a restart."""
    if engine != 'chromium':
        pytest.skip('Network.setBypassServiceWorker is a Chromium DevTools call')
    page = open_page(release_site.url + '/?debug=1&sw=1')                                     # (this tab stays, so the old version keeps a client and the new one keeps waiting)
    controlled(page)
    new_version_waiting(page, release_site)
    tab = second_tab(page)
    client = page.context.new_cdp_session(tab)
    client.send('Network.enable')
    client.send('Network.setBypassServiceWorker', {'bypass': True})
    tab.goto(release_site.url + '/?debug=1&sw=1')
    tab.wait_for_function('window.__pp !== undefined')
    assert tab.evaluate('navigator.serviceWorker.controller') is None
    assert tab.evaluate('navigator.serviceWorker.getRegistration().then((r) => !!r.waiting)') is True
    time.sleep(1.0)
    assert tab.evaluate('__pp.pwa.update') is False and tab.locator('#appNotice').is_hidden()
    tab.close()


def test_the_worker_answers_only_same_origin_gets_from_its_cache_and_leaves_the_rest_to_the_network(release_site, open_page):
    other = serve.make_server(SITE)                                                            # a second origin: the same files on another port
    threading.Thread(target=other.serve_forever, daemon=True).start()
    other_url = f'http://127.0.0.1:{other.server_address[1]}'
    page = open_page(release_site.url + '/?debug=1&sw=1', bypass_csp=True)
    controlled(page)
    seen = {}
    page.on('response', lambda r: seen.__setitem__((r.request.method, r.url), (r.status, r.from_service_worker)))
    page.evaluate("""(other) => Promise.all([fetch('/index.html'), fetch('/og.png'), fetch('/no-such-file.txt'),
      fetch('/somewhere', { method: 'POST', body: 'a' }), fetch(other + '/index.html', { mode: 'no-cors' })]).then(() => 0)""", other_url)
    base = release_site.url
    assert seen[('GET', base + '/index.html')] == (200, True)                              # the shell: from the cache
    assert seen[('GET', base + '/og.png')] == (200, True)                                  # not in the shell: the worker lets the network answer
    assert seen[('GET', base + '/no-such-file.txt')] == (404, True)                        # and the network's answer is what comes back
    assert seen[('POST', base + '/somewhere')][1] is False                                 # a request that changes something is none of its business
    assert seen[('GET', other_url + '/index.html')] == (200, False)                        # nor is another site's
    page.problems.clear()                                                                  # (the 404 and the 501 are on purpose)
    other.shutdown()
    other.server_close()


def test_a_page_that_is_the_first_to_see_a_new_version_does_not_restart_itself_on_first_install(release_site, open_page):
    """The very first worker claims the page: that is not an update, and reloading for it would loop."""
    page = open_page(release_site.url + '/?debug=1&sw=1')
    page.evaluate('window.__once = (window.__once || 0) + 1; 0')
    controlled(page)
    time.sleep(0.5)
    assert page.evaluate('window.__once') == 1 and page.evaluate("performance.getEntriesByType('navigation')[0].type") == 'navigate'
    assert page.evaluate('__pp.pwa.update') is False and page.locator('#appNotice').is_hidden()          # and it is not announced as an update either


def test_a_worker_that_cannot_install_leaves_the_running_version_alone(release_site, open_page):
    page = open_page(release_site.url + '/?debug=1&sw=1')
    controlled(page)
    release_site.publish('1.0.1')
    (release_site.directory / 'css' / 'app.css').unlink()                                    # the new version's list names a file that is gone
    page.evaluate('__pp.pwa.registration.update().catch(() => 0).then(() => 0)')
    time.sleep(2.0)
    assert page.evaluate('__pp.pwa.update') is False and page.locator('#versionLabel').text_content() == 'v1.0.0'
    assert page.evaluate('navigator.serviceWorker.controller.state') == 'activated'
    names = page.evaluate('caches.keys()')
    assert any(n.startswith('pathpatrol-1.0.0-') for n in names)                          # the old cache is untouched
    page.problems[:] = [p for p in page.problems if 'app.css' not in p and '404' not in p]


# ---- installing -----------------------------------------------------------------------------------------------------------------
FAKE_PROMPT = """window.__fakePrompt = (outcome, fail) => { const e = new Event('beforeinstallprompt', { cancelable: true });
  e.prompt = async () => { window.__prompted = (window.__prompted || 0) + 1; if (fail) throw new Error('the prompt broke'); }; e.userChoice = Promise.resolve({ outcome }); window.__lastPrompt = e; window.dispatchEvent(e); return e.defaultPrevented; }; 0"""


def notice(page):
    return page.evaluate("""({ visible: !document.getElementById('appNotice').hidden, text: document.getElementById('appNotice').textContent, mode: document.getElementById('appNotice').dataset.mode,
      button: !document.getElementById('appButton').hidden, status: document.getElementById('appStatus').textContent })""")


def test_the_browsers_install_offer_becomes_a_button_and_goes_away_when_used_or_installed(open_page):
    page = open_page()
    page.evaluate(FAKE_PROMPT)
    assert notice(page)['visible'] is False
    assert page.evaluate("__fakePrompt('accepted')") is True                                   # the browser's own bar is suppressed
    assert notice(page) | {'status': ''} == {'visible': True, 'text': 'Install app', 'mode': 'install', 'button': True, 'status': ''}
    assert page.locator('#appButton').text_content() == 'Install'
    page.click('#appNotice')
    page.wait_for_function('window.__prompted === 1')
    page.wait_for_function('__pp.pwa.installed === true')
    got = notice(page)
    assert got['visible'] is False and got['button'] is False and 'Installed.' in got['status']
    assert page.locator('#toast').text_content().strip() == 'Installed'
    page.evaluate("__fakePrompt('accepted')")                                                   # an installed app is not offered itself
    assert notice(page)['visible'] is False


def test_a_dismissed_install_prompt_is_gone_until_the_browser_offers_another(open_page):
    page = open_page()
    page.evaluate(FAKE_PROMPT)
    page.evaluate("__fakePrompt('dismissed')")
    page.click('#appNotice')
    page.wait_for_function('window.__prompted === 1')
    page.wait_for_function('document.getElementById("appNotice").hidden')                        # a prompt can be shown once
    assert page.evaluate('__pp.pwa.installed') is False
    assert page.locator('#toast').text_content().strip() != 'Installed'
    page.evaluate("__fakePrompt('accepted')")
    assert notice(page)['visible'] is True and notice(page)['mode'] == 'install'                 # a new offer brings the button back


def test_an_install_prompt_that_breaks_is_no_trouble_either(open_page):
    page = open_page()
    page.evaluate(FAKE_PROMPT)
    page.evaluate("__fakePrompt('accepted', true)")
    page.click('#appNotice')
    page.wait_for_function('window.__prompted === 1')
    page.wait_for_function('document.getElementById("appNotice").hidden')
    assert page.evaluate('__pp.pwa.installed') is False and page.locator('#toast').text_content().strip() != 'Installed'


def test_installing_by_other_means_removes_the_button(open_page):
    page = open_page()
    page.evaluate(FAKE_PROMPT)
    page.evaluate("__fakePrompt('accepted')")
    assert notice(page)['visible'] is True
    page.evaluate("window.dispatchEvent(new Event('appinstalled')); 0")
    assert notice(page)['visible'] is False and page.evaluate('__pp.pwa.installed') is True


@pytest.mark.parametrize('mode', ['standalone', 'fullscreen'])
def test_an_app_that_is_already_open_as_an_app_is_not_offered_installation(open_page, mode):
    page = open_page(init=["""const real = window.matchMedia.bind(window); window.matchMedia = (q) => q.includes('display-mode: MODE')
      ? { matches: true, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent() { return false; } } : real(q);""".replace('MODE', mode)])
    page.evaluate(FAKE_PROMPT)
    page.evaluate("__fakePrompt('accepted')")
    assert notice(page)['visible'] is False and page.evaluate('__pp.pwa.standalone') is True


def test_the_app_button_offers_the_most_useful_thing_first_and_announces_an_update_once(open_page):
    page = open_page()
    page.evaluate(FAKE_PROMPT)
    page.evaluate("Object.defineProperty(__pp.pwa, 'isIos', { get: () => true }); window.__said = []; const say = __pp.ui.announce.bind(__pp.ui); __pp.ui.announce = (text) => { window.__said.push(text); say(text); }; 0")
    page.evaluate("__fakePrompt('accepted')")                                                    # an install offer and the iOS hint at once (they never meet outside a test)
    assert notice(page)['mode'] == 'install'                                                   # the offer the browser made beats the hint
    page.evaluate('__pp.pwa.installPrompt = null; __pp.pwa.onChange(); 0')
    assert notice(page)['mode'] == 'ios'
    page.evaluate("__pp.pwa.update = true; __pp.pwa.installPrompt = window.__lastPrompt; __pp.pwa.onChange(); __pp.pwa.onChange(); __pp.pwa.onChange(); 0")
    assert notice(page)['mode'] == 'update'                                                    # and a waiting update beats them both
    assert [s for s in page.evaluate('window.__said') if 'Update ready' in s] == ['Update ready. Restart from the title screen or Settings.']       # said once, however often the screens refresh


def test_settings_says_what_offline_play_and_the_installed_state_are(open_page):
    page = open_page()
    for state, text in (('unsupported', 'Offline play is not available here.'), ('pending', 'Saving an offline copy…'), ('ready', 'Ready to play offline.')):
        page.evaluate(f"__pp.pwa.offline = '{state}'; __pp.pwa.onChange(); 0")
        assert page.locator('#appStatus').text_content() == text
    page.evaluate("__pp.pwa.update = true; __pp.pwa.installed = true; __pp.pwa.onChange(); 0")
    assert page.locator('#appStatus').text_content() == 'A new version is ready. Installed. Ready to play offline.'


IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
IPAD_UA = 'Mozilla/5.0 (iPad; CPU OS 12_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1 Mobile/15E148 Safari/604.1'
IPOD_UA = 'Mozilla/5.0 (iPod touch; CPU iPhone OS 12_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1 Mobile/15E148 Safari/604.1'
MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'


def platform(name, touch_points):
    return f"Object.defineProperty(navigator, 'platform', {{ configurable: true, value: '{name}' }}); Object.defineProperty(navigator, 'maxTouchPoints', {{ configurable: true, value: {touch_points} }});"


@pytest.mark.parametrize('agent,script,ios', [
    (IPHONE_UA, '', True), (IPAD_UA, '', True), (IPOD_UA, '', True),          # (an iPod touch's agent says 'iPhone OS')
    (MAC_UA, platform('MacIntel', 5), True),                       # an iPad running iPadOS says it is a Mac, but a Mac with a touch screen it is not
    (MAC_UA, platform('MacIntel', 0), False),                      # a Mac is a Mac
    ('Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36', platform('Linux armv8l', 5), False),
], ids=['iphone', 'ipad', 'ipod', 'ipad-as-mac', 'mac', 'android'])
def test_which_devices_count_as_ios(open_page, agent, script, ios):
    page = open_page(user_agent=agent, init=[script] if script else [])
    assert page.evaluate('__pp.pwa.isIos') is ios


def test_ios_gets_a_one_time_hint_where_the_button_is_since_it_has_no_prompt(open_page):
    page = open_page(user_agent=IPHONE_UA, viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
    got = notice(page)
    assert got['visible'] is True and got['mode'] == 'ios' and got['text'] == 'Install: tap Share, then Add to Home Screen. Tap to hide'
    assert got['button'] is False and 'To install: tap Share, then Add to Home Screen.' in got['status']                  # Settings keeps saying it
    page.tap('#appNotice')
    assert notice(page)['visible'] is False and page.evaluate('__pp.storage.settings.installHintSeen') is True
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    assert notice(page)['visible'] is False                                                   # once, as promised
    assert 'To install:' in notice(page)['status']


def test_the_ios_hint_is_not_shown_to_an_installed_app_or_to_anyone_else(open_page):
    standalone = open_page(user_agent=IPHONE_UA, viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True,
                           init=["Object.defineProperty(navigator, 'standalone', { configurable: true, value: true });"])
    assert notice(standalone)['visible'] is False and 'To install:' not in notice(standalone)['status']
    ipad = open_page(user_agent=MAC_UA, viewport={'width': 820, 'height': 1180}, has_touch=True, is_mobile=True, init=[platform('MacIntel', 5)])
    assert notice(ipad)['visible'] is True                                                      # an iPad says it is a Mac, and is still an iPad
    desktop = open_page()
    assert notice(desktop)['visible'] is False and notice(desktop)['status'] != ''


# ---- the screen stays awake ------------------------------------------------------------------------------------------------------
FAKE_WAKE = """window.__wake = { requests: 0, releases: 0, active: 0, most: 0, delay: 0, mode: 'ok' };
Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async (type) => {
  if (window.__wake.mode === 'deny') throw new DOMException('not allowed', 'NotAllowedError');
  await new Promise((resolve) => setTimeout(resolve, window.__wake.delay));
  window.__wake.requests++; window.__wake.active++; window.__wake.most = Math.max(window.__wake.most, window.__wake.active);
  const sentinel = { type, released: false, addEventListener() {}, release: async () => { if (sentinel.released) return; sentinel.released = true; window.__wake.releases++; window.__wake.active--; } };
  window.__wake.last = sentinel; return sentinel; } } });"""


def test_the_screen_is_kept_awake_only_while_a_run_is_being_played(open_page):
    page = open_page(init=[FAKE_WAKE])
    page.wait_for_function('__pp.state().frames > 3')
    assert page.evaluate('window.__wake.active') == 0                                          # the title does not need it
    page.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); 0")
    page.wait_for_function('window.__wake.active === 1')
    page.evaluate("__pp.game.pause('manual'); 0")
    page.wait_for_function('window.__wake.active === 0')                                       # paused: let the screen dim
    page.evaluate('__pp.game.resume(); 0')
    page.wait_for_function('window.__wake.active === 1')
    assert page.evaluate('window.__wake.requests') == 2 and page.evaluate('window.__wake.releases') == 1
    page.evaluate('__pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    page.wait_for_function('window.__wake.active === 0')                                       # game over as well
    assert page.evaluate('window.__wake.requests') == page.evaluate('window.__wake.releases') == 2


def test_a_run_that_stops_before_the_lock_is_granted_does_not_keep_it(open_page):
    page = open_page(init=[FAKE_WAKE, 'window.__wake.delay = 150;'])
    page.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); __pp.game.pause('manual'); 0")      # asked for, and no longer wanted before the answer comes
    page.wait_for_function('window.__wake.requests === 1')
    page.wait_for_function('window.__wake.releases === 1')
    assert page.evaluate('window.__wake.active') == 0


def test_toggling_quickly_asks_for_one_lock_at_a_time_and_ends_holding_what_is_wanted(open_page):
    page = open_page(init=[FAKE_WAKE, 'window.__wake.delay = 150;'])
    page.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); __pp.game.pause('manual'); __pp.game.resume(); __pp.game.pause('manual'); __pp.game.resume(); 0")
    page.wait_for_function('window.__wake.active === 1')
    time.sleep(0.5)
    got = page.evaluate('({ ...window.__wake, last: undefined })')
    assert got['active'] == 1 and got['most'] == 1 and got['requests'] == got['releases'] + 1       # never two at once, and the one held is the one that matters


def test_hiding_the_page_lets_go_and_coming_back_to_a_run_asks_again(open_page):
    page = open_page(init=[FAKE_WAKE])
    page.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); 0")
    page.wait_for_function('window.__wake.active === 1')
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); 0")
    page.wait_for_function('window.__wake.active === 0')
    page.evaluate("Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')); 0")
    page.evaluate('__pp.game.resume(); __pp.game.tick(3.1); 0')                                # the automatic pause on hiding ends with the 3-2-1
    page.wait_for_function('window.__wake.active === 1')


def test_a_refused_or_missing_wake_lock_never_gets_in_the_way(open_page):
    page = open_page(init=[FAKE_WAKE, "window.__wake.mode = 'deny';"])
    page.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); 0")
    page.wait_for_function('__pp.state().frames > 5')
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('window.__wake.active') == 0
    page.evaluate("window.__wake.mode = 'ok'; __pp.game.pause('manual'); __pp.game.resume(); 0")
    page.wait_for_function('window.__wake.active === 1')                                       # allowed later: it is asked for again at the next change
    none = open_page(init=["delete Navigator.prototype.wakeLock;"])
    none.evaluate("__pp.game.newRun({ seed: 'awake' }); __pp.freeze(true); 0")
    none.wait_for_function('__pp.state().frames > 5')
    assert none.evaluate('__pp.state().phase') == 'playing' and none.evaluate("'wakeLock' in navigator") is False
