# Path Patrol: common tasks.  `make setup` once, then `make serve` or `make test`.
PY := .venv/bin/python

.PHONY: setup serve test

setup:            ## create the test venv and fetch the WebKit build
	python3 -m venv .venv
	$(PY) -m pip install -r tests/requirements.txt
	$(PY) -m playwright install webkit

serve:            ## serve site/ at http://127.0.0.1:8000/
	python3 tools/serve.py

test:             ## run the whole suite on Chromium (installed Chrome) and WebKit
	$(PY) -m pytest tests
