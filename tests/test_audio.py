"""Sound and vibration. A real speaker cannot be listened to from a test, so a fake AudioContext is installed before
the page loads. It records every oscillator (its shape, start frequency, glide, length and loudness) and what the game
asked the context to do, so the rules can be checked: when the context may be created, when it must be woken, what each
event sounds like, that muting is immediate, and that a browser without audio or vibration is not an error."""
import pytest

DESKTOP = {'width': 1280, 'height': 800}

FAKE_AUDIO = """
(() => {
  const log = { contexts: 0, resumes: 0, oscs: [], ctx: null, nextState: 'running', fail: false };      // what resume() leads to
  class Param {
    constructor(value = 0) { this.events = []; this.value = value; }
    setValueAtTime(v, t) { this.events.push(['set', v, t]); this.value = v; }
    exponentialRampToValueAtTime(v, t) { this.events.push(['ramp', v, t]); this.value = v; }
    setTargetAtTime(v, t, c) { this.events.push(['target', v, t, c]); }
    cancelScheduledValues() { this.events.push(['cancel']); }
  }
  class Node { connect(to) { this.out = to; return to; } disconnect() {} }
  class Osc extends Node {
    constructor(ctx) { super(); this.ctx = ctx; this.type = 'sine'; this.frequency = new Param(440); this.startedAt = null; this.stoppedAt = null; }
    start(t) { this.startedAt = t === undefined ? null : t; this.begun = true; this.hum = t === undefined; }
    stop(t) { this.stoppedAt = t === undefined ? this.ctx.currentTime : t; }
    summary() {
      const sets = this.frequency.events.filter((e) => e[0] === 'set'), ramps = this.frequency.events.filter((e) => e[0] === 'ramp'), targets = this.frequency.events.filter((e) => e[0] === 'target');
      const amp = this.out && this.out.gain ? this.out.gain.events.filter((e) => e[0] === 'ramp').map((e) => e[1]) : [];
      return { type: this.type, freq: sets.length ? sets[0][1] : null, glide: ramps.length ? ramps[0][1] : null, start: this.startedAt,
               dur: this.startedAt !== null && this.stoppedAt !== null ? +(this.stoppedAt - this.startedAt - 0.03).toFixed(4) : null,
               gain: amp.length ? Math.max(...amp) : null, hum: !!this.hum, targets: targets.map((e) => e[1]), stopped: this.stoppedAt !== null };
    }
  }
  class Gain extends Node { constructor() { super(); this.gain = new Param(1); } }
  class FakeAudioContext {
    constructor() {
      if (log.fail) throw new Error('no audio here');
      log.contexts++; log.ctx = this; this.state = 'suspended'; this.currentTime = 0; this.destination = { fake: 'destination' };
    }
    createOscillator() { const o = new Osc(this); log.oscs.push(o); return o; }
    createGain() { return new Gain(); }
    resume() { log.resumes++; this.state = log.nextState; return Promise.resolve(); }
  }
  log.tones = () => log.oscs.filter((o) => o.begun && !o.hum).map((o) => o.summary());
  log.humOscs = () => log.oscs.filter((o) => o.hum).map((o) => o.summary());
  log.reset = () => { log.oscs.length = 0; };
  window.__audio = log;
  const variant = window.__audioVariant || 'standard';
  if (variant === 'standard') window.AudioContext = FakeAudioContext;
  else if (variant === 'webkit') { delete window.AudioContext; window.webkitAudioContext = FakeAudioContext; }
  else if (variant === 'none') { delete window.AudioContext; delete window.webkitAudioContext; }
})();
"""


def install(variant='standard'):
    return [f"window.__audioVariant = '{variant}';", FAKE_AUDIO]


VIBRATE = """
(() => { window.__vibes = []; Object.defineProperty(navigator, 'vibrate', { configurable: true, value: (pattern) => { window.__vibes.push(pattern); return true; } }); })();
"""
NO_VIBRATE = "Object.defineProperty(navigator, 'vibrate', { configurable: true, value: undefined });"


def start_sound_page(open_page, variant='standard', **kwargs):
    page = open_page(init=install(variant), viewport=kwargs.pop('viewport', DESKTOP), **kwargs)
    return page


