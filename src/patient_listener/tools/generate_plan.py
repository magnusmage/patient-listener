"""Request a bounded plan from the running local GPU server; credentials stay off argv."""
from __future__ import annotations
import argparse
import getpass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never forward a console credential to a redirected host


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a plan using the running local server. Defaults: 1 word, templates, GPU hint audio.')
    parser.add_argument('--person', default='margaret')
    parser.add_argument('--status', action='store_true', help='Read nightly schedule and recent runs; no generation')
    parser.add_argument('--max-words', type=int, choices=range(1,11), default=1)
    parser.add_argument('--use-ai', action='store_true', help='Opt in to at most one Super request per selected word (can spend credits)')
    parser.add_argument('--text-only', action='store_true', help='Save hints/plan without generating GPU audio')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    token = getpass.getpass('Therapist/carer console token (not the Nebius key): ').strip()
    if not token or any(ord(c) < 32 or ord(c) == 127 for c in token):
        parser.error('Enter a valid console token')
    body = {'max_words': args.max_words, 'use_ai': args.use_ai, 'render_audio': not args.text_only}
    if not args.status:
        print('Maximum Super requests:', args.max_words if args.use_ai else 0)
    url = f'http://127.0.0.1:{args.port}/api/console/plans/{quote(args.person, safe="")}/generate'
    if args.status:
        url = f'http://127.0.0.1:{args.port}/api/console/nightly/{quote(args.person, safe="")}'
    request = Request(url, data=None if args.status else json.dumps(body).encode(), headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
        method='GET' if args.status else 'POST')
    try:
        with build_opener(NoRedirect).open(request, timeout=600) as response:
            print(json.dumps(json.load(response), indent=2))
    except HTTPError as exc:
        # Server responses contain fixed messages, never model or transcript payloads.
        try:
            detail = json.load(exc).get('detail', 'Request rejected')
        except (ValueError, AttributeError):
            detail = 'Request rejected'
        print(f'Plan not generated (HTTP {exc.code}): {detail}')
        return 1
    except URLError:
        print('Could not reach the local server. Start it and check the port.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
