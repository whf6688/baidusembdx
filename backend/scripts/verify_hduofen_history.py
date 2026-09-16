from __future__ import annotations

import argparse
import json
import uuid

from sqlalchemy import text

from search_console.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Hduofen history import task.")
    parser.add_argument("--task-id", required=True, type=uuid.UUID)
    args = parser.parse_args()

    with SessionLocal() as session:
        mapping = dict(
            session.execute(
                text(
                    """
                    SELECT count(*) AS rows,
                           count(DISTINCT custom_id) AS custom_ids,
                           count(DISTINCT account_id) AS accounts,
                           count(DISTINCT source_sha256) AS source_hashes,
                           min(source_file) AS source_file
                    FROM search_marketing.hduofen_account_mappings
                    """
                )
            ).one()._mapping
        )
        task_events = dict(
            session.execute(
                text(
                    """
                    SELECT count(*) AS rows,
                           count(DISTINCT (source_type, source_event_id)) AS unique_rows,
                           count(*) FILTER (WHERE metric_included) AS included,
                           count(*) FILTER (
                               WHERE exclusion_reason = 'custom_id_not_found'
                           ) AS table_outside_custom_ids
                    FROM search_marketing.hduofen_events
                    WHERE capture_task_id = :task_id
                    """
                ),
                {"task_id": args.task_id},
            ).one()._mapping
        )
        rule_check = dict(
            session.execute(
                text(
                    """
                    SELECT count(*) AS invalid_included_second_hop_visitors
                    FROM search_marketing.hduofen_events AS event
                    JOIN search_marketing.accounts AS account
                      ON account.id = event.account_id
                    WHERE event.capture_task_id = :task_id
                      AND event.source_type = 'visitors'
                      AND event.metric_included
                      AND account.account_type::text = 'SECOND_HOP'
                      AND nullif(btrim(event.tracking_keyword), '') IS NULL
                    """
                ),
                {"task_id": args.task_id},
            ).one()._mapping
        )

    print(
        json.dumps(
            {
                "mapping": mapping,
                "task_events": task_events,
                "rule_check": rule_check,
            },
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
