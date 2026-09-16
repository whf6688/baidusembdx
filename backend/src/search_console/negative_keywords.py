import hashlib
import json
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import ProjectNegativeKeyword, ReferenceTemplateVersion


def clean_negative_keyword(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalized_negative_keyword(value: object) -> str:
    return clean_negative_keyword(value).casefold()


def reference_template_negative_keywords(template_data: dict | None) -> dict[str, list[str]]:
    campaign = (template_data or {}).get("campaign") or {}
    result: dict[str, list[str]] = {"phrase": [], "exact": []}
    for match_type, source_key in (("phrase", "negative_words"), ("exact", "exact_negative_words")):
        seen: set[str] = set()
        for value in campaign.get(source_key) or []:
            keyword = clean_negative_keyword(value)
            normalized = keyword.casefold()
            if not keyword or normalized in seen:
                continue
            seen.add(normalized)
            result[match_type].append(keyword)
    return result


def reference_template_negative_keyword_fingerprint(
    reference_template: ReferenceTemplateVersion,
) -> str:
    candidates = reference_template_negative_keywords(reference_template.template_data)
    payload = {
        "template_id": str(reference_template.id),
        "template_version": reference_template.version,
        "negative_keywords": candidates,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def project_negative_keyword_snapshot(db: Session, project_id: uuid.UUID) -> dict[str, list[str]]:
    rows = db.scalars(
        select(ProjectNegativeKeyword)
        .where(ProjectNegativeKeyword.project_id == project_id)
        .order_by(ProjectNegativeKeyword.match_type, ProjectNegativeKeyword.created_at, ProjectNegativeKeyword.id)
    ).all()
    result: dict[str, list[str]] = {"phrase": [], "exact": []}
    for row in rows:
        if row.match_type in result:
            result[row.match_type].append(row.keyword_text)
    return result


def sync_reference_template_negative_keywords(
    db: Session,
    project_id: uuid.UUID,
    reference_template: ReferenceTemplateVersion,
    created_by: str,
) -> dict:
    candidates = reference_template_negative_keywords(reference_template.template_data)
    created = {"phrase": 0, "exact": 0}
    for match_type, keywords in candidates.items():
        if not keywords:
            continue
        rows = [
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "match_type": match_type,
                "keyword_text": keyword,
                "normalized_keyword_text": normalized_negative_keyword(keyword),
                "source": "reference_template",
                "reference_template_version_id": reference_template.id,
                "created_by": created_by,
            }
            for keyword in keywords
        ]
        statement = (
            pg_insert(ProjectNegativeKeyword)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["project_id", "match_type", "normalized_keyword_text"]
            )
            .returning(ProjectNegativeKeyword.id)
        )
        created[match_type] = len(list(db.scalars(statement)))
    return {
        "source_template_id": str(reference_template.id),
        "source_template_version": reference_template.version,
        "candidate_counts": {key: len(value) for key, value in candidates.items()},
        "created_counts": created,
        "created_total": sum(created.values()),
    }