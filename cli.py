#!/usr/bin/env python3
"""TC Lab command-line administration.

Emergency access for an administrator with shell access — used when the
dashboard admin password has been lost. It can only *reset* the admin
password; there is deliberately no way to read or display an existing
password, because passwords are stored only as one-way bcrypt hashes.

    sudo tc-lab reset-admin-password
    sudo tc-lab list-users
    sudo tc-lab --help

Run from the install directory, or set TC_LAB_STATE_DIR to point at the
directory holding users.json.
"""
import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path

# Import the app's own auth module so the password policy and hashing are
# identical to the dashboard's — they can never drift apart.
sys.path.insert(0, str(Path(__file__).parent.resolve()))
try:
    import auth
except ImportError as e:                                    # pragma: no cover
    sys.exit(f"error: cannot import the application (auth.py): {e}\n"
             "Run this from the TC Lab install directory, e.g.\n"
             "  cd /opt/tc_lab && sudo venv/bin/python cli.py reset-admin-password")

ADMIN_USER = "admin"
EXIT_OK, EXIT_ERR, EXIT_PERM = 0, 1, 2


def _err(msg):
    print(f"error: {msg}", file=sys.stderr)


def require_root():
    """The user store is root-owned (0600); refuse early with a clear message
    rather than failing later on a confusing permission error."""
    if os.geteuid() != 0:
        _err("this command must be run as root (try: sudo tc-lab ...)")
        sys.exit(EXIT_PERM)


def _getpass(prompt):
    """getpass, but a closed stdin or Ctrl-C exits cleanly instead of dumping a
    traceback — this tool is used when things are already going wrong."""
    try:
        return getpass.getpass(prompt)
    except EOFError:
        print()
        _err("no input received — password unchanged")
        sys.exit(EXIT_ERR)
    except KeyboardInterrupt:
        print()
        _err("cancelled — password unchanged")
        sys.exit(EXIT_ERR)


def _prompt_new_password():
    """Read a password twice, without echoing it. Never logged or printed."""
    sys.stdout.flush()          # keep prompts after the context lines when piped
    for _ in range(3):
        pw = _getpass("New admin password: ")
        problem = auth.validate_password(pw)
        if problem:
            _err(problem)
            continue
        if pw != _getpass("Retype new admin password: "):
            _err("passwords do not match")
            continue
        return pw
    _err("too many failed attempts — password unchanged")
    sys.exit(EXIT_ERR)


def cmd_reset_admin_password(args):
    require_root()
    users_file = auth.USERS_FILE
    print(f"User store: {users_file}")

    users = auth._load_users()
    if users_file.exists() and not users:
        _err(f"{users_file} exists but could not be parsed — refusing to "
             "overwrite it. Fix or move the file, then retry.")
        return EXIT_ERR

    existing = ADMIN_USER in users
    if existing:
        print(f"Resetting the password for '{ADMIN_USER}'. "
              f"{len(users) - 1} other account(s) will be left untouched.")
    else:
        print(f"No '{ADMIN_USER}' account found — it will be recreated "
              f"with the admin role. {len(users)} other account(s) preserved.")

    password = args.password or _prompt_new_password()
    problem = auth.validate_password(password)
    if problem:
        _err(problem)
        return EXIT_ERR

    # Back up the store before touching it, so a bad write is recoverable.
    if users_file.exists():
        backup = users_file.with_suffix(".json.bak")
        try:
            shutil.copy2(users_file, backup)
            os.chmod(backup, 0o600)
            print(f"Backup written: {backup}")
        except OSError as e:
            _err(f"could not write backup: {e}")
            return EXIT_ERR

    # Update only this account's hash; every other user and their role is
    # carried across untouched, and no other application config is read or
    # written by this command.
    users.setdefault(ADMIN_USER, {})
    users[ADMIN_USER]["hash"] = auth.hash_password(password)
    users[ADMIN_USER]["role"] = "admin"     # recovery must restore admin rights
    try:
        auth._save_users(users)
    except OSError as e:
        _err(f"could not write {users_file}: {e}")
        return EXIT_ERR

    # Read back and verify before claiming success.
    written = auth._load_users()
    if ADMIN_USER not in written or not auth.check_password(
            password, written[ADMIN_USER]["hash"]):
        _err("verification failed — the password was NOT changed")
        return EXIT_ERR

    print()
    print(f"SUCCESS: password for '{ADMIN_USER}' has been reset.")
    print(f"         role: admin   accounts in store: {len(written)}")
    print("         Sign in at the dashboard with the new password.")
    return EXIT_OK


def cmd_list_users(args):
    require_root()
    users = auth.list_users()          # never includes hashes
    if not users:
        print("No accounts found. Start the service once to create the "
              "default admin account.")
        return EXIT_OK
    if args.json:
        print(json.dumps(users, indent=2))
        return EXIT_OK
    width = max(len(u["username"]) for u in users)
    print(f"{'USERNAME':<{max(width, 8)}}  ROLE")
    for u in users:
        print(f"{u['username']:<{max(width, 8)}}  {u['role']}")
    print(f"\n{len(users)} account(s) in {auth.USERS_FILE}")
    return EXIT_OK


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="tc-lab", description=__doc__.split("\n\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Passwords can only be reset, never displayed.")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    r = sub.add_parser("reset-admin-password",
                       help="reset the dashboard admin password (root only)")
    # Hidden, for automated provisioning; interactive use should omit it so the
    # password never lands in the shell history or the process list.
    r.add_argument("--password", help=argparse.SUPPRESS)
    r.set_defaults(func=cmd_reset_admin_password)

    l = sub.add_parser("list-users", help="list accounts and roles (no hashes)")
    l.add_argument("--json", action="store_true", help="machine-readable output")
    l.set_defaults(func=cmd_list_users)

    args = p.parse_args(argv)
    if not args.command:
        p.print_help()
        return EXIT_OK
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        _err("cancelled")
        sys.exit(EXIT_ERR)
