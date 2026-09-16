import hashlib
import json
import random
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import unquote_plus, urlparse, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .models import Account


WORKFLOW_VERSION = "weight-loss-account-flow-v5"
BEIJING = ZoneInfo("Asia/Shanghai")
REPLACED_TRACKING_PARAMETERS = {
    "userid",
    "keywordid",
    "zhanghuid",
    "keyword",
    "kw_enc_utf8",
    "e_adposition",
}
ACCOUNT_WORKFLOW = [
    {
        "key": "account_budget",
        "label": "账户限额",
        "detail": "日预算 50 元",
        "applies_to": "all",
    },
    {
        "key": "account_regions",
        "label": "账户推广地域",
        "detail": "直接更新账户-推广地域列表；计划不设置地域",
        "applies_to": "all",
    },
    {
        "key": "campaign",
        "label": "推广计划",
        "detail": "短语/精确否定词模板 · 移动设备 · 可选上线时段 · 不设置计划地域",
        "applies_to": "except_preembedded",
    },
    {
        "key": "adgroup",
        "label": "推广单元",
        "detail": "单元出价使用系统版本化搭建规则 · 每单元最多 5,000 词",
        "applies_to": "except_preembedded",
    },
    {
        "key": "ocpc",
        "label": "oCPC 项目",
        "detail": "目标转化成本 · 使用本次填写的项目出价",
        "applies_to": "all",
    },
    {
        "key": "keywords",
        "label": "关键词",
        "detail": "短语匹配 · 仅二跳账户逐词生成 zhanghuid、UTF-8 keyword 和 e_adposition；一跳账户不传关键词 URL",
        "applies_to": "all",
    },
    {
        "key": "audience",
        "label": "人群",
        "detail": "使用系统版本化人群搭建规则",
        "applies_to": "all",
    },
    {
        "key": "creative",
        "label": "基础创意",
        "detail": "每个实际上传关键词的单元使用创意中心随机固定50组；一跳拒绝后删除补齐，二跳多次拒绝组合进黑名单",
        "applies_to": "all",
    },
]


def _text(value) -> str:
    return str(value or "").strip()


def _account_type(account: Account) -> str:
    return getattr(account.account_type, "value", account.account_type)


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_keyword_tracking_url(account: Account, keyword_utf8_encoded: str) -> str | None:
    """Build one Baidu keyword URL from the encoding persisted in the material center."""
    if _account_type(account) != "二跳账户":
        return None
    source = _text(account.landing_url_template)
    encoded_keyword = _text(keyword_utf8_encoded)
    if not source or not encoded_keyword:
        return None

    parsed = urlsplit(source)
    preserved_query_parts: list[str] = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        raw_key = part.split("=", 1)[0]
        if unquote_plus(raw_key).strip().lower() in REPLACED_TRACKING_PARAMETERS:
            continue
        preserved_query_parts.append(part)
    preserved_query_parts.append(f"zhanghuid={account.baidu_account_id}")
    preserved_query_parts.append(f"keyword={encoded_keyword}")
    preserved_query_parts.append("e_adposition={adposition}")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(preserved_query_parts), parsed.fragment))


def keyword_url_generation_policy(account: Account) -> dict | None:
    if _account_type(account) != "二跳账户":
        return None
    return {
        "scope": "per_keyword",
        "encoding": "utf-8",
        "keyword_parameter": "keyword",
        "encoded_value_source": "material_keywords.keyword_utf8_encoded",
        "account_parameter": "zhanghuid",
        "account_value_source": "target_account_id",
        "position_parameter": "e_adposition",
        "position_macro": "{adposition}",
        "removed_parameters": ["userid", "keywordid", "kw_enc_utf8"],
        "forbidden_parameter": "kw_enc_utf8",
    }


def _resolved_account_status(account: Account, account_statuses: dict[int, str] | None) -> str:
    if account_statuses is not None:
        return _text(account_statuses.get(account.baidu_account_id))
    # Compatibility for isolated callers/tests; production always passes the canonical status map.
    return _text(account.lifecycle_stage)


