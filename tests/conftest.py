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
import time

import pytest
from playwright.sync_api import Error as PlaywrightError, Locator, Page, TimeoutError as PlaywrightTimeout, sync_playwright

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
def _wait_for_function(self, expression, arg=None, *, timeout=None, polling=None):
    """Page.wait_for_function evaluates its expression with `new Function` inside the page, and the page's Content-Security-Policy (which
    has no 'unsafe-eval', on purpose) refuses that. page.evaluate goes through the browser's own protocol, which the policy does not
    govern, so this waits by asking it: same meaning (truthy), same 30 s default, the same TimeoutError, and a page that is in the middle
    of a navigation is asked again. Every test keeps running under the real policy this way."""
    if arg is not None:
        raise TypeError('these tests wait for an expression, without an argument')
    limit = 30_000 if timeout is None else timeout
    end = time.monotonic() + (limit / 1000 if limit else float('inf'))
    while True:
        try:
            if self.evaluate(f'!!({expression})'):
                return None
        except PlaywrightError as error:
            if not re.search(r'Execution context was destroyed|Cannot find context|navigat', str(error)):
                raise
        if time.monotonic() >= end:
            raise PlaywrightTimeout(f'Page.wait_for_function: Timeout {limit}ms exceeded.')
        time.sleep(0.01)


Page.wait_for_function = _wait_for_function


def _quiet_screenshot(original, page_of):
    """WebKit's screenshot adds a stylesheet to the page (whatever the options), which the page's policy (style-src 'self') refuses, and
    WebKit reports each refusal as a console error. Noted here so that exactly those refusals, while a screenshot is being taken, are
    not counted (the same refusal at any other moment is a real violation and is)."""
    def screenshot(self, **options):
        page = page_of(self)
        page.__dict__['_screenshot_until'] = time.monotonic() + 5
        try:
            return original(self, **options)
        finally:
            page.__dict__['_screenshot_until'] = time.monotonic() + 0.5          # (the report may still be on its way)
    return screenshot


Page.screenshot = _quiet_screenshot(Page.screenshot, lambda page: page)
Locator.screenshot = _quiet_screenshot(Locator.screenshot, lambda locator: locator.page)

# Chrome says this a few seconds after the load of a document that was replaced (by a reload) before it had claimed its font preloads. Nothing
# is wrong: a document that stays is never told it (test_design asserts that on a cold load, and that each font is fetched once).
BENIGN_WARNING = re.compile(r'was preloaded using link preload but not used within a few seconds')
SCREENSHOT_INJECTION = re.compile(r"Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear")


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
        if not tutorial:
            context.add_init_script(TUTORIAL_DONE)
        for script in init:
            context.add_init_script(script)
        page = context.new_page()
        problems = []
        page.problems = problems
        page.requests = []                                # every URL the page asked for, for "nothing third-party" checks
        page.on('request', lambda r: page.requests.append(r.url))
        def on_console(message):
            if message.type not in ('error', 'warning') or BENIGN_WARNING.search(message.text):
                return
            if SCREENSHOT_INJECTION.search(message.text) and time.monotonic() < page.__dict__.get('_screenshot_until', 0):
                return
            problems.append(f'console.{message.type}: {message.text}')

        page.on('console', on_console)
        page.on('pageerror', lambda e: problems.append(f'pageerror: {e}'))
        page.on('requestfailed', lambda r: problems.append(f'requestfailed: {r.url}'))
        page.on('response', lambda r: problems.append(f'http {r.status}: {r.url}') if r.status >= 400 else None)
        opened.append((context, page))
        page.goto(path if path.startswith('http') else site_url + path)          # a full URL is for a test that runs its own server
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
    # A problem reported in the last moments of a test (an error in a handler the test's final click set off) may still be on its way to
    # us: the browser's events are only delivered while we are calling into it. So wait a beat in the browser's own event loop. (Not a
    # round trip through the page: that would hang for ever on a page with scripts off, or one stuck in a loop.)
    alive = next((page for _, page in opened if not page.is_closed()), None)
    if alive is not None:
        alive.wait_for_timeout(50)
    leftovers = [problem for _, page in opened for problem in page.problems]
    for context, _ in opened:
        context.close()
    assert not leftovers, 'the browser reported problems:\n' + '\n'.join(leftovers)
