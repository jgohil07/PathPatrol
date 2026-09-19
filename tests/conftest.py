"""Shared fixtures: a static server for site/, real browsers, and pages that fail the test on any
console error, page error or failed request.

Engines: chromium (the installed Chrome locally, bundled Chromium in CI) and webkit.
    PP_ENGINES=chromium            run one engine only
    PP_CHROMIUM_CHANNEL=           empty = Playwright's bundled Chromium (CI); default 'chrome'
    PP_SITE_DIR=/some/copy         test a different copy of the site (used to check the tests can fail)
"""
import os
import pathlib
import re
import sys
import threading

import pytest
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import serve  # noqa: E402

ENGINES = [e for e in os.environ.get('PP_ENGINES', 'chromium,webkit').split(',') if e]
EXTERNAL_FONTS = re.compile(r'https://fonts\.(googleapis|gstatic)\.com/.*')


@pytest.fixture(scope='session')
def site_url():
    server = serve.make_server(os.environ.get('PP_SITE_DIR') or ROOT / 'site')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


@pytest.fixture(scope='session')
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope='session', params=ENGINES)
def browser(request, playwright_instance):
    p = playwright_instance
    if request.param == 'chromium':
        channel = os.environ.get('PP_CHROMIUM_CHANNEL', 'chrome') or None
        instance = p.chromium.launch(channel=channel)
    else:
        instance = getattr(p, request.param).launch()
    yield instance
    instance.close()


@pytest.fixture
def engine(browser):
    return browser.browser_type.name


@pytest.fixture
def open_page(browser, site_url, playwright_instance):
    """open_page(path='/?debug=1', device=None, viewport=None, dpr=None, init=()) -> Page.

    `page.problems` collects everything the browser complained about; the test fails at teardown if it
    is not empty. A test that provokes an error on purpose clears it (page.problems.clear()).
    """
    opened = []

    def _open(path='/?debug=1', *, device=None, viewport=None, dpr=None, init=(), wait_ready=True):
        kwargs = dict(playwright_instance.devices[device]) if device else {}
        if viewport:
            kwargs['viewport'] = viewport
        if dpr:
            kwargs['device_scale_factor'] = dpr
        context = browser.new_context(**kwargs)
        context.route(EXTERNAL_FONTS, lambda route: route.fulfill(status=200, body='', content_type='text/css'))
        for script in init:
            context.add_init_script(script)
        page = context.new_page()
        problems = []
        page.problems = problems
        page.on('console', lambda m: problems.append(f'console.{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: problems.append(f'pageerror: {e}'))
        page.on('requestfailed', lambda r: problems.append(f'requestfailed: {r.url}'))
        page.on('response', lambda r: problems.append(f'http {r.status}: {r.url}') if r.status >= 400 else None)
        page.goto(site_url + path)
        if wait_ready:
            page.wait_for_function('window.__pp !== undefined')
        opened.append((context, page))
        return page

    yield _open
    leftovers = [problem for _, page in opened for problem in page.problems]
    for context, _ in opened:
        context.close()
    assert not leftovers, 'the browser reported problems:\n' + '\n'.join(leftovers)