def account_configuration_issues(
    account: Account,
    *,
    require_empty: bool,
    require_subject: bool = False,
    account_statuses: dict[int, str] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not account.is_active:
        issues.append("账户已停用")
    if require_empty and _resolved_account_status(account, account_statuses) != "空账户":
        issues.append("账户状态不是空账户")
    if require_subject and not _text(account.account_subject):
        issues.append("缺少账号主体")
    if not _text(account.page_type):
        issues.append("缺少页面类型")
    if not _text(account.promotion_page):
        issues.append("缺少推广页面")
    if _account_type(account) != "一跳预埋户":
        landing_url = _text(account.landing_url_template)
        if not landing_url:
            issues.append("缺少推广链接")
        elif not _valid_url(landing_url):
            issues.append("推广链接不是有效的 HTTP/HTTPS 地址")
    return issues


def serialize_account(
    account: Account,
    issues: list[str] | None = None,
    account_statuses: dict[int, str] | None = None,
) -> dict:
    keyword_policy = keyword_url_generation_policy(account)
    return {
        "id": str(account.id),
        "account_id": account.baidu_account_id,
        "login_name": account.login_name,
        "account_subject": account.account_subject,
        "account_status": _resolved_account_status(account, account_statuses),
        "account_type": _account_type(account),
        "page_type": account.page_type,
        "promotion_page": account.promotion_page,
        "promotion_link": account.landing_url_template,
        "keyword_url_mode": "per_keyword_utf8_encoded" if keyword_policy else "none",
        "keyword_landing_url": None,
        "keyword_url_generation": keyword_policy,
        "permission_status": account.permission_status,
        "issues": issues or [],
    }


def account_workflow_overrides(account: Account) -> dict:
    preembedded = _account_type(account) == "一跳预埋户"
    keyword_policy = keyword_url_generation_policy(account)
    return {
        "skip_campaign_and_adgroup_creation": preembedded,
        "campaign_action": "update_existing_to_current_template" if preembedded else "create_from_current_template",
        "adgroup_action": "reuse_existing_no_create" if preembedded else "create_from_current_template",
        "campaign_template_source": "project_current_enabled_version",
        "keyword_url_mode": "per_keyword_utf8_encoded" if keyword_policy else "none",
        "keyword_landing_url": None,
        "keyword_url_generation": keyword_policy,
        "creative_targeting": {
            "scope": (
                "keyword_uploaded_existing_adgroups_only"
                if preembedded
                else "keyword_uploaded_workflow_adgroups"
            ),
            "adgroup_ids_source": "keyword_upload_result.successful_adgroup_ids",
            "requires_uploaded_keyword_count": True,
            "exclude_other_existing_adgroups": preembedded,
            "distribution": "round_robin_across_target_adgroups",
            "empty_scope_action": "block_without_creative_write",
        },
    }


def keyword_uploaded_adgroup_ids(keyword_upload_results: list[dict]) -> list[int]:
    """Return only units that received at least one keyword in this workflow.

    The ad-build executor must use this result as the creative target scope for
    pre-embedded accounts. Existing units not present here are never creative
    targets merely because they already exist in the account.
    """
    selected: set[int] = set()
    for row in keyword_upload_results:
        uploaded_count = int(row.get("uploaded_keyword_count") or 0)
        if uploaded_count <= 0:
            continue
        adgroup_id = row.get("adgroup_id")
        if adgroup_id is None or int(adgroup_id) <= 0:
            raise ValueError("关键词上传成功记录缺少有效的 adgroup_id")
        selected.add(int(adgroup_id))
    return sorted(selected)


def account_workflow_steps(account: Account) -> list[dict]:
    if _account_type(account) == "一跳预埋户":
        steps = []
        for step in ACCOUNT_WORKFLOW:
            if step["key"] == "adgroup":
                continue
            if step["key"] == "campaign":
                steps.append({
                    **step,
                    "label": "更新已有计划",
                    "detail": "更新短语否定词、精确否定词、移动设备及可选时段；不新建计划，不设置计划地域",
                    "applies_to": "preembedded_only",
                })
            else:
                if step["key"] == "creative":
                    steps.append({
                        **step,
                        "detail": "仅向本次实际上传成功关键词的已有单元新建创意；账户内其他已有单元全部跳过",
                        "applies_to": "preembedded_keyword_uploaded_adgroups_only",
                    })
                else:
                    steps.append(step)
        return steps
    return ACCOUNT_WORKFLOW


def build_plan_pause_schedule_from_windows(enabled: bool, windows: list[dict]) -> list[dict]:
    """Convert arbitrary user-facing online windows to Baidu's inverse pause windows."""
    if not enabled:
        return []
    online_hours_by_day = {weekday: set() for weekday in range(1, 8)}
    for window in windows:
        weekday = int(window["weekDay"])
        start_hour = int(window["startHour"])
        end_hour = int(window["endHour"])
        if weekday < 1 or weekday > 7 or start_hour < 0 or end_hour > 24 or start_hour >= end_hour:
            raise ValueError("启用时段参数无效")
        online_hours_by_day[weekday].update(range(start_hour, end_hour))
    result: list[dict] = []
    for weekday in range(1, 8):
        pause_start: int | None = None
        for hour in range(24):
            is_paused = hour not in online_hours_by_day[weekday]
            if is_paused and pause_start is None:
                pause_start = hour
            elif not is_paused and pause_start is not None:
                result.append({"weekDay": weekday, "startHour": pause_start, "endHour": hour})
                pause_start = None
        if pause_start is not None:
            result.append({"weekDay": weekday, "startHour": pause_start, "endHour": 24})
    return result


def build_plan_pause_schedule(enabled: bool, weekdays: list[int], start_hour: int, end_hour: int) -> list[dict]:
    """Convert the legacy shared daily online window to Baidu pause windows."""
    if not enabled:
        return []
    if start_hour == end_hour:
        raise ValueError("上线开始和结束时间不能相同")
    windows: list[dict] = []
    for weekday in set(weekdays):
        if start_hour < end_hour:
            windows.append({"weekDay": weekday, "startHour": start_hour, "endHour": end_hour})
        else:
            windows.append({"weekDay": weekday, "startHour": start_hour, "endHour": 24})
            windows.append({"weekDay": weekday % 7 + 1, "startHour": 0, "endHour": end_hour})
    return build_plan_pause_schedule_from_windows(True, windows)


def _available_subjects(
    accounts: list[Account],
    account_statuses: dict[int, str] | None = None,
) -> list[dict]:
    grouped: dict[str, list[Account]] = defaultdict(list)
    for account in accounts:
        if account.is_active and _resolved_account_status(account, account_statuses) == "空账户" and _text(account.account_subject):
            grouped[_text(account.account_subject)].append(account)
    result = []
    for subject, rows in sorted(grouped.items()):
        ready = sum(
            not account_configuration_issues(
                row,
                require_empty=True,
                require_subject=True,
                account_statuses=account_statuses,
            )
            for row in rows
        )
        result.append({"name": subject, "empty_count": len(rows), "ready_count": ready, "blocked_count": len(rows) - ready})
    return result


def _round_robin_by_subject(pool: list[Account], quantity: int) -> tuple[list[Account], dict[str, int]]:
    grouped: dict[str, list[Account]] = defaultdict(list)
    for account in pool:
        grouped[_text(account.account_subject)].append(account)
    for rows in grouped.values():
        rows.sort(key=lambda row: row.baidu_account_id)
    subjects = sorted(grouped)
    selected: list[Account] = []
    subject_counts: dict[str, int] = defaultdict(int)
    while len(selected) < quantity:
        progressed = False
        for subject in subjects:
            if grouped[subject] and len(selected) < quantity:
                selected.append(grouped[subject].pop(0))
                subject_counts[subject] += 1
                progressed = True
        if not progressed:
            break
    return selected, dict(subject_counts)


def _serialize_online_schedule(payload) -> list[dict] | None:
    windows = getattr(payload, "online_schedule", None)
    if windows is None:
        return None
    return [
        window.model_dump() if hasattr(window, "model_dump") else dict(window)
        for window in windows
    ]


def _selection_fingerprint(payload, selected: list[Account], creative_pool_fingerprint: str = "") -> str:
    online_schedule = _serialize_online_schedule(payload)
    canonical = {
        "project_id": str(payload.project_id),
        "keyword_mode": payload.keyword_mode,
        "selection_mode": payload.selection_mode,
        "account_selectors": payload.account_selectors,
        "manager_login_names": payload.manager_login_names,
        "subject_names": payload.subject_names,
        "quantity": payload.quantity,
        "selection_seed": payload.selection_seed,
        "selected_account_ids": [row.baidu_account_id for row in selected],
        "project_bid": str(payload.project_bid),
        "online_schedule_enabled": payload.online_schedule_enabled,
        "online_schedule": online_schedule,
        "online_weekdays": payload.online_weekdays,
        "online_start_hour": payload.online_start_hour,
        "online_end_hour": payload.online_end_hour,
        "region_target": payload.region_target,
        "geo_location_status": payload.geo_location_status,
        "creative_pool_fingerprint": creative_pool_fingerprint,
        "workflow_version": WORKFLOW_VERSION,
    }
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_ad_build_preview(
    accounts: list[Account],
    payload,
    *,
    material_keyword_count: int,
    writes_enabled: bool,
    creative_summary: dict | None = None,
    material_summary: dict | None = None,
    account_statuses: dict[int, str] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    errors: list[str] = []
    warnings: list[str] = []
    selected: list[Account] = []
    allocation: dict[str, int] = {}
    require_empty = True

    if payload.selection_mode == "specified_accounts":
        by_id = {str(row.baidu_account_id): [row] for row in accounts}
        by_login: dict[str, list[Account]] = defaultdict(list)
        for row in accounts:
            by_login[row.login_name].append(row)
        seen_ids: set[int] = set()
        for selector in payload.account_selectors:
            matches = by_id.get(selector, []) if selector.isdigit() else by_login.get(selector, [])
            if not matches:
                errors.append(f"未精确匹配到账户：{selector}")
                continue
            if len(matches) > 1:
                errors.append(f"账户名称存在重复，请改用百度账户 ID：{selector}")
                continue
            if matches[0].baidu_account_id not in seen_ids:
                selected.append(matches[0])
                seen_ids.add(matches[0].baidu_account_id)

    elif payload.selection_mode == "specified_managers":
        manager_set = set(payload.manager_login_names)
        existing_managers = {row.manager_login_name for row in accounts}
        for manager_login_name in payload.manager_login_names:
            if manager_login_name not in existing_managers:
                errors.append(f"未找到账户管家：{manager_login_name}")
        manager_pool = [
            row for row in accounts
            if row.is_active
            and _resolved_account_status(row, account_statuses) == "空账户"
            and row.manager_login_name in manager_set
        ]
        grouped_managers: dict[str, list[Account]] = defaultdict(list)
        for row in manager_pool:
            grouped_managers[row.manager_login_name].append(row)
        selected = []
        allocation = {}
        for manager_login_name in dict.fromkeys(payload.manager_login_names):
            manager_accounts = sorted(
                grouped_managers[manager_login_name],
                key=lambda row: row.baidu_account_id,
            )
            requested_quantity = (
                payload.quantity
                if payload.quantity is not None
                else len(manager_accounts)
            )
            manager_selected = manager_accounts[:requested_quantity]
            selected.extend(manager_selected)
            if manager_selected:
                allocation[manager_login_name] = len(manager_selected)
            if len(manager_selected) < requested_quantity:
                errors.append(
                    f"管家 {manager_login_name} 名下空账户只有 {len(manager_selected)} 个，"
                    f"少于每个管家搭建数量 {requested_quantity}"
                )
        if not selected:
            errors.append("所选管家名下没有账户状态为“空账户”的账户")

    elif payload.selection_mode == "multi_subjects":
        ready_pool = [
            row for row in accounts
            if not account_configuration_issues(
                row,
                require_empty=True,
                require_subject=True,
                account_statuses=account_statuses,
            )
        ]
        selected, allocation = _round_robin_by_subject(ready_pool, payload.quantity or 0)
        if len(selected) < (payload.quantity or 0):
            errors.append(f"符合条件的空账户只有 {len(selected)} 个，少于指定数量 {payload.quantity}")
        if not allocation:
            errors.append("没有同时具备账号主体和页面配置的空账户")

    elif payload.selection_mode == "specified_subjects":
        subject_set = set(payload.subject_names)
        existing_subjects = {_text(row.account_subject) for row in accounts if _text(row.account_subject)}
        for subject in payload.subject_names:
            if subject not in existing_subjects:
                errors.append(f"未找到账号主体：{subject}")
        selected = sorted(
            [
                row for row in accounts
                if row.is_active
                and _resolved_account_status(row, account_statuses) == "空账户"
                and _text(row.account_subject) in subject_set
            ],
            key=lambda row: (_text(row.account_subject), row.baidu_account_id),
        )
        allocation = dict(defaultdict(int))
        for row in selected:
            allocation[_text(row.account_subject)] = allocation.get(_text(row.account_subject), 0) + 1
        if not selected:
            errors.append("所选主体下没有账户状态为“空账户”的账户")

    else:
        ready_pool = [
            row for row in accounts
            if not account_configuration_issues(
                row,
                require_empty=True,
                account_statuses=account_statuses,
            )
        ]
        seed = int(hashlib.sha256(f"{payload.project_id}:{payload.selection_seed}".encode()).hexdigest(), 16)
        random.Random(seed).shuffle(ready_pool)
        requested_quantity = payload.quantity if payload.quantity is not None else len(ready_pool)
        selected = ready_pool[:requested_quantity]
        if len(selected) < requested_quantity:
            errors.append(f"符合条件的空账户只有 {len(selected)} 个，少于指定数量 {requested_quantity}")

    blocked_accounts: list[dict] = []
    ready_accounts: list[dict] = []
    for account in selected:
        issues = account_configuration_issues(
            account,
            require_empty=require_empty,
            require_subject=payload.selection_mode in {"multi_subjects", "specified_subjects"},
            account_statuses=account_statuses,
        )
        serialized = serialize_account(account, issues, account_statuses)
        if issues:
            blocked_accounts.append(serialized)
        else:
            ready_accounts.append(serialized)
        if account.permission_status != "granted":
            warnings.append(f"账户 {account.login_name} 的百度操作权限尚未确认")

    if blocked_accounts:
        errors.append(f"有 {len(blocked_accounts)} 个账户缺少页面类型、推广页面或推广链接等必需配置")
    if material_keyword_count <= 0:
        errors.append("项目公共物料库暂无可用关键词，请先在物料中心导入")
    creative_summary = creative_summary or {
        "segment_counts": {"title": 1, "description1": 1, "description2": 0},
        "available_combination_count": 50,
        "blacklisted_combination_count": 0,
        "fingerprint": "",
    }
    material_summary = material_summary or {
        "fingerprint": hashlib.sha256(b"[]").hexdigest(),
        "campaign_count": 0,
        "campaigns": [],
    }
    if creative_summary["segment_counts"].get("title", 0) <= 0:
        errors.append("创意中心暂无可用创意标题")
    if creative_summary["segment_counts"].get("description1", 0) <= 0:
        errors.append("创意中心暂无可用创意描述1")
    if creative_summary.get("available_combination_count", 0) < 50:
        errors.append("创意中心可用组合不足50组，请补充标题或创意描述1")
    if not selected:
        errors.append("没有可加入新建队列的账户")
    if not writes_enabled:
        warnings.append("百度写入当前关闭；可以保存任务队列，但不会调用百度")

    scheduled_dates: list[date] = list(getattr(payload, "scheduled_dates", []) or [])
    scheduled_times: list[time] = list(getattr(payload, "scheduled_times", []) or [])
    schedule_unlimited = bool(getattr(payload, "schedule_unlimited", False))
    required_batch_count = 1
    schedule_slots: list[datetime] = []
    available_schedule_slot_count: int | None = None

    if payload.execution_mode == "scheduled":
        batch_size = payload.batch_size
        required_batch_count = (len(selected) + batch_size - 1) // batch_size if selected else 0
        if scheduled_dates and scheduled_times:
            interval = 0
            if schedule_unlimited:
                cursor = scheduled_dates[0]
                maximum_days = max(1, required_batch_count + 1)
                for _ in range(maximum_days):
                    for scheduled_time in scheduled_times:
                        candidate = datetime.combine(cursor, scheduled_time, tzinfo=BEIJING).astimezone(UTC)
                        if candidate > now:
                            schedule_slots.append(candidate)
                            if len(schedule_slots) >= required_batch_count:
                                break
                    if len(schedule_slots) >= required_batch_count:
                        break
                    cursor += timedelta(days=1)
                available_schedule_slot_count = None
            else:
                all_slots = [
                    datetime.combine(scheduled_date, scheduled_time, tzinfo=BEIJING).astimezone(UTC)
                    for scheduled_date in scheduled_dates
                    for scheduled_time in scheduled_times
                ]
                schedule_slots = sorted(slot for slot in all_slots if slot > now)
                expired_slot_count = len(all_slots) - len(schedule_slots)
                if expired_slot_count:
                    if schedule_slots:
                        next_slot = schedule_slots[0].astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
                        warnings.append(
                            f"已自动作废 {expired_slot_count} 个早于当前时间的执行节点，将从 {next_slot} 开始执行"
                        )
                    else:
                        warnings.append(f"已自动作废 {expired_slot_count} 个早于当前时间的执行节点")
                available_schedule_slot_count = len(schedule_slots)
                if len(schedule_slots) < required_batch_count:
                    errors.append(
                        f"当前只有 {len(schedule_slots)} 个执行节点，但账户队列需要 {required_batch_count} 批；请增加日期或时间，或选择不限日期"
                    )
            first_scheduled_at = schedule_slots[0] if schedule_slots else now
        else:
            first_scheduled_at = payload.scheduled_at.astimezone(UTC)
            if first_scheduled_at <= now:
                errors.append("首次执行时间必须晚于当前时间")
            interval = payload.batch_interval_minutes
    else:
        first_scheduled_at = now
        batch_size = max(1, len(selected))
        interval = 0

    batches = []
    for offset in range(0, len(selected), batch_size):
        batch_accounts = selected[offset: offset + batch_size]
        batch_number = len(batches) + 1
        if payload.execution_mode == "scheduled" and schedule_slots:
            if batch_number > len(schedule_slots):
                break
            scheduled_at = schedule_slots[batch_number - 1]
        else:
            scheduled_at = first_scheduled_at + timedelta(minutes=interval * (batch_number - 1))
        batches.append({
            "number": batch_number,
            "scheduled_at": scheduled_at,
            "account_count": len(batch_accounts),
            "account_ids": [row.baidu_account_id for row in batch_accounts],
            "account_names": [row.login_name for row in batch_accounts],
        })

    permission_warning_count = sum(row.permission_status != "granted" for row in selected)
    unique_warnings = list(dict.fromkeys(warnings))
    unique_errors = list(dict.fromkeys(errors))
    online_schedule = _serialize_online_schedule(payload)
    return {
        "keyword_mode": payload.keyword_mode,
        "selection_mode": payload.selection_mode,
        "execution_mode": payload.execution_mode,
        "selection_fingerprint": _selection_fingerprint(payload, selected, creative_summary.get("fingerprint", "")),
        "selected_account_ids": [row.baidu_account_id for row in selected],
        "selected_count": len(selected),
        "ready_count": len(ready_accounts),
        "blocked_count": len(blocked_accounts),
        "permission_warning_count": permission_warning_count,
        "can_submit": bool(selected) and not unique_errors,
        "errors": unique_errors,
        "warnings": unique_warnings,
        "accounts": [
            serialize_account(
                row,
                account_configuration_issues(
                    row,
                    require_empty=require_empty,
                    require_subject=payload.selection_mode in {"multi_subjects", "specified_subjects"},
                    account_statuses=account_statuses,
                ),
                account_statuses,
            )
            for row in selected
        ],
        "blocked_accounts": blocked_accounts,
        "available_subjects": _available_subjects(accounts, account_statuses),
        "subject_allocation": allocation,
        "material_keyword_count": material_keyword_count,
        "material_fingerprint": material_summary["fingerprint"],
        "material_plan": {
            "mode": payload.keyword_mode,
            "campaign_count": material_summary["campaign_count"],
            "campaigns": material_summary["campaigns"],
            "per_account_keyword_count": material_keyword_count,
            "description": (
                "全部非黑名单关键词按原物料计划投放，每个账户每个关键词仅投放一次"
                if payload.keyword_mode == "full"
                else "按 A–F 分级规则优选投放，A 最大化利用，B/C 测试，D/E/F 补充"
            ),
        },
        "creative_count_per_account": 50,
        "creative_available_combination_count": creative_summary.get("available_combination_count", 0),
        "creative_blacklisted_combination_count": creative_summary.get("blacklisted_combination_count", 0),
        "creative_segment_counts": creative_summary.get("segment_counts", {}),
        "creative_pool_fingerprint": creative_summary.get("fingerprint", ""),
        "build_settings": {
            "project_bid": str(payload.project_bid),
            "online_schedule_enabled": payload.online_schedule_enabled,
            "online_schedule": online_schedule,
            "online_weekdays": payload.online_weekdays,
            "online_start_hour": payload.online_start_hour,
            "online_end_hour": payload.online_end_hour,
            "plan_pause_schedule": (
                build_plan_pause_schedule_from_windows(
                    payload.online_schedule_enabled,
                    online_schedule,
                )
                if online_schedule is not None
                else build_plan_pause_schedule(
                    payload.online_schedule_enabled,
                    payload.online_weekdays,
                    payload.online_start_hour,
                    payload.online_end_hour,
                )
            ),
            "campaign_region_mode": "unset",
            "account_region_update": "account_promotion_region_list",
            "region_target": payload.region_target,
            "region_count": len(payload.region_target),
            "geo_location_status": payload.geo_location_status,
        },
        "batch_size": batch_size,
        "batch_interval_minutes": interval,
        "batch_count": len(batches),
        "required_batch_count": required_batch_count,
        "scheduled_dates": [value.isoformat() for value in scheduled_dates],
        "scheduled_times": [value.strftime("%H:%M") for value in scheduled_times],
        "schedule_unlimited": schedule_unlimited,
        "available_schedule_slot_count": available_schedule_slot_count,
        "unused_schedule_slot_count": (
            max(0, available_schedule_slot_count - required_batch_count)
            if available_schedule_slot_count is not None else None
        ),
        "first_scheduled_at": first_scheduled_at,
        "estimated_completed_at": batches[-1]["scheduled_at"] if batches else first_scheduled_at,
        "batches": batches,
        "workflow_version": WORKFLOW_VERSION,
        "workflow": ACCOUNT_WORKFLOW,
    }
