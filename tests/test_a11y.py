"""Accessibility that is cheap to break: every control has a name, every reference between elements resolves, headings and
landmarks make sense, the board says what it is, and nothing steals the tab order. The markup is read as text (a crawler and a screen
reader start there); the running page is read through Playwright's own accessibility tree."""
import pathlib
import re
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'site' / 'index.html').read_text()


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.feed(SOURCE)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))

    def with_tag(self, tag):
        return [a for t, a in self.items if t == tag]


ELEMENTS = Elements()


def test_ids_are_unique_and_every_reference_between_elements_resolves():
    ids = [a['id'] for _, a in ELEMENTS.items if 'id' in a]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    for _, attrs in ELEMENTS.items:
        for key in ('aria-labelledby', 'aria-describedby', 'aria-controls', 'for'):
            for ref in attrs.get(key, '').split():
                assert ref in ids, f'{key}="{ref}" points at nothing'


def test_no_element_takes_a_place_in_the_tab_order_ahead_of_the_others():
    assert not [a for _, a in ELEMENTS.items if a.get('tabindex') not in (None, '0', '-1')]


def test_the_page_has_its_landmarks_once_and_one_top_heading_per_screen():
    assert [a for a in ELEMENTS.with_tag('header') if a.get('class') == 'bar'] and len(ELEMENTS.with_tag('header')) == 1 + len(ELEMENTS.with_tag('dialog'))      # the top bar, and one head in each dialog (which is no banner)
    for landmark in ('main', 'footer'):
        assert len(ELEMENTS.with_tag(landmark)) == 1, landmark
    assert len(ELEMENTS.with_tag('h1')) == 1                                        # the title screen's; the others are h2 (a level, a run) inside their overlays


def test_every_dialog_is_named_by_a_heading_that_exists():
    dialogs = ELEMENTS.with_tag('dialog')
    assert len(dialogs) == 3
    for d in dialogs:
        heading = d['aria-labelledby']
        assert any(a.get('id') == heading for t, a in ELEMENTS.items if t in ('h2', 'h3')), heading


def test_the_board_says_what_it_is_and_the_live_region_speaks_politely():
    board = [a for a in ELEMENTS.with_tag('canvas')]
    assert len(board) == 1 and board[0]['role'] == 'application' and board[0]['aria-roledescription'] == 'game board'
    assert board[0]['tabindex'] == '0' and 'arrow keys' in board[0]['aria-label']       # a keyboard player is told the keys where the focus lands
    live = [a for _, a in ELEMENTS.items if a.get('id') == 'announcer'][0]
    assert live['role'] == 'status' and live['aria-live'] == 'polite' and live['aria-atomic'] == 'true'


def test_decoration_is_hidden_from_assistive_technology():
    for tag, attrs in ELEMENTS.items:
        if tag == 'svg' and attrs.get('class', '').split()[:1] in (['icon'],):
            assert attrs.get('aria-hidden') == 'true', attrs


def controls(snapshot):
    """(role, name) of every interactive thing in a Playwright ARIA snapshot (YAML lines like `- button "Pause"`)."""
    found = []
    for line in snapshot.splitlines():
        m = re.match(r'\s*- \'?(button|switch|radio|checkbox|link|textbox|dialog)\b(?: "((?:[^"\\]|\\.)*)")?', line)      # (a name with a # in it makes YAML quote the whole key)
        if m:
            found.append((m.group(1), m.group(2)))
    return found


def test_every_control_on_every_screen_has_a_name(open_page):
    page = open_page(viewport={'width': 1280, 'height': 800})
    seen = set()

    def check(where):
        tree = controls(page.locator('body').aria_snapshot())
        assert tree, where
        unnamed = [role for role, name in tree if not name]
        assert not unnamed, f'{where}: unnamed {unnamed}'
        seen.update(name for _, name in tree)

    page.wait_for_function('__pp.state().frames > 3')
    check('title')
    page.click('#helpButton')
    check('help')
    page.keyboard.press('Escape')
    page.click('#settingsButton')
    check('settings')
    page.keyboard.press('Escape')
    page.click('#startButton')
    page.evaluate('__pp.freeze(true); 0')
    check('playing')
    page.keyboard.press('p')
    check('paused')
    page.keyboard.press('p')
    page.evaluate('__pp.forceWin(); 0')
    check('level clear')
    page.evaluate('__pp.game.startLevel(2); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife(); 0')
    check('game over')
    assert {'Start run', 'Sound', 'How to play', 'Settings', 'Pause', 'Close help', 'Close settings', 'Resume', 'Next level', 'New run',
            'Restart level', 'Play the tutorial', 'Reset local records'} <= seen, sorted(seen)
    assert any(name.startswith('Daily #') for name in seen), sorted(seen)                  # (the quoted-key lines are read too)


def test_the_game_can_be_played_and_left_with_the_keyboard_alone(open_page):
    """Tab reaches the board and the buttons, Enter starts a run, Escape leaves a dialog, and focus comes back to what opened it."""
    page = open_page(viewport={'width': 1280, 'height': 800})
    page.wait_for_function('__pp.state().frames > 3')
    page.focus('#helpButton')
    page.keyboard.press('Enter')
    assert page.evaluate("document.getElementById('helpDialog').open")
    assert page.evaluate('document.activeElement.closest("dialog") !== null')            # focus moved into the dialog
    page.keyboard.press('Escape')
    assert not page.evaluate("document.getElementById('helpDialog').open")
    assert page.evaluate('document.activeElement.id') == 'helpButton'                    # and came back
    page.focus('#startButton')
    page.keyboard.press('Enter')
    assert page.evaluate('__pp.state().phase') == 'playing'


def test_the_help_lists_every_key_the_game_answers_to():
    """A new shortcut added to the input layer has to be written down for the person who cannot see the board (this test says where)."""
    handled = set(re.findall(r"case '([^']+)':", (ROOT / 'site' / 'js' / 'input.js').read_text()))
    labels = {'p': 'P', 'Escape': 'Esc', 'm': 'M', 't': 'T', 'h': 'H', '?': '?', 'Enter': 'Enter', ' ': 'Space', 'r': 'R'}
    assert handled == set(labels), f'a key was added or removed in input.js: {sorted(handled ^ set(labels))}; update this table and the Help'
    dialog = SOURCE[SOURCE.index('id="helpDialog"'):]
    dialog = dialog[:dialog.index('</dialog>')]
    listed = set(re.findall(r'<kbd>([^<]+)</kbd>', dialog))
    assert set(labels.values()) <= listed and {'WASD', 'Backspace', 'Tab', 'Option'} <= listed, sorted(listed)
    assert 'arrow keys work too' in dialog and 'Safari' in dialog                          # the arrow keys steer as WASD do; Safari's Tab skips buttons unless Option is held