def wake(page):
    """A gesture, so the context exists and is running."""
    page.mouse.click(5, 5)
    assert page.evaluate('__audio.ctx && __audio.ctx.state') == 'running'


def tones(page):
    return page.evaluate('__audio.tones()')


def frame(page):
    page.evaluate('new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def new_run(page, patrols='[{ x: 100, y: 60 }]'):
    page.evaluate(f'__pp.game.newRun({{ seed: "sound" }}); __pp.setPatrols({patrols}); if (window.__audio) __audio.reset()')


# ---- the context: when it may exist ------------------------------------------------------------------------
def test_no_audio_context_exists_until_a_gesture_and_then_it_is_woken(open_page):
    page = start_sound_page(open_page)
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40)')                                        # game events with no gesture behind them
    frame(page)
    assert page.evaluate('__audio.contexts') == 0 and tones(page) == []            # nothing is created, nothing plays
    page.mouse.click(5, 5)
    assert page.evaluate('__audio.contexts') == 1 and page.evaluate('__audio.resumes') >= 1
    assert page.evaluate('__audio.ctx.state') == 'running'
    page.keyboard.press('x')
    page.mouse.click(9, 9)
    assert page.evaluate('__audio.contexts') == 1                                   # one context, however many gestures


def test_a_muted_profile_creates_nothing_until_sound_is_switched_on(open_page):
    page = start_sound_page(open_page)
    page.evaluate("""localStorage.setItem('pathpatrol:v2', JSON.stringify({ v: 2, settings: { sound: false, tutorialDone: true }, records: {} }))""")
    page.reload()
    page.wait_for_function('window.__pp !== undefined')
    page.mouse.click(5, 5)
    page.keyboard.press('Enter')
    assert page.evaluate('__audio.contexts') == 0
    page.click('#soundButton')                                                        # switching it on is itself the gesture
    assert page.evaluate('__audio.contexts') == 1 and page.evaluate('__audio.ctx.state') == 'running'


def test_the_older_webkit_name_is_used_when_the_standard_one_is_missing(open_page):
    page = start_sound_page(open_page, 'webkit')
    assert page.evaluate('typeof window.AudioContext') == 'undefined'
    wake(page)
    assert page.evaluate('__audio.contexts') == 1


def test_a_browser_without_audio_or_with_a_failing_context_just_plays_on_silently(open_page):
    page = start_sound_page(open_page, 'none')
    page.mouse.click(5, 5)
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40)')
    assert page.evaluate('__pp.state().phase') == 'playing'
    page = start_sound_page(open_page)
    page.evaluate('__audio.fail = true')
    page.mouse.click(5, 5)                                                            # the constructor throws: swallowed
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40)')
    assert page.evaluate('__pp.state().phase') == 'playing' and page.evaluate('__audio.contexts') == 0


def test_an_interrupted_context_is_woken_again_by_the_next_gesture(open_page):
    """iOS puts the context into 'interrupted' after a call or an app switch; only a gesture brings it back."""
    page = start_sound_page(open_page)
    wake(page)
    resumes = page.evaluate('__audio.resumes')
    page.evaluate("__audio.ctx.state = 'interrupted'")
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40)')
    assert tones(page) == []                                                          # an interrupted context is not played into
    page.mouse.click(7, 7)
    assert page.evaluate('__audio.resumes') > resumes and page.evaluate('__audio.ctx.state') == 'running'
    page.evaluate('__audio.reset(); __pp.game.newRun({ seed: "again" }); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40)')
    assert len(tones(page)) >= 1                                                      # and it plays again


