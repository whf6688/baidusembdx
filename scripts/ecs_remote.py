from __future__ import annotations

import argparse
import pathlib
import sys

import paramiko


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def connect(host: str, user: str, key_file: pathlib.Path) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    key = paramiko.Ed25519Key.from_private_key_file(str(key_file))
    client.connect(
        hostname=host,
        username=user,
        pkey=key,
        timeout=12,
        banner_timeout=12,
        auth_timeout=12,
    )
    return client


def run_command(client: paramiko.SSHClient, command: str) -> int:
    _, stdout, stderr = client.exec_command(command)
    for line in iter(stdout.readline, ""):
        sys.stdout.write(line)
    for line in iter(stderr.readline, ""):
        sys.stderr.write(line)
    return stdout.channel.recv_exit_status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="47.57.238.238")
    parser.add_argument("--user", default="root")
    parser.add_argument(
        "--key-file",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1]
        / "data"
        / "ssh"
        / "baidu-search-ecs-ed25519",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    command_parser = subparsers.add_parser("exec")
    command_parser.add_argument("command")
    put_parser = subparsers.add_parser("put")
    put_parser.add_argument("local", type=pathlib.Path)
    put_parser.add_argument("remote")
    args = parser.parse_args()

    with connect(args.host, args.user, args.key_file) as client:
        if args.action == "exec":
            return run_command(client, args.command)
        with client.open_sftp() as sftp:
            sftp.put(str(args.local), args.remote)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
