"""The test server itself. A flaky server means flaky tests, so it gets its own check."""
import http.client
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import serve  # noqa: E402


def test_a_burst_of_simultaneous_requests_loses_none():
    """socketserver's default listen backlog of 5 dropped about one request in ten at a burst of 8, which is
    what a page loading its module graph, fonts and sprites looks like. The server must take a burst of 32."""
    server = serve.make_server(ROOT / 'site')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    failures, statuses = [], []

    def fetch():
        try:
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            connection.request('GET', '/js/main.js')
            response = connection.getresponse()
            response.read()
            statuses.append(response.status)
            connection.close()
        except OSError as error:
            failures.append(repr(error))

    try:
        for _ in range(6):
            threads = [threading.Thread(target=fetch) for _ in range(32)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
    finally:
        server.shutdown()
    assert not failures, f'{len(failures)} of {len(failures) + len(statuses)} requests failed, e.g. {failures[0]}'
    assert set(statuses) == {200}


def test_the_types_the_browser_is_strict_about():
    """Browsers refuse ES modules served as text/plain and reject a manifest that is not application/manifest+json."""
    server = serve.make_server(ROOT / 'site')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=10)
        connection.request('GET', '/js/main.js')
        response = connection.getresponse()
        response.read()
        assert response.getheader('Content-Type').startswith('application/javascript')
        assert response.getheader('Cache-Control') == 'no-cache'
        connection.close()
    finally:
        server.shutdown()
