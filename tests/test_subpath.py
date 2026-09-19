"""GitHub Pages serves a project from a path, https://<user>.github.io/PathPatrol/, not from the root of a domain. Anything that says
"/something" where it should say "something" works on a local server and breaks there. These tests serve site/ under /PathPatrol/
and nowhere else (a request outside the prefix is a 404, as on Pages) and check the game, its worker and its manifest all live there."""
import pathlib
import threading
from urllib.parse import urljoin

import pytest
import serve

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
PREFIX = '/PathPatrol'


class Under(serve.Handler):
    def translate_path(self, path):
        path = path.split('?', 1)[0].split('#', 1)[0]
        if path != PREFIX and not path.startswith(PREFIX + '/'):
            return str(SITE / '__outside_the_prefix__')                                  # nothing there: 404
        return super().translate_path(path[len(PREFIX):] or '/')


@pytest.fixture
def under_prefix():
    server = serve.make_server(SITE, handler=Under)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Site:
        base = f'http://127.0.0.1:{server.server_address[1]}{PREFIX}/'
        stopped = False

        def stop(self):
            if not self.stopped:
                self.stopped = True
                server.shutdown()
                server.server_close()

    site = Site()
    yield site
    site.stop()


def test_the_game_loads_and_plays_from_a_path(under_prefix, open_page):
    page = open_page(under_prefix.base + '?debug=1')                                     # (any request outside the prefix is a 404, which fails the test)
    page.click('#startButton')
    page.evaluate('__pp.setPatrols([{ x: 100, y: 60 }]); __pp.game.route.begin(30, 1); __pp.game.route.move(30, 71)')
    assert page.evaluate('__pp.state().cleared') > 5
    assert all(url.startswith(under_prefix.base) for url in page.requests)


def test_the_worker_the_manifest_and_the_cache_all_live_under_the_path(under_prefix, open_page):
    page = open_page(under_prefix.base + '?debug=1&sw=1')
    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=25_000)
    got = page.evaluate("""async () => {
      const scope = (await navigator.serviceWorker.getRegistration()).scope;
      const cached = []; for (const name of await caches.keys()) for (const r of await (await caches.open(name)).keys()) cached.push(r.url);
      const link = new URL(document.querySelector('link[rel="manifest"]').getAttribute('href'), document.baseURI).href;
      const manifest = await (await fetch(link)).json();
      const at = (u) => new URL(u, link).href;
      const icons = []; for (const i of manifest.icons) icons.push([at(i.src), (await fetch(at(i.src))).status]);
      return { scope, cached, link, id: at(manifest.id), start: at(manifest.start_url), manifestScope: at(manifest.scope), icons }; }""")
    base = under_prefix.base
    assert got['scope'] == base and got['link'] == base + 'manifest.webmanifest'
    assert got['id'] == got['start'] == got['manifestScope'] == base                          # the installed app is this path, not the domain
    assert got['cached'] and all(url.startswith(base) for url in got['cached'])
    assert base in got['cached'] and base + 'index.html' in got['cached']
    assert all(status == 200 and url.startswith(base) for url, status in got['icons'])


def test_it_plays_offline_from_the_path(under_prefix, open_page):
    page = open_page(under_prefix.base + '?debug=1&sw=1')
    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=25_000)
    under_prefix.stop()
    page.reload()
    page.wait_for_function('window.__pp !== undefined', timeout=20_000)
    page.click('#startButton')
    assert page.evaluate('__pp.state().phase') == 'playing'
    page.problems[:] = [p for p in page.problems if 'sw.js' not in p]                       # (the worker's own look for a newer sw.js finds nobody home)
