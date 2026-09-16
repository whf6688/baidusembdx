from __future__ import annotations

import argparse
import base64
import csv
import io
import pathlib
import subprocess

from ecs_remote import connect


ROOT = pathlib.Path(__file__).resolve().parents[1]


def local_psql(sql: str) -> str:
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "postgres", "psql",
            "-v", "ON_ERROR_STOP=1", "-U", "search_app", "-d", "baidu_platform",
            "-At", "-F", "|",
        ],
        cwd=ROOT,
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"本地数据库操作失败：{result.stderr.strip() or result.returncode}")
    return result.stdout


def sql_literal(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def remote_rows(manager_name: str, host: str, key_file: pathlib.Path) -> dict[int, tuple[str | None, str | None]]:
    manager_literal = manager_name.replace("'", "''")
    sql = f"""
COPY (
    SELECT account.baidu_account_id, account.rebate_rate::text, account.recharge_account
    FROM search_marketing.accounts AS account
    JOIN search_marketing.account_managers AS manager ON manager.id = account.manager_id
    WHERE manager.login_name = '{manager_literal}'
    ORDER BY account.baidu_account_id
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)
"""
    encoded = base64.b64encode(sql.encode("utf-8")).decode("ascii")
    command = (
        f"echo {encoded} | base64 -d | "
        "docker exec -i baidu-search-prod-postgres-1 "
        "psql -U search_app -d baidu_platform"
    )
    with connect(host, "root", key_file) as client:
        _, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode("utf-8")
        error = stderr.read().decode("utf-8", errors="replace").strip()
        status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError(f"线上只读导出失败：{error or status}")
    result: dict[int, tuple[str | None, str | None]] = {}
    for row in csv.DictReader(io.StringIO(output)):
        result[int(row["baidu_account_id"])] = (
            row["rebate_rate"] or None,
            row["recharge_account"] or None,
        )
    return result


def restore(
    manager_name: str,
    source: dict[int, tuple[str | None, str | None]],
    apply: bool,
) -> tuple[int, int, int]:
    manager_literal = sql_literal(manager_name)
    manager_output = local_psql(
        "SELECT id,auth_status,is_active FROM search_marketing.account_managers "
        f"WHERE login_name={manager_literal};"
    ).strip()
    if not manager_output:
        raise RuntimeError("本地不存在指定账户管家")
    manager_id, auth_status, is_active = manager_output.split("|")
    if auth_status != "archived" or is_active != "f":
        raise RuntimeError("安全检查失败：只允许恢复已归档且停用的历史管家")
    local_ids = {
        int(value)
        for value in local_psql(
            "SELECT baidu_account_id FROM search_marketing.accounts "
            f"WHERE manager_id='{manager_id}'::uuid;"
        ).splitlines()
        if value.strip()
    }
    missing = local_ids.difference(source)
    if missing:
        raise RuntimeError(f"线上缺少 {len(missing)} 个本地账户，已取消整批恢复")
    current: dict[int, tuple[str | None, str | None]] = {}
    current_output = local_psql(
        "SELECT baidu_account_id,rebate_rate::text,"
        "coalesce(encode(convert_to(recharge_account,'UTF8'),'base64'),'') "
        "FROM search_marketing.accounts "
        f"WHERE manager_id='{manager_id}'::uuid ORDER BY baidu_account_id;"
    )
    for line in current_output.splitlines():
        account_id, rebate_rate, recharge_encoded = line.split("|", 2)
        current[int(account_id)] = (
            rebate_rate or None,
            base64.b64decode(recharge_encoded).decode("utf-8") if recharge_encoded else None,
        )
    pending = sum(current.get(account_id) != source[account_id] for account_id in local_ids)
    if not apply:
        return len(local_ids), pending, 0
    values = ",\n".join(
        f"({account_id}, {sql_literal(source[account_id][0])}::numeric, "
        f"{sql_literal(source[account_id][1])}::varchar)"
        for account_id in sorted(local_ids)
    )
    local_psql(
        f"""
BEGIN;
CREATE TEMP TABLE restore_manager_financials (
    baidu_account_id bigint PRIMARY KEY,
    rebate_rate numeric(7,2),
    recharge_account varchar(200)
) ON COMMIT DROP;
INSERT INTO restore_manager_financials VALUES
{values};
UPDATE search_marketing.accounts AS account
SET rebate_rate = source.rebate_rate,
    recharge_account = source.recharge_account
FROM restore_manager_financials AS source
WHERE account.manager_id = '{manager_id}'::uuid
  AND account.baidu_account_id = source.baidu_account_id;
UPDATE search_marketing.account_managers
SET financial_settings_mode = 'legacy_per_account',
    rebate_rate = NULL,
    recharge_account = NULL
WHERE id = '{manager_id}'::uuid;
COMMIT;
"""
    )
    return len(local_ids), pending, len(local_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="从线上只读历史库恢复旧管家的逐账户返点与充值账户")
    parser.add_argument("--manager", default="BDCC-发丹嘉w")
    parser.add_argument("--host", default="47.57.238.238")
    parser.add_argument(
        "--key-file",
        type=pathlib.Path,
        default=ROOT / "data" / "ssh" / "baidu-search-ecs-ed25519",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = remote_rows(args.manager, args.host, args.key_file)
    checked, pending, updated = restore(args.manager, source, args.apply)
    print(
        f"线上源数据 {len(source)} 条；本地精确匹配 {checked} 条；"
        f"待恢复 {pending} 条；实际恢复 {updated} 条"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
