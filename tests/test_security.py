"""The page's Content-Security-Policy (a meta tag, because GitHub Pages sends no headers): what it says, that nothing in the markup
breaks it, that a browser really enforces it, and that a full session of play never runs into it."""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'

POLICY = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
          "manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'")

WATCH = """(() => { window.__violations = [];
  document.addEventListener('securitypolicyviolation', (e) => window.__violations.push(e.violatedDirective.split(' ')[0] + ' ' + e.blockedURI)); })();"""


def html():
    return (SITE / 'index.html').read_text()


def test_the_policy_is_the_strict_one_and_comes_before_anything_that_loads():
    source = html()
    tag = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)"\s*/?>', source)
    assert tag and tag.group(1) == POLICY
    first_load = min(source.index(m) for m in ('<link', '<script', '<style') if m in source)
    assert tag.start() < first_load                                                        # a policy only governs what comes after it


def test_the_markup_has_no_inline_script_style_or_event_handler():
    source = html()
    for script in re.findall(r'<script\b([^>]*)>', source):
        assert 'src=' in script or 'application/ld+json' in script, script                 # (structured data is not run)
    assert '<style' not in source and not re.search(r'\sstyle\s*=', source)
    assert not re.search(r'\son[a-z]+\s*=', source) and 'javascript:' not in source


def test_no_script_builds_markup_or_code_from_strings():
    for path in (SITE / 'js').glob('*.js'):
        text = path.read_text()
        for banned in ('eval(', 'new Function', 'innerHTML', 'insertAdjacentHTML', 'document.write', "setAttribute('style'", 'cssText'):
            assert banned not in text, f'{path.name} uses {banned}'


def test_the_browser_really_enforces_it(open_page):
    """A policy that is only written down is no policy: try the things it forbids and see the browser refuse each."""
    page = open_page(init=[WATCH])
    page.evaluate("""() => { const s = document.createElement('script'); s.textContent = 'window.__ran = true'; document.head.append(s);
      document.body.setAttribute('style', 'color: red');
      new Image().src = 'https://example.com/pixel.png';
      fetch('https://example.com/data').catch(() => {});
      const f = document.createElement('iframe'); f.src = 'https://example.com/'; document.body.append(f); }""")
    page.wait_for_function('window.__violations.length >= 5')
    got = page.evaluate('window.__violations')
    directives = {v.split(' ')[0] for v in got}
    assert page.evaluate('window.__ran') is None                                             # the inline script did not run
    assert directives >= {'script-src-elem', 'style-src-attr', 'img-src', 'connect-src'} or directives >= {'script-src', 'style-src', 'img-src', 'connect-src'}, got
    assert any(d.startswith(('frame-src', 'child-src', 'default-src')) for d in directives), got     # (framing another site falls back to default-src)
    page.problems.clear()                                                                    # the refusals are reported as console errors: they were the point


def play_everything(page):
    """Every screen and dialog the game has, with real input."""
    page.wait_for_function('__pp.state().frames > 3')
    page.click('#helpButton')
    page.keyboard.press('Escape')
    page.click('#settingsButton')
    page.keyboard.press('Escape')
    page.click('#dailyButton')
    page.evaluate('__pp.freeze(true); __pp.setPatrols([{ x: 100, y: 60 }]); 0')
    page.evaluate('__pp.game.route.begin(30, 1); __pp.game.route.move(30, 71); 0')
    page.keyboard.press('p')
    page.keyboard.press('p')
    page.evaluate('__pp.forceWin(); 0')
    page.evaluate('__pp.game.startLevel(2); 0')
    page.evaluate('__pp.ui.el.shareText.value = "x"; __pp.ui.el.shareDialog.showModal(); 0')
    page.keyboard.press('Escape')
    page.evaluate('__pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')


def test_a_whole_session_breaks_no_rule_of_the_policy(open_page):
    page = open_page(path='/?debug=1&sw=1', init=[WATCH])
    play_everything(page)
    page.wait_for_function('navigator.serviceWorker.controller !== null', timeout=25_000)          # the worker, the manifest and the icons are in play too
    assert page.evaluate('window.__violations') == []


def test_the_worker_fetches_only_from_its_own_origin():
    """The policy in the page does not govern the worker's own requests, so the worker's code is held to it here."""
    worker = (SITE / 'sw.js').read_text()
    assert not re.search(r"https?://", re.sub(r'/\*.*?\*/', '', worker, flags=re.S))
