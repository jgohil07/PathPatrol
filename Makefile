# Path Patrol: common tasks.  `make setup` once, then `make serve` or `make test`.
PY := .venv/bin/python

.PHONY: setup serve test check sw icons screenshots

setup:            ## create the test venv and fetch the WebKit build
	python3 -m venv .venv
	$(PY) -m pip install -r tests/requirements.txt
	$(PY) -m playwright install webkit

serve:            ## serve site/ at http://127.0.0.1:8000/
	python3 tools/serve.py

test:             ## run the whole suite on Chromium (installed Chrome) and WebKit
	$(PY) -m pytest tests

sw:               ## rewrite the file list and hash in site/sw.js: run it after ANY change under site/
	python3 tools/make_sw.py

check:            ## fail if site/sw.js is out of date (the tests and CI check this too)
	python3 tools/make_sw.py --check

icons:            ## redraw site/icons/ (no dependencies), then run `make sw`
	python3 tools/make_icons.py

screenshots:      ## retake the manifest's screenshots and the social image from the real game (not part of the offline shell)
	$(PY) tools/make_screenshots.py
