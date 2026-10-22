"""Exercise the restricted tools against a local server; no LLM or Telegram calls."""
import argparse
import getpass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from .generate_plan import NoRedirect


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8000)
    sub=parser.add_subparsers(dest='command',required=True)
    add=sub.add_parser('add-word')
    add.add_argument('--text',required=True)
    add.add_argument('--kind',required=True,choices=('person','place','food','object','activity','phrase'))
    add.add_argument('--meaning-cue',default='')
    add.add_argument('--first-sound',default='')
    add.add_argument('--request-id',required=True,help='Stable ID for this tool call; reuse only for the same draft')
    sub.add_parser('summary')
    args=parser.parse_args(argv)
    if not 1 <= args.port <= 65535: parser.error('Invalid port')
    token=getpass.getpass('Agent tools token: ').strip()
    if not token.startswith('plagent_') or any(ord(c)<32 or ord(c)==127 for c in token):
        parser.error('Use a provisioned agent token')
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    body=None
    if args.command == 'add-word':
        endpoint='add_word_draft'
        headers['Idempotency-Key']=args.request_id
        body=json.dumps({'text':args.text,'kind':args.kind,'meaning_cue':args.meaning_cue,
                         'first_sound':args.first_sound}).encode()
    else: endpoint='progress_summary'
    request=Request(f'http://127.0.0.1:{args.port}/api/agent/tools/{endpoint}',data=body,
                    headers=headers,method='POST' if body else 'GET')
    try:
        with build_opener(NoRedirect).open(request,timeout=10) as response:
            print(json.dumps(json.load(response),indent=2))
    except HTTPError as exc:
        print(f'Tool request rejected (HTTP {exc.code}). Check credential, links and input.')
        return 1
    except (URLError,TimeoutError):
        print('Tool request did not complete. Check the server; retry drafts with the SAME request ID.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
