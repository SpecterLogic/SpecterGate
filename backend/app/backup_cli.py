"""Offline backup tools. Passwords are read from the terminal, never arguments."""
import argparse
import getpass
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup").add_argument("output", type=Path)
    decrypt = commands.add_parser("decrypt-backup")
    decrypt.add_argument("input", type=Path)
    decrypt.add_argument("output", type=Path)
    args = parser.parse_args()
    password = getpass.getpass("Backup password: ")
    try:
        if args.command == "backup":
            from app.services.backups import create_backup
            if password != getpass.getpass("Confirm password: "):
                parser.error("Passwords do not match.")
            _, content = create_backup(password)
        else:
            from app.services.backup_crypto import decrypt_archive
            content = decrypt_archive(args.input.read_bytes(), password)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
    except Exception:
        parser.exit(1, "Backup operation failed. Check the password, paths and database; output files must not already exist.\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
