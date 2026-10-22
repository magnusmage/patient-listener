"""Provision or revoke console access from a trusted local terminal.

This is the administrative bootstrap for access-token sign-in, not a public registration API.
Tokens expire, are stored only as hashes, and should be supplied privately to their owner.
"""

import argparse

from ..store.factory import open_admin_store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Existing SQLite file; omit for PostgreSQL DATABASE_URL")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant", help="Set identity, add patient links, replace existing tokens")
    grant.add_argument("--user", required=True)
    grant.add_argument("--name", required=True)
    grant.add_argument("--role", required=True, choices=("therapist", "carer"))
    grant.add_argument("--person", action="append", required=True, help="Patient ID; repeat for each link")
    grant.add_argument("--hours", type=int, default=8, help="Access-token lifetime (default: 8 hours)")
    revoke = sub.add_parser("revoke", help="Revoke every access token for an identity")
    revoke.add_argument("--user", required=True)
    args = parser.parse_args()
    try: store = open_admin_store(args.db)
    except ValueError as exc: parser.error(str(exc))
    try:
        if args.command == "revoke":
            store.revoke_console_tokens(args.user)
            print("Console access tokens revoked.")
            return
        if args.hours <= 0 or any(not store.person_exists(pid) for pid in args.person):
            parser.error("supply a positive lifetime and existing patient IDs")
        store.set_console_user(args.user, args.name, args.role)
        for pid in args.person:
            store.link_console_user(args.user, pid)
        token = store.issue_console_token(args.user, ttl_s=args.hours * 3600)
        print("Access token (shown once; enter it on the console sign-in screen):")
        print(token)
    finally:
        store.close()


if __name__ == "__main__":
    main()
