"""Design rules that are easy to break by accident: text contrast, self-hosted fonts that really load, nothing
fetched from anywhere but our own origin, and a visible keyboard focus ring."""
import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / 'site' / 'css' / 'app.css').read_text()
TOKENS = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-fA-F]{6})', CSS))
MIN_TEXT = 4.5            # WCAG AA for normal text; nearly all of this UI is small


def rgb(hex_colour):
    h = hex_colour.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(colour):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_the_tokens_the_tests_rely_on_exist():
    assert set(TOKENS) >= {'bg', 'raised', 'ink', 'ink-soft', 'muted', 'aqua', 'aqua-dim', 'coral', 'amber'}


def test_text_meets_contrast_on_the_page_and_on_dialogs():
    for fg, bg in [('ink', 'bg'), ('ink-soft', 'bg'), ('muted', 'bg'), ('aqua', 'bg'), ('amber', 'bg'), ('coral', 'bg'),
                   ('ink', 'raised'), ('ink-soft', 'raised'), ('muted', 'raised'), ('coral', 'raised'), ('aqua', 'raised')]:
        assert contrast(rgb(TOKENS[fg]), rgb(TOKENS[bg])) >= MIN_TEXT, f'{fg} on {bg}'
    assert '#04201b' in CSS                                                   # the primary button's dark text, checked next
    assert contrast(rgb('#04201b'), rgb(TOKENS['aqua'])) >= MIN_TEXT
    assert contrast(rgb(TOKENS['aqua-dim']), rgb(TOKENS['bg'])) >= 3          # the "> " prompt marker: decoration, but keep it legible


def test_overlay_text_is_readable_over_the_brightest_floor_of_every_level_palette(open_page):
    """The title, pause and game-over panels sit on a translucent overlay over the board, whose floor colour changes
    with the level and the theme. Check the brightest floor each palette can produce."""
    page = open_page()
    floors = page.evaluate("""async () => { const { paletteFor } = await import('/js/render.js'); const out = [];
      for (const theme of ['flight', 'drive']) for (let n = 1; n <= 6; n++) out.push([theme, n, paletteFor(theme, n)[0]]);
      return out; }""")
    assert len(floors) == 12
    m = re.search(r'\.overlay \{[^}]*background: rgba\((\d+), (\d+), (\d+), ([\d.]+)\)', CSS)
    over, alpha = tuple(int(m.group(i)) for i in (1, 2, 3)), float(m.group(4))
    for theme, level, floor in floors:
        # the board's top-left shade adds 8% white, which is as bright as the floor ever gets
        lit = tuple(v * 0.92 + 255 * 0.08 for v in rgb(floor))
        composite = tuple(over[i] * alpha + lit[i] * (1 - alpha) for i in range(3))
        for name in ('ink', 'ink-soft', 'muted'):
            ratio = contrast(rgb(TOKENS[name]), composite)
            assert ratio >= MIN_TEXT, f'{name} text over the {theme} level-{level} floor is {ratio:.2f}:1'


def test_the_self_hosted_fonts_really_load(open_page):
    page = open_page()
    page.wait_for_function('document.fonts.status === "loaded"')
    loaded = page.evaluate("""[...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/"/g, '') + ' ' + f.weight)""")
    assert 'DM Mono 400' in loaded and 'DM Mono 500' in loaded, loaded
    assert any(name.startswith('Space Grotesk') for name in loaded), loaded


def test_the_fonts_the_page_preloads_are_claimed_by_the_page_and_fetched_once(open_page, site_url):
    """A preload that the page's own request does not match is a font downloaded twice, and the browser says so a few seconds after the
    load. The fixture lets that warning pass (it also comes after a reload, harmlessly); on a load that stays it must never come."""
    page = open_page()
    heard = []
    page.on('console', lambda m: heard.append(m.text))
    page.wait_for_timeout(3600)
    page.evaluate('0')
    assert not [text for text in heard if 'preloaded using link preload' in text], heard
    fonts = [url for url in page.requests if url.endswith('.woff2')]
    assert len(fonts) == 3 and len(set(fonts)) == 3, fonts                       # two are preloaded, one is not; each was fetched exactly once
    preloaded = page.evaluate("[...document.querySelectorAll('link[rel=preload][as=font]')].map((l) => l.href)")
    assert preloaded and set(preloaded) <= set(fonts)


def test_nothing_is_fetched_from_outside_the_site(open_page, site_url):
    """No CDN, no analytics, no web fonts from a third party: a visitor's browser only ever talks to us."""
    page = open_page()
    page.click('#startButton')
    page.wait_for_timeout(300)
    foreign = [url for url in page.requests if not (url.startswith(site_url) or url.startswith('data:'))]
    assert foreign == []
    assert len(page.requests) > 10                                            # and it really did record the page's requests


def test_keyboard_focus_is_visible(open_page, engine):
    page = open_page()
    page.focus('#soundButton')
    # A keyboard move, so :focus-visible applies. Safari's default is that plain Tab skips buttons and Option+Tab
    # reaches them (verified with Playwright's WebKit: Tab lands on <body>), so that engine needs the Option key.
    page.keyboard.press('Alt+Tab' if engine == 'webkit' else 'Tab')
    ring = page.evaluate("""(() => { const s = getComputedStyle(document.activeElement);
      return { id: document.activeElement.id, style: s.outlineStyle, width: s.outlineWidth, colour: s.outlineColor }; })()""")
    assert ring['id'] == 'helpButton'
    assert ring['style'] == 'solid' and ring['width'] == '2px' and ring['colour'] == 'rgb(114, 244, 209)', ring
