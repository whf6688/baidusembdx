import argparse
import json
from pathlib import Path

from sqlalchemy import select, text

from search_console.db import SessionLocal
from search_console.historical_keyword_performance import (
    import_historical_keyword_performance,
)
from search_console.models import Project


def main() -> None:
    parser = argparse.ArgumentParser(description="导入项目级关键词年度历史累计指标")
    parser.add_argument("file", type=Path)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--project-code", default="jfsem")
    parser.add_argument("--actor", default="historical-import")
    args = parser.parse_args()

    content = args.file.read_bytes()
    with SessionLocal() as db:
        project = db.scalar(select(Project).where(Project.code == args.project_code))
        if project is None:
            raise SystemExit(f"项目不存在：{args.project_code}")
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"historical-keyword-performance:{project.id}:{args.year}"},
        )
        report = import_historical_keyword_performance(
            db,
            project_id=project.id,
            report_year=args.year,
            content=content,
            actor=args.actor,
        )
        db.commit()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