# ---- what each event sounds like ---------------------------------------------------------------------------------
def test_a_capture_chime_has_more_notes_and_more_volume_the_bigger_the_capture(open_page):
    page = start_sound_page(open_page)
    wake(page)
    got = {}
    # Cuts down the board with a patrol parked on the far side; the share of the field claimed is 4 columns + the cut, over 232.
    #   x = 3.5 -> 1.7 %   x = 12 -> 9.1 %   x = 25 -> 20.3 %   x = 40 -> 33.2 %   (none reaches the 65 % target, so no level clear)
    for name, unit_x in (('small', 3.5), ('medium', 12), ('large', 25), ('huge', 40)):
        new_run(page, '[{ x: 118, y: 36 }]')
        page.evaluate(f'__pp.cutLine("v", {unit_x})')
        got[name] = [t for t in tones(page)]
    assert [len(got[n]) for n in ('small', 'medium', 'large', 'huge')] == [1, 2, 3, 4]      # <2%: one note, <10%: two, <25%: three, more: four
    assert [got[n][0]['gain'] for n in ('small', 'medium', 'large', 'huge')] == [0.10, 0.13, 0.16, 0.19]
    assert all(t['freq'] == pytest.approx(523.25) for t in [got['small'][0]])
    assert [round(t['freq'], 2) for t in got['large']] == [523.25, round(523.25 * 2 ** (4 / 12), 2), round(523.25 * 2 ** (7 / 12), 2)]   # a major triad on C5
    assert [t['start'] for t in got['huge']] == pytest.approx([0, 0.07, 0.14, 0.21], abs=0.02)                                    # struck in turn


def test_a_higher_combo_raises_the_chime_a_semitone_step_at_a_time(open_page):
    page = start_sound_page(open_page)
    wake(page)
    new_run(page)
    freqs = []
    for x in (8, 10, 12, 14, 16, 18, 20, 22, 24, 26):                                 # ten captures: the combo climbs x1 ... x3
        page.evaluate('__audio.reset()')
        page.evaluate(f'__pp.cutLine("v", {x})')
        freqs.append(tones(page)[0]['freq'])
    base = 523.25
    expected = [round(base * 2 ** (round((min(1 + 0.25 * i, 3) - 1) * 4) / 12), 2) for i in range(10)]
    assert [round(f, 2) for f in freqs] == expected
    assert freqs[0] < freqs[4] < freqs[8] and freqs[8] == freqs[9]                     # rising, then held at the x3 ceiling


def test_each_game_event_has_its_own_sound(open_page):
    page = start_sound_page(open_page)
    wake(page)
    heard = {}

    def capture(name):
        heard[name] = tones(page)
        page.evaluate('__audio.reset()')

    new_run(page)
    page.evaluate('__pp.game.route.begin(40, 1)')                                     # touching an edge: a short tick
    capture('armed')
    page.evaluate('__pp.game.route.move(40, 20); __pp.game.route.end("lift")')        # letting go in the field: a soft falling blip
    heard['lifted'] = [t for t in tones(page) if not t['hum']]
    new_run(page, '[{ x: 40, y: 20 }]')
    page.evaluate('__pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')       # drawn into a patrol: the buzz
    heard['hit'] = tones(page)
    new_run(page, '[{ x: 43, y: 36 }]')
    page.evaluate('const r = __pp.game.route; r.begin(40, 1); r.move(40, 36); for (let i = 0; i < 12; i++) __pp.game.step(1 / 120)')   # a patrol just missing it: a ping
    heard['closecall'] = [t for t in tones(page) if t['freq'] > 1000]
    new_run(page, '[]')
    page.evaluate('__pp.forceWin()')                                                   # the whole field with no patrol: a real level clear
    heard['clear'] = tones(page)
    new_run(page)
    page.evaluate('__pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife()')
    heard['over'] = tones(page)

    assert [(t['freq'], t['type']) for t in heard['armed']] == [(920, 'triangle')] and heard['armed'][0]['dur'] == pytest.approx(0.035)
    assert [(t['freq'], t['glide']) for t in heard['lifted']] == [(330, 210)]
    assert sorted((t['type'], t['freq'], t['glide']) for t in heard['hit'] if t['type'] in ('sawtooth', 'square')) == [('sawtooth', 118, 66), ('square', 59, 40)]
    assert all(t['freq'] < 200 for t in heard['hit'] if t['type'] in ('sawtooth', 'square'))     # low and short: it is a buzz, not a note
    assert [t['freq'] for t in heard['closecall']] == [1480]
    clear = heard['clear']                                                             # the whole field's chime (4 notes), then the clear arpeggio
    assert len(clear) == 4 + 5
    assert [t['freq'] for t in clear[-5:]] == pytest.approx([523.25 * 2 ** (n / 12) for n in (0, 4, 7, 12, 16)])          # C E G C E, rising
    assert [t['start'] for t in clear[-5:]] == pytest.approx([0, 0.09, 0.18, 0.27, 0.36], abs=0.01)
    assert [t['freq'] for t in heard['over'] if t['type'] == 'triangle'] == pytest.approx([(523.25 / 2) * 2 ** (n / 12) for n in (7, 4, 0)], rel=1e-6)   # three falling notes


