"""A smoke check of a deployed copy of the site: set PP_LIVE_URL (with the trailing slash) and run just this file,

    PP_LIVE_URL=https://jgohil07.github.io/PathPatrol/ python -m pytest tests/test_live.py

The workflow runs it after every deploy. It first waits until the site serves the very files this checkout has (the page can lag
the deploy by a moment), then checks what only a real host can show: every file answers with the type a browser insists on,
the manifest and the worker live under the site's path, and the game boots, plays and works offline there. Skipped otherwise."""
import os
import pathlib
import time
from urllib.parse import urljoin

import make_sw                                                  # tools/ is on the path (conftest)
import pytest

LIVE = os.environ.get('PP_LIVE_URL', '')
SITE = pathlib.Path(__file__).resolve().parents[1] / 'site'
pytestmark = pytest.mark.skipif(not LIVE, reason='set PP_LIVE_URL to check a deployed site')

TYPES = {'.html': 'text/html', '.js': 'javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png',
         '.webmanifest': 'application/manifest+json', '.txt': 'text/plain', '.xml': 'xml'}
EXTRAS = ['sw.js', 'og.png', 'robots.txt', 'sitemap.xml', 'screenshots/wide.png', 'screenshots/narrow.png']


@pytest.fixture(scope='session')
def deployed(playwright_instance):
    """Waits (up to three minutes: the first publication of a new site can take a while to reach every edge) until the site's worker file is this checkout's."""
    base = LIVE if LIVE.endswith('/') else LIVE + '/'
    request = playwright_instance.request.new_context()
    wanted = (SITE / 'sw.js').read_text()
    end = time.time() + 180
    seen = 'no answer'
    while True:
        try:
            got = request.get(base + 'sw.js', headers={'Cache-Control': 'no-cache'})
            seen = f'HTTP {got.status}, {len(got.text())} bytes against {len(wanted)}'
            if got.ok and got.text() == wanted:
                break
        except Exception as error:                              # a host that is not answering yet
            seen = f'{type(error).__name__}: {str(error)[:200]}'
        if time.time() > end:
            raise AssertionError(f'the site never served this checkout\'s sw.js (last answer: {seen}): is the deploy for this commit done?')
        time.sleep(3)
    yield base
    request.dispose()


def test_every_file_answers_with_the_type_a_browser_insists_on(deployed, playwright_instance):
    request = playwright_instance.request.new_context()
    files = [''] + make_sw.shell_files(SITE) + EXTRAS
    for rel in files:
        response = request.get(urljoin(deployed, rel))
        kind = TYPES[pathlib.Path(rel).suffix] if rel else 'text/html'
        assert response.status == 200, f'{rel}: HTTP {response.status}'
        assert kind in response.headers['content-type'], f'{rel}: {response.headers["content-type"]}'
    request.dispose()


def test_the_manifest_and_every_icon_it_names_resolve_under_the_sites_path(deployed, open_page):
    page = open_page(deployed + '?debug=1')
    got = page.evaluate("""async () => {
      const link = new URL(document.querySelector('link[rel="manifest"]').getAttribute('href'), document.baseURI).href;
      const manifest = await (await fetch(link)).json(); const at = (u) => new URL(u, link).href;
      const files = [...manifest.icons, ...manifest.screenshots].map((i) => at(i.src)); const codes = [];
      for (const url of files) codes.push([url, (await fetch(url)).status]);
      return { link, id: at(manifest.id), start: at(manifest.start_url), scope: at(manifest.scope), codes }; }""")
    assert got['id'] == got['start'] == got['scope'] == deployed and got['link'] == deployed + 'manifest.webmanifest'
    assert got['codes'] and all(status == 200 and url.startswith(deployed) for url, status in got['codes'])


def test_the_game_boots_clean_and_plays_on_the_live_site(deployed, open_page):
    page = open_page(deployed + '?debug=1')                     # (any console warning, page error, failed request or HTTP error here fails the test)
    page.click('#startButton')
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }]); __pp.game.route.begin(30, 1); __pp.game.route.move(30, 71); 0')
    assert page.evaluate('__pp.state().cleared') > 5
    assert page.locator('#versionLabel').text_content() == 'v1.0.0'


def test_the_worker_takes_the_scope_of_the_path_and_the_game_plays_offline(deployed, open_page, engine):
    page = open_page(deployed + '?debug=1&sw=1')
    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=60_000)
    assert page.evaluate('navigator.serviceWorker.getRegistration().then((r) => r.scope)') == deployed
    names = page.evaluate('caches.keys()')
    assert len(names) == 1 and names[0].startswith('pathpatrol-1.0.0-')
    cached = page.evaluate("caches.open(%r).then((c) => c.keys()).then((keys) => keys.map((r) => r.url))" % names[0])
    assert cached and all(url.startswith(deployed) for url in cached) and deployed in cached
    if engine != 'chromium':
        pytest.skip('offline emulation blocks a page the worker serves in WebKit; the offline reload is checked on Chromium')
    page.context.set_offline(True)
    page.reload()
    page.wait_for_function('window.__pp !== undefined', timeout=30_000)
    page.click('#startButton')
    assert page.evaluate('__pp.state().phase') == 'playing'
    page.context.set_offline(False)
    page.problems[:] = [p for p in page.problems if 'sw.js' not in p and 'net::ERR_INTERNET_DISCONNECTED' not in p]     # (the worker's own look for a newer sw.js finds nobody home)


def test_chromium_finds_nothing_wrong_with_installing_the_live_app(deployed, open_page, engine):
    if engine != 'chromium':
        pytest.skip('Page.getInstallabilityErrors is a Chromium DevTools call')
    page = open_page(deployed + '?debug=1&sw=1')
    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=60_000)
    client = page.context.new_cdp_session(page)
    errors = [e['errorId'] for e in client.send('Page.getInstallabilityErrors')['installabilityErrors']]
    assert set(errors) <= {'in-incognito'}, errors                    # (a test browser's context is always "incognito", which Chromium reports and which is no fault of the app)
