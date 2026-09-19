#!/usr/bin/env python3
"""Captures the screenshots the manifest advertises and renders the social-share image, from the real game.

    .venv/bin/python tools/make_screenshots.py

Writes site/screenshots/wide.png (1280x720), site/screenshots/narrow.png (720x1280) and site/og.png (1200x630).
The scene is composed through the page's ?debug=1 hooks (a level with four patrols and three obstacles, ground already
claimed, a route being drawn, a pickup, a power-up running), so what is pictured is the game itself, not a mock-up.
Needs the Playwright install in .venv. Not run in CI: the results are committed."""
import pathlib
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import serve  # noqa: E402

SCENE = """() => {
  const g = __pp.game;
  g.newRun({ seed: 'store' }); g.startLevel(7); __pp.freeze(true);
  g.tracers.list.length = 0;
  __pp.setPatrols([{ x: 96, y: 22, vx: 12, vy: 9 }, { x: 78, y: 56, vx: -10, vy: 11 }, { x: 108, y: 48, vx: -9, vy: -12 }, { x: 62, y: 30, vx: 11, vy: -8 }]);
  __pp.cutLine('v', 30);                                      // the left of the board is already claimed
  g.run.score = 48250; g.run.combo = 1.75; g.level.cleared = 26.4;
  g.powerups.place('shield', 86, 38);                         // a pickup waiting on the board
  g.powerups.until.slow = g.clock.now + 3.6;                 // and a power-up running
  g.route.begin(29.6, 44); g.route.move(38, 44); g.route.move(50, 47); g.route.move(60, 45.5);        // a route being drawn: the runway and the tip ring
  g.emit('hud');
}"""


def compose(page):
    page.evaluate(SCENE)
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    page.wait_for_timeout(120)


def main():
    out = ROOT / 'site' / 'screenshots'
    out.mkdir(parents=True, exist_ok=True)
    server = serve.make_server(ROOT / 'site')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_address[1]}/?debug=1'
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='pp-og-'))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome')
        seed_done = "localStorage.setItem('pathpatrol:v2', JSON.stringify({ v: 2, settings: { tutorialDone: true }, records: {} }));"
        for name, viewport, touch in (('wide', {'width': 1280, 'height': 720}, False), ('narrow', {'width': 720, 'height': 1280}, True)):
            context = browser.new_context(viewport=viewport, device_scale_factor=1, has_touch=touch, is_mobile=touch)
            context.add_init_script(seed_done)
            page = context.new_page()
            page.goto(url)
            page.wait_for_function('window.__pp !== undefined')
            compose(page)
            page.screenshot(path=str(out / f'{name}.png'))
            print(f'wrote screenshots/{name}.png')
            context.close()
        context = browser.new_context(viewport={'width': 1280, 'height': 720}, device_scale_factor=2)      # the board alone, sharp, for the social image
        context.add_init_script(seed_done)
        page = context.new_page()
        page.goto(url)
        page.wait_for_function('window.__pp !== undefined')
        compose(page)
        page.locator('#gameCanvas').screenshot(path=str(tmp / 'board.png'))
        context.close()
        html = (ROOT / 'tools' / 'og.html').read_text().replace('{{ROOT}}', ROOT.as_uri()).replace('{{BOARD}}', (tmp / 'board.png').as_uri())
        (tmp / 'og.html').write_text(html)
        context = browser.new_context(viewport={'width': 1200, 'height': 630}, device_scale_factor=1)
        page = context.new_page()
        page.goto((tmp / 'og.html').as_uri())
        page.evaluate('document.fonts.ready.then(() => 0)')
        page.wait_for_timeout(200)
        page.screenshot(path=str(ROOT / 'site' / 'og.png'))
        print('wrote og.png')
        browser.close()
    server.shutdown()


main()
