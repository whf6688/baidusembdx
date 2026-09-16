from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import posixpath
import shlex
import sys
import uuid

from ecs_remote import connect, run_command


HDUOFEN_KEYS = (
    "HDUOFEN_USERNAME",
    "HDUOFEN_PASSWORD",
    "HDUOFEN_SESSION_ENCRYPTION_KEY",
    "HDUOFEN_CAPTURE_ENABLED",
)


def read_env_values(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    missing = [key for key in HDUOFEN_KEYS if not values.get(key)]
    if missing:
        raise RuntimeError(f"Local environment is missing: {', '.join(missing)}")
    if values["HDUOFEN_CAPTURE_ENABLED"].lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("Local HDUOFEN_CAPTURE_ENABLED is not enabled")
    return {key: values[key] for key in HDUOFEN_KEYS}


def replace_env_values(content: str, replacements: dict[str, str]) -> str:
    output: list[str] = []
    replaced: set[str] = set()
    for raw_line in content.splitlines():
        stripped = raw_line.lstrip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in replacements:
                output.append(f"{key}={replacements[key]}")
                replaced.add(key)
                continue
        output.append(raw_line)
    for key in HDUOFEN_KEYS:
        if key not in replaced:
            output.append(f"{key}={replacements[key]}")
    return "\n".join(output).rstrip() + "\n"


def write_remote_file(sftp, path: str, content: str, mode: int = 0o600) -> None:
    with sftp.open(path, "w") as remote_file:
        remote_file.write(content)
        remote_file.flush()
    sftp.chmod(path, mode)


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="47.57.238.238")
    parser.add_argument("--user", default="root")
    parser.add_argument("--local-env", type=pathlib.Path, default=root / ".env")
    parser.add_argument(
        "--key-file",
        type=pathlib.Path,
        default=root / "data" / "ssh" / "baidu-search-ecs-ed25519",
    )
    args = parser.parse_args()

    replacements = read_env_values(args.local_env)
    with connect(args.host, args.user, args.key_file) as client:
        with client.open_sftp() as sftp:
            current = sftp.normalize("/www/baidu-search/current")
            env_path = posixpath.join(current, "deploy", ".env.production")
            with sftp.open(env_path, "r") as remote_file:
                original = remote_file.read().decode("utf-8")
            updated = replace_env_values(original, replacements)
            timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
            backup_path = f"{env_path}.backup-hduofen-{timestamp}"
            temporary_path = f"{env_path}.tmp-hduofen-{uuid.uuid4().hex}"
            write_remote_file(sftp, backup_path, original)
            write_remote_file(sftp, temporary_path, updated)
            sftp.posix_rename(temporary_path, env_path)

        compose = (
            "docker compose --env-file deploy/.env.production "
            "-f deploy/docker-compose.production.yml"
        )
        current_q = shlex.quote(current)
        restart_command = (
            f"cd {current_q} && "
            f"{compose} up -d --no-deps --force-recreate api worker scheduler web && "
            "for n in $(seq 1 30); do "
            "if curl -fsS http://127.0.0.1:18080/api/v1/health >/dev/null; "
            "then echo online_health=ok; exit 0; fi; sleep 2; done; "
            "echo online_health=failed; exit 1"
        )
        exit_code = run_command(client, restart_command)
        if exit_code != 0:
            with client.open_sftp() as sftp:
                write_remote_file(sftp, env_path, original)
            run_command(
                client,
                f"cd {current_q} && {compose} up -d --no-deps --force-recreate api worker scheduler web",
            )
            raise RuntimeError("Online restart failed; production environment was restored")

        verify_command = (
            f"cd {current_q} && "
            f"{compose} exec -T api printenv HDUOFEN_CAPTURE_ENABLED && "
            f"{compose} exec -T api sh -lc '"
            "test -n \"$HDUOFEN_USERNAME\" && "
            "test -n \"$HDUOFEN_PASSWORD\" && "
            "test -n \"$HDUOFEN_SESSION_ENCRYPTION_KEY\" && "
            "echo hduofen_credentials=configured'"
        )
        exit_code = run_command(client, verify_command)
        if exit_code != 0:
            raise RuntimeError("Online Hduofen environment verification failed")
        print(f"backup={backup_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
