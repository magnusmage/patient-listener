"""Exercise privacy APIs on the running local server; credentials never enter argv."""
import argparse
import getpass
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener
from .generate_plan import NoRedirect


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'delete', 'receipt', 'purge-consent'])
    parser.add_argument('--person', help='Person alias or full ID; required for export/delete')
    parser.add_argument('--out', help='New CSV file for export (existing files are never overwritten)')
    parser.add_argument('--receipt', help='Receipt ID returned by deletion')
    parser.add_argument('--db', help='Existing SQLite file, only for purge-consent')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args(argv)
    if args.action == 'purge-consent':
        from ..store.factory import open_admin_store
        from ..store.privacy import PrivacyStore
        store = open_admin_store(args.db)
        try: print(json.dumps(PrivacyStore(store).purge_expired_consent()))
        finally: store.close()
        return 0
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1..65535')
    if args.action in {'export', 'delete'} and not args.person:
        parser.error('--person is required')
    if args.action == 'export' and (not args.out or Path(args.out).exists()):
        parser.error('--out must name a new CSV file')
    if args.action == 'receipt' and not args.receipt:
        parser.error('--receipt is required')
    token = getpass.getpass('Linked therapist/carer console token (not the Nebius key): ').strip()
    if not token or len(token) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in token):
        parser.error('Enter a valid console token')
    opener = build_opener(NoRedirect)
    base = f'http://127.0.0.1:{args.port}/api/console/'

    def call(path, method='GET', body=None):
        request = Request(base+path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
        with opener.open(request, timeout=60) as response:
            return response.read()

    try:
        if args.action == 'receipt':
            result = json.loads(call('deletions/'+quote(args.receipt, safe='')))
        else:
            path = 'privacy/'+quote(args.person, safe='')
            if args.action == 'export':
                if input('Has the person explicitly requested this export? Type YES: ') != 'YES':
                    print('Cancelled.'); return 0
                data = call(path+'/export', 'POST', {'personConfirmed': True})
                with Path(args.out).open('xb') as output: output.write(data)
                print('CSV saved to:', args.out)
                return 0
            challenge = json.loads(call(path+'/deletion-request', 'POST'))
            print('Delete application data for:', challenge['person_id'])
            print(challenge['retained_records'])
            print('Stop practice first. Deletion cannot be undone. The person must explicitly request it.')
            expected = 'DELETE '+challenge['person_id']
            if input('To confirm, type '+expected+': ') != expected:
                print('Cancelled. No data was deleted.'); return 0
            result = json.loads(call(path, 'DELETE', {'personConfirmed': True,
                'confirmationToken': challenge['confirmation_token']}))
        print(json.dumps(result, indent=2))
    except HTTPError as exc:
        try: detail = json.load(exc).get('detail', 'Request rejected')
        except (ValueError, AttributeError): detail = 'Request rejected'
        print(f'Privacy operation rejected (HTTP {exc.code}): {detail}')
        return 1
    except URLError:
        print('Could not reach the local server. Check the port.')
        return 1
    except OSError:
        print('Could not write the export file. Check its path and permissions.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
