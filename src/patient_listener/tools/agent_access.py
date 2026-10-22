"""Trusted local provisioning of one agent/helper/person credential; never a public API."""
import argparse
from pathlib import Path
from ..store.sqlite_store import SqliteStore
from ..store.agent_store import AgentStore


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True,help='Existing app database file')
    sub=parser.add_subparsers(dest='command',required=True)
    grant=sub.add_parser('grant')
    grant.add_argument('--service',default='hermes')
    grant.add_argument('--helper',required=True,help='Existing linked carer/therapist ID')
    grant.add_argument('--person',required=True,help='Full patient ID')
    grant.add_argument('--hours',type=int,default=8)
    revoke=sub.add_parser('revoke')
    revoke.add_argument('--service',default='hermes')
    args=parser.parse_args(argv)
    if not Path(args.db).is_file(): parser.error('Use the existing server database file')
    store=SqliteStore(args.db)
    try:
        agent=AgentStore(store)
        if args.command == 'revoke':
            agent.revoke(args.service)
            print('Agent tool credentials revoked.')
            return 0
        helper=store.console_identity(args.helper)
        service=store.console_identity(args.service)
        if (not args.service or args.hours <= 0 or not helper
                or helper['role'] not in {'carer','therapist'}
                or args.person not in store.linked_people(args.helper)):
            parser.error('Use a positive lifetime and an existing helper linked to the person')
        if service and service['role'] != 'agent':
            parser.error('Service ID belongs to another role; choose a different ID')
        if not service: store.set_console_user(args.service,args.service,'agent')
        store.link_console_user(args.service,args.person)
        token=agent.issue_token(args.service,args.helper,args.person,args.hours*3600)
        print('Agent tools token (shown once; not a therapist token or Nebius key):')
        print(token)
        return 0
    finally: store.close()


if __name__ == '__main__':
    raise SystemExit(main())
