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
from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import serve  # noqa: E402

# A fresh profile plays the tutorial on its first Start run. Most tests want a plain run, so a page starts with the
# tutorial already done, unless the test says tutorial=True. It seeds once per tab (sessionStorage marks it), so a
# test that stores something and reloads, or removes the storage key on purpose, is not overwritten again.
TUTORIAL_DONE = """(() => { try {
  if (sessionStorage.getItem('__pp_seeded')) return;
  sessionStorage.setItem('__pp_seeded', '1');
  const key = 'pathpatrol:v2';
  const stored = JSON.parse(localStorage.getItem(key) || 'null') || { v: 2, settings: {}, records: {} };
  stored.settings = Object.assign({}, stored.settings, { tutorialDone: true });
  localStorage.setItem(key, JSON.stringify(stored));
} catch (error) { /* storage blocked: the page will play the tutorial, and the test has other things to say */ } })();"""

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
    """open_page(path='/?debug=1', device=None, viewport=None, dpr=None, init=(), tutorial=False, **context_options) -> Page.

    tutorial=True leaves the profile fresh, so the first Start run plays the tutorial; by default it is marked done.

    `page.problems` collects everything the browser complained about; the test fails at teardown if it
    is not empty. A test that provokes an error on purpose clears it (page.problems.clear()).
    """
    opened = []

    def _open(path='/?debug=1', *, device=None, viewport=None, dpr=None, init=(), wait_ready=True, tutorial=False, **options):
        kwargs = dict(playwright_instance.devices[device]) if device else {}
        if viewport:
            kwargs['viewport'] = viewport
        if dpr:
            kwargs['device_scale_factor'] = dpr
        kwargs.update(options)                            # anything else browser.new_context() takes: has_touch, is_mobile, locale...
        context = browser.new_context(**kwargs)
        context.route(EXTERNAL_FONTS, lambda route: route.fulfill(status=200, body='', content_type='text/css'))
        if not tutorial:
            context.add_init_script(TUTORIAL_DONE)
        for script in init:
            context.add_init_script(script)
        page = context.new_page()
        problems = []
        page.problems = problems
        page.requests = []                                # every URL the page asked for, for "nothing third-party" checks
        page.on('request', lambda r: page.requests.append(r.url))
        page.on('console', lambda m: problems.append(f'console.{m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: problems.append(f'pageerror: {e}'))
        page.on('requestfailed', lambda r: problems.append(f'requestfailed: {r.url}'))
        page.on('response', lambda r: problems.append(f'http {r.status}: {r.url}') if r.status >= 400 else None)
        opened.append((context, page))
        page.goto(site_url + path)
        if wait_ready:
            try:
                page.wait_for_function('window.__pp !== undefined', timeout=10_000)
            except PlaywrightTimeout as error:
                # Say why: a page that never boots is almost always an error the browser already reported.
                try:
                    where = page.evaluate("[document.readyState, (document.getElementById('app') || {dataset: {}}).dataset.phase, location.href]")
                except Exception as inner:                    # the page may be too stuck to answer
                    where = f'page unreachable: {inner}'
                raise AssertionError('the page never became ready (window.__pp is undefined)\n'
                                     f'state: {where}\nreported: {problems or "nothing"}') from error
        return page

    yield _open
    leftovers = [problem for _, page in opened for problem in page.problems]
    for context, _ in opened:
        context.close()
    assert not leftovers, 'the browser reported problems:\n' + '\n'.join(leftovers)
