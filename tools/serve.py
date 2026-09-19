#!/usr/bin/env python3
"""Static server for site/ with the right MIME types and no caching.

    python3 tools/serve.py [--port 8000] [--dir site] [--verbose]

The MIME types matter: browsers refuse ES modules served as text/plain and reject a manifest that is
not application/manifest+json, so the test server is deliberately as strict as GitHub Pages.
"""
import argparse
import functools
import http.server
import mimetypes
import pathlib

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('application/manifest+json', '.webmanifest')
mimetypes.add_type('font/woff2', '.woff2')
mimetypes.add_type('image/svg+xml', '.svg')

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Handler(http.server.SimpleHTTPRequestHandler):
    verbose = False

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, fmt, *args):
        if self.verbose:
            super().log_message(fmt, *args)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # socketserver's default listen backlog is 5. A page loading its module graph, fonts and sprites opens
    # connections in a burst, and with a backlog of 5 a burst of 8 already lost about one request in ten
    # (measured: 6 of 64; 105 of 240 at a burst of 30). A dropped request stalls or fails the page load.
    request_queue_size = 128


def make_server(directory, port=0, verbose=False):
    """A server bound to 127.0.0.1. port=0 picks a free port (see server.server_address)."""
    handler = type('BoundHandler', (Handler,), {'verbose': verbose})
    return Server(('127.0.0.1', port), functools.partial(handler, directory=str(directory)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--dir', default=str(ROOT / 'site'))
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    server = make_server(args.dir, args.port, args.verbose)
    print(f'Serving {args.dir} at http://127.0.0.1:{server.server_address[1]}/  (Ctrl+C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == '__main__':
    main()