def test_no_tone_is_loud_long_or_clicky(open_page):
    """Every voice must sit well under full scale so they can overlap, be short, and have an attack ramp (no click)."""
    page = start_sound_page(open_page)
    wake(page)
    new_run(page, '[{ x: 43, y: 36 }]')
    page.evaluate('const r = __pp.game.route; r.begin(40, 1); r.move(40, 36); for (let i = 0; i < 12; i++) __pp.game.step(1 / 120); r.move(40, 71)')
    page.evaluate('__pp.game.emit("extraLife", { lives: 4 }); __pp.forceWin()')
    new_run(page, '[]')
    page.evaluate('__audio.reset(); __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife()')
    page.evaluate('__pp.sound.pickup(); __pp.sound.lifted(); __pp.sound.tick(); __pp.sound.buzz(); __pp.sound.ping()')
    every = tones(page)
    assert len(every) > 8
    assert all(t['gain'] is not None and 0 < t['gain'] <= 0.2 for t in every)
    assert all(t['dur'] is not None and 0 < t['dur'] <= 0.31 for t in every)
    assert page.evaluate('__pp.sound.master.gain.value') == pytest.approx(0.35)         # the overall level is set, not left at full


# ---- the drawing hum ----------------------------------------------------------------------------------------------
def test_the_hum_rises_with_the_route_and_stops_when_it_ends_however_it_ends(open_page):
    page = start_sound_page(open_page)
    wake(page)
    new_run(page, '[{ x: 100, y: 60 }]')
    page.evaluate('__pp.freeze(true); __pp.game.route.begin(40, 1)')
    frame(page)
    assert page.evaluate('__audio.humOscs().length') == 0                              # armed on an edge: not humming yet
    page.evaluate('__pp.game.route.move(40, 8)')
    frame(page)
    page.evaluate('__pp.game.route.move(40, 25)')
    frame(page)
    page.evaluate('__pp.game.route.move(40, 45)')
    frame(page)
    page.evaluate('__pp.game.route.move(90, 45); __pp.game.route.move(90, 10)')      # a long winding route: over 240 cells, past the pitch ceiling
    frame(page)
    assert page.evaluate('__pp.game.route.cells.length') > 245                          # comfortably beyond the 240-cell ceiling
    page.evaluate('__pp.game.route.move(110, 10)')
    frame(page)
    hum = page.evaluate('__audio.humOscs()')
    assert len(hum) == 1 and hum[0]['type'] == 'sine' and hum[0]['freq'] == 150 and not hum[0]['stopped']
    assert hum[0]['targets'] == sorted(hum[0]['targets']) and len(set(hum[0]['targets'])) >= 3 and hum[0]['targets'][-1] > hum[0]['targets'][0] + 40   # higher as it grows
    assert max(hum[0]['targets']) == pytest.approx(150 + 240 * 2.2)                    # ...and it stops rising at a ceiling once the route is long enough
    assert hum[0]['targets'][-1] == hum[0]['targets'][-2]                              # (two frames on a route that only got longer: the same pitch)

    for how, action in (('closes', '__pp.game.route.move(40, 71)'), ('lifted', '__pp.game.route.end("lift")'), ('paused', '__pp.game.pause("manual")'),
                        ('hit', '__pp.setPatrols([{ x: 40, y: 50 }]); __pp.game.route.move(40, 60)')):
        new_run(page, '[{ x: 100, y: 60 }]')
        frame(page)                                                                    # the engine polls once a frame: let it see the gap between routes
        page.evaluate('__audio.reset(); __pp.freeze(true); __pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')
        frame(page)
        assert page.evaluate('__audio.humOscs().length') == 1 and not page.evaluate('__audio.humOscs()[0].stopped'), how
        page.evaluate(action)
        frame(page)
        assert page.evaluate('__audio.humOscs().every((h) => h.stopped)'), how          # every hum has been told to stop
        assert page.evaluate('__pp.sound.hum') is None, how


