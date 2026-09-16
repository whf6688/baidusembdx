import hashlib
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo


PAGE_SIZE = 100
API_FRAGMENTS = {
    "visitors": "browserec/escurrentBrowseRecord",
    "copy_visitors": "copystat/queryCopyCurrentPage",
    "conversions": "qwhkzs/queryHkzsConversionList",
}


def _record_key(record: dict) -> str:
    for field in ("id", "_id"):
        value = record.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deduplicate_records(records: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for record in records:
        unique[_record_key(record)] = record
    return list(unique.values())


def _selected_query_bounds(
    captured_at: datetime,
    date_from: date,
    date_to: date,
) -> tuple[str, str]:
    local_capture = captured_at.astimezone(ZoneInfo("Asia/Shanghai"))
    start_time = f"{date_from.isoformat()} 00:00:00"
    end_time = (
        local_capture.strftime("%Y-%m-%d %H:%M:%S")
        if date_to == local_capture.date()
        else f"{date_to.isoformat()} 23:59:59"
    )
    return start_time, end_time


def _fetch_complete_dataset(
    context,
    initial_response,
    captured_at: datetime,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    request = initial_response.request
    payload = dict(parse_qsl(request.post_data or "", keep_blank_values=True))
    payload["page"] = "1"
    payload["count"] = str(PAGE_SIZE)
    if date_from is not None and date_to is not None:
        payload["start_time"], payload["end_time"] = _selected_query_bounds(
            captured_at, date_from, date_to
        )
    elif "end_time" in payload:
        payload["end_time"] = captured_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    replay_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in {"access-token", "referer"}
    }

    def fetch_page(page_number: int) -> dict:
        response = context.request.post(
            request.url,
            headers=replay_headers,
            form={**payload, "page": str(page_number)},
            timeout=30_000,
        )
        if not response.ok:
            raise RuntimeError(f"tracking_api_http_{response.status}")
        body = response.json()
        if not body.get("success"):
            raise RuntimeError("tracking_api_rejected")
        return body

    first_body = fetch_page(1)
    first_data = first_body.get("data") or {}
    expected_count = int(first_data.get("countAll") or 0)
    records = list(first_data.get("list") or [])
    for page_number in range(2, math.ceil(expected_count / PAGE_SIZE) + 1):
        page_body = fetch_page(page_number)
        records.extend((page_body.get("data") or {}).get("list") or [])

    unique_records = _deduplicate_records(records)
    return {
        "source_url": request.url,
        "captured_at": captured_at.isoformat(),
        "date_from": payload.get("start_time"),
        "date_to": payload.get("end_time"),
        "expected_count": expected_count,
        "record_count": len(unique_records),
        "complete": len(unique_records) == expected_count,
        "records": unique_records,
    }


def capture_tracking_pages(
    settings,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
) -> dict:
    if not settings.hduofen_username or not settings.hduofen_password:
        return {"status": "blocked", "reason": "missing_credentials"}
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    scope = project_id or "shared"
    capture_dir = (
        Path(settings.storage_root)
        / "hduofen"
        / scope
        / datetime.now(UTC).strftime("%Y/%m/%d/%H%M%S")
    )
    capture_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "visitors": "https://i.hduofen.cn/page/stat/nowaccess.html",
        "copy_visitors": "https://i.hduofen.cn/page/copy/copynow.html",
        "conversions": "https://i.hduofen.cn/page/qywxhkzs/hkzsConversion.html",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = context.new_page()
        page.goto("https://i.hduofen.cn/login/", wait_until="domcontentloaded", timeout=30_000)
        captcha_fields = page.locator("#veri-code, #verify_code")
        if any(captcha_fields.nth(index).is_visible() for index in range(captcha_fields.count())):
            browser.close()
            return {"status": "blocked", "reason": "captcha_detected"}
        page.locator("#num").fill(settings.hduofen_username)
        page.locator("#pass").fill(settings.hduofen_password)
        page.locator("button.log-btn").click()
        try:
            page.wait_for_url(lambda url: "/login" not in url, timeout=15_000)
        except PlaywrightTimeoutError:
            browser.close()
            return {"status": "blocked", "reason": "login_failed"}
        captures = []
        for name, url in targets.items():
            fragment = API_FRAGMENTS[name]
            with page.expect_response(
                lambda response: fragment in response.url,
                timeout=30_000,
            ) as response_info:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            captured_at = datetime.now(UTC)
            dataset = _fetch_complete_dataset(
                context,
                response_info.value,
                captured_at,
                date_from=date_from,
                date_to=date_to,
            )
            html = page.content()
            fingerprint = hashlib.sha256(html.encode("utf-8")).hexdigest()
            html_path = capture_dir / f"{name}.html"
            data_path = capture_dir / f"{name}.json"
            html_path.write_text(html, encoding="utf-8")
            data_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            captures.append(
                {
                    "name": name,
                    "path": str(html_path),
                    "data_path": str(data_path),
                    "fingerprint": fingerprint,
                    "expected_count": dataset["expected_count"],
                    "record_count": dataset["record_count"],
                    "complete": dataset["complete"],
                }
            )
        browser.close()
    status = "captured" if all(item["complete"] for item in captures) else "partial"
    return {"status": status, "captures": captures, "committed_to_facts": False}
