"""Create or update one web-login credential without storing plaintext."""

import argparse
import getpass
import secrets
import stat
import sys
from pathlib import Path

import bcrypt


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a console login user")
    parser.add_argument("username")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()

    username = args.username.strip()
    if not username or ":" in username or "\n" in username:
        raise SystemExit("Invalid username")

    if args.delete:
        existing = args.file.read_text(encoding="utf-8").splitlines() if args.file.exists() else []
        updated = [line for line in existing if line.partition(":")[0] != username]
        args.file.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
        args.file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"deleted={username}")
        return

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    elif args.generate:
        password = secrets.token_urlsafe(18)
    else:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters")

    args.file.parent.mkdir(parents=True, exist_ok=True)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    existing = args.file.read_text(encoding="utf-8").splitlines() if args.file.exists() else []
    updated = [line for line in existing if line.partition(":")[0] != username]
    updated.append(f"{username}:{password_hash}")
    args.file.write_text("\n".join(updated) + "\n", encoding="utf-8")
    args.file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    print(f"username={username}")
    if args.generate:
        print(f"password={password}")
        print("This password is shown once. Store it in a password manager.")


if __name__ == "__main__":
    main()
