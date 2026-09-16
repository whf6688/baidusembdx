import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectPreference


AD_BUILD_PLAN_REPEATS_KEY = "ad_build_plan_repeats"
AD_BUILD_PLAN_REPEATS_DRAFT_KEY = "ad_build_plan_repeats_draft"


def default_plan_repeat_count(campaign_name: str) -> int:
    return 5 if campaign_name.strip().upper().startswith("A") else 1


def load_plan_repeat_counts_for_key(
    db: Session,
    project_id: uuid.UUID,
    key: str,
) -> dict[str, int]:
    row = db.scalar(select(ProjectPreference).where(
        ProjectPreference.project_id == project_id,
        ProjectPreference.key == key,
    ))
    raw = row.value if row and isinstance(row.value, dict) else {}
    plans = raw.get("plans") if isinstance(raw, dict) else None
    if not isinstance(plans, list):
        return {}
    result: dict[str, int] = {}
    for item in plans:
        if not isinstance(item, dict):
            continue
        name = str(item.get("campaign_name") or "").strip()
        try:
            repeat_count = int(item.get("repeat_count"))
        except (TypeError, ValueError):
            continue
        if name and 1 <= repeat_count <= 20:
            result[name] = repeat_count
    return result


def load_plan_repeat_counts(db: Session, project_id: uuid.UUID) -> dict[str, int]:
    """Return only the published configuration used by real build jobs."""
    return load_plan_repeat_counts_for_key(db, project_id, AD_BUILD_PLAN_REPEATS_KEY)


def repeat_count_for_plan(
    configured: dict[str, int],
    campaign_name: str,
) -> int:
    return configured.get(campaign_name, default_plan_repeat_count(campaign_name))