def test_muting_silences_the_hum_and_everything_after_at_once(open_page):
    page = start_sound_page(open_page)
    wake(page)
    new_run(page)
    page.evaluate('__pp.freeze(true); __pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')
    frame(page)
    assert page.evaluate('__audio.humOscs().length') == 1
    page.click('#soundButton')                                                          # mute, mid-route
    assert page.evaluate('__pp.storage.settings.sound') is False and page.evaluate('__pp.sound.hum') is None
    assert page.evaluate('__audio.humOscs().every((h) => h.stopped)')
    page.evaluate('__audio.reset(); __pp.game.route.move(40, 71)')                       # the route closes: a capture, but no chime
    page.evaluate('__pp.game.loseLife(); __pp.game.route.begin(60, 1)')
    frame(page)
    assert tones(page) == [] and page.evaluate('__audio.humOscs().length') == 0
    page.click('#soundButton')                                                          # and back on
    page.evaluate('__audio.reset(); __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 30)')
    assert len(tones(page)) >= 1


# ---- vibration -----------------------------------------------------------------------------------------------------
def test_vibration_follows_the_events_and_the_setting(open_page):
    page = open_page(init=[VIBRATE], viewport=DESKTOP)
    new_run(page, '[{ x: 40, y: 20 }]')
    page.evaluate('__vibes.length = 0; __pp.game.route.begin(40, 1); __pp.game.route.move(40, 30)')          # into a patrol
    hit = page.evaluate('__vibes.slice()')
    new_run(page)
    page.evaluate('__vibes.length = 0')
    got = {}
    for name, x in (('small', 3.5), ('medium', 12), ('large', 40)):
        new_run(page, '[{ x: 118, y: 36 }]' if name != 'small' else '[{ x: 100, y: 60 }]')
        page.evaluate('__vibes.length = 0')
        page.evaluate(f'__pp.cutLine("v", {x})')
        got[name] = page.evaluate('__vibes.slice()')
    new_run(page)
    page.evaluate('__vibes.length = 0; __pp.game.emit("extraLife", { lives: 4 })')
    life = page.evaluate('__vibes.slice()')
    page.evaluate('__vibes.length = 0; __pp.game.loseLife(); __pp.game.loseLife(); __pp.game.loseLife()')
    over = page.evaluate('__vibes.slice()')
    assert hit == [[40]] and got == {'small': [[6]], 'medium': [[12]], 'large': [[10, 30, 16]]}
    assert life == [[15, 40, 15]] and over == [[60, 40, 60]]

    page.click('#settingsButton')                                                        # switch it off in Settings
    page.click('#hapticsSwitch')
    assert page.evaluate('__pp.storage.settings.haptics') is False
    page.keyboard.press('Escape')
    new_run(page)
    page.evaluate('__vibes.length = 0; __pp.setPatrols([{ x: 100, y: 60 }]); __pp.cutLine("v", 40); __pp.game.loseLife()')
    assert page.evaluate('__vibes.length') == 0                                          # off means off


def test_the_vibration_switch_only_exists_where_the_browser_can_vibrate(open_page):
    page = open_page(init=[NO_VIBRATE], viewport=DESKTOP)
    page.click('#settingsButton')
    assert page.locator('#hapticsRow').is_hidden()
    page2 = open_page(init=[VIBRATE], viewport=DESKTOP)
    page2.click('#settingsButton')
    assert page2.locator('#hapticsRow').is_visible() and page2.locator('#hapticsSwitch').get_attribute('aria-checked') == 'true'
    page2.evaluate('__vibes.length = 0')
    page2.click('#hapticsSwitch')
    page2.click('#hapticsSwitch')                                                        # turning it on gives a taste of it
    assert page2.evaluate('__vibes.slice()') == [[12]]


def test_a_vibrate_that_throws_or_is_missing_never_breaks_the_game(open_page):
    page = open_page(init=["Object.defineProperty(navigator, 'vibrate', { configurable: true, value: () => { throw new Error('not allowed'); } });"], viewport=DESKTOP)
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40); __pp.game.loseLife()')
    assert page.evaluate('__pp.state().phase') == 'playing'
    page = open_page(init=[NO_VIBRATE], viewport=DESKTOP)
    new_run(page)
    page.evaluate('__pp.cutLine("v", 40); __pp.game.loseLife()')
    assert page.evaluate('__pp.state().phase') == 'playing'
