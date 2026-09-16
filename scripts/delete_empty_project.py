"""Delete an empty local project without touching Baidu or another database."""

from __future__ import annotations

import argparse

from sqlalchemy import delete, func, select

from search_console.db import SessionLocal
from search_console.models import (
    Account,
    AccountCategory,
    AccountDraft,
    AccountManager,
    AuditEvent,
    KeywordDeploymentPlan,
    KeywordTierTemplate,
    Material,
    Project,
    ProjectPreference,
)


PROTECTED_MODELS = (
    AccountManager,
    AccountDraft,
    AccountCategory,
    Account,
    Material,
    KeywordDeploymentPlan,
    ProjectPreference,
    AuditEvent,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("code")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    with SessionLocal.begin() as db:
        project = db.scalar(select(Project).where(Project.code == args.code))
        if project is None:
            print(f"not_found={args.code}")
            return 0

        counts = {
            model.__tablename__: db.scalar(
                select(func.count()).select_from(model).where(model.project_id == project.id)
            )
            or 0
            for model in PROTECTED_MODELS
        }
        template_count = db.scalar(
            select(func.count())
            .select_from(KeywordTierTemplate)
            .where(KeywordTierTemplate.project_id == project.id)
        ) or 0

        print(f"project={project.name}/{project.code}")
        for table, count in counts.items():
            print(f"{table}={count}")
        print(f"keyword_tier_templates={template_count}")

        populated = {table: count for table, count in counts.items() if count}
        if populated:
            print("refused=project_has_business_data")
            return 2
        if not args.execute:
            print("dry_run=true")
            return 0

        db.execute(
            delete(KeywordTierTemplate).where(KeywordTierTemplate.project_id == project.id)
        )
        db.delete(project)
        print("deleted=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
