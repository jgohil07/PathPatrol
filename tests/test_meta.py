"""What the page says about itself: to a search result, to a link preview, to a browser or a person with no JavaScript. Read from the
markup as text, because that is what a crawler sees: nothing here needs the game to run."""
import json
import pathlib
import re
import struct
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
URL = 'https://jgohil07.github.io/PathPatrol/'


class Page(HTMLParser):
    """The head, and the few things in the body these tests care about."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.title, self.metas, self.links, self.scripts, self.noscript, self.anchors = '', [], [], [], '', []
        self._open = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._open.append(tag)
        if tag == 'meta':
            self.metas.append(attrs)
        elif tag == 'link':
            self.links.append(attrs)
        elif tag == 'script':
            self.scripts.append({**attrs, 'text': ''})
        elif tag == 'a':
            self.anchors.append(attrs)

    def handle_endtag(self, tag):
        if tag in self._open:
            while self._open and self._open.pop() != tag:
                pass

    def handle_data(self, data):
        if self._open and self._open[-1] == 'title':
            self.title += data
        elif self._open and self._open[-1] == 'script':
            self.scripts[-1]['text'] += data
        elif 'noscript' in self._open:
            self.noscript += data

    def meta(self, key, value):
        found = [m.get('content') for m in self.metas if m.get(key) == value]
        assert len(found) == 1, f'{key}={value}: expected one, found {len(found)}'
        return found[0]


def page():
    return Page((SITE / 'index.html').read_text())


def configured_share_url():
    return re.search(r"shareUrl: '([^']+)'", (SITE / 'js' / 'config.js').read_text()).group(1)


def png_size(path):
    return struct.unpack('>II', pathlib.Path(path).read_bytes()[16:24])


def test_the_title_and_description_fit_a_search_result():
    p = page()
    assert 'Path Patrol' in p.title and 20 <= len(p.title.strip()) <= 60
    description = p.meta('name', 'description')
    assert 70 <= len(description) <= 160, len(description)


def test_every_place_that_names_the_site_names_the_same_address():
    p = page()
    canonical = [l['href'] for l in p.links if l.get('rel') == 'canonical']
    assert canonical == [URL] and configured_share_url() == URL                            # the shared result points where the page says it lives
    assert p.meta('property', 'og:url') == URL
    sitemap = ET.parse(SITE / 'sitemap.xml').getroot()
    assert [e.text for e in sitemap.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')] == [URL]
    assert f'Sitemap: {URL}sitemap.xml' in (SITE / 'robots.txt').read_text().splitlines()


def test_a_link_preview_has_what_the_big_platforms_ask_for():
    p = page()
    assert p.meta('property', 'og:type') == 'website' and p.meta('property', 'og:site_name') == 'Path Patrol'
    assert p.meta('property', 'og:title') == p.title.strip() and p.meta('property', 'og:description') == p.meta('name', 'description')
    image = p.meta('property', 'og:image')
    assert image == URL + 'og.png' and (SITE / 'og.png').is_file()                          # absolute (a preview is fetched from elsewhere), and the file is the one that ships
    assert (int(p.meta('property', 'og:image:width')), int(p.meta('property', 'og:image:height'))) == png_size(SITE / 'og.png') == (1200, 630)
    assert len(p.meta('property', 'og:image:alt')) > 20
    assert p.meta('name', 'twitter:card') == 'summary_large_image'
    assert p.meta('name', 'twitter:title') == p.title.strip() and p.meta('name', 'twitter:description') == p.meta('name', 'description')
    assert p.meta('name', 'twitter:image') == image


def test_structured_data_describes_a_free_game_in_the_browser():
    blocks = [s for s in page().scripts if s.get('type') == 'application/ld+json']
    assert len(blocks) == 1
    data = json.loads(blocks[0]['text'])
    assert data['@context'] == 'https://schema.org' and data['@type'] == 'VideoGame' and data['name'] == 'Path Patrol'
    assert data['url'] == URL and data['image'] == URL + 'og.png'
    assert data['gamePlatform'] == 'Web browser' and data['playMode'] == 'SinglePlayer' and data['isAccessibleForFree'] is True
    assert data['offers']['price'] == '0' and data['author']['name'] == 'Jay'
    assert 70 <= len(data['description']) <= 300


def test_robots_lets_everything_in_and_the_sitemap_lists_the_one_page():
    lines = (SITE / 'robots.txt').read_text().splitlines()
    assert 'User-agent: *' in lines and 'Allow: /' in lines and not any(l.startswith('Disallow: /') and l != 'Disallow:' for l in lines)


def test_a_browser_with_no_javascript_is_told_why_nothing_happens():
    p = page()
    assert 'JavaScript' in p.noscript and len(p.noscript.strip()) > 40


def test_the_page_can_be_zoomed_and_says_what_language_it_is_in():
    p = page()
    viewport = p.meta('name', 'viewport')
    assert 'user-scalable=no' not in viewport.replace(' ', '') and 'maximum-scale' not in viewport
    assert re.search(r'<html lang="en"', (SITE / 'index.html').read_text())


def test_no_link_opens_a_new_tab_without_noopener():
    for anchor in page().anchors:
        if anchor.get('target') == '_blank':
            assert 'noopener' in anchor.get('rel', ''), anchor


def test_with_javascript_off_the_page_shows_the_message_alone_and_readably(open_page):
    """Nothing in the game can work without a script, so the dead controls stay out of the way of the one sentence that matters."""
    page = open_page(java_script_enabled=False, wait_ready=False, viewport={'width': 390, 'height': 700})
    note = page.locator('.noscript')
    assert note.is_visible() and 'JavaScript' in note.text_content()
    assert page.locator('#app').is_hidden()
    box = note.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 390 and 0 <= box['y'] and box['y'] + box['height'] <= 700
    colours = note.evaluate("(e) => [getComputedStyle(e).color, getComputedStyle(document.body).backgroundColor]")
    assert colours == ['rgb(232, 241, 238)', 'rgb(7, 11, 18)']                            # light on the page's near-black
