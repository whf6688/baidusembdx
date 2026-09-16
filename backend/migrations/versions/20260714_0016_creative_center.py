"""Add project creative segments, combinations, assignments and review state."""

from alembic import op


revision = "20260714_0016"
down_revision = "20260714_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.creative_segments (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            segment_type varchar(30) NOT NULL,
            content varchar(200) NOT NULL,
            is_blacklisted boolean NOT NULL DEFAULT false,
            blacklist_reason text NULL,
            created_by varchar(100) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_creative_segments_type CHECK (segment_type IN ('title', 'description1', 'description2')),
            CONSTRAINT uq_creative_segments_project_type_content UNIQUE (project_id, segment_type, content)
        );
        CREATE INDEX IF NOT EXISTS ix_creative_segments_project_type
            ON search_marketing.creative_segments(project_id, segment_type);
        CREATE UNIQUE INDEX IF NOT EXISTS uq_creative_segments_project_type_content_lower
            ON search_marketing.creative_segments(project_id, segment_type, lower(content));

        CREATE TABLE IF NOT EXISTS search_marketing.creative_combinations (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            title_segment_id uuid NOT NULL REFERENCES search_marketing.creative_segments(id),
            description1_segment_id uuid NOT NULL REFERENCES search_marketing.creative_segments(id),
            description2_segment_id uuid NULL REFERENCES search_marketing.creative_segments(id),
            combination_hash varchar(64) NOT NULL,
            is_blacklisted boolean NOT NULL DEFAULT false,
            rejection_count integer NOT NULL DEFAULT 0,
            blacklist_reason text NULL,
            blacklisted_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_creative_combinations_project_hash UNIQUE (project_id, combination_hash),
            CONSTRAINT ck_creative_combinations_rejections CHECK (rejection_count >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_creative_combinations_project_blacklist
            ON search_marketing.creative_combinations(project_id, is_blacklisted);

        CREATE TABLE IF NOT EXISTS search_marketing.creative_assignments (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            job_id uuid NOT NULL REFERENCES search_marketing.ad_build_jobs(id) ON DELETE CASCADE,
            account_id uuid NOT NULL REFERENCES search_marketing.accounts(id),
            combination_id uuid NOT NULL REFERENCES search_marketing.creative_combinations(id),
            slot_number integer NOT NULL,
            generation integer NOT NULL DEFAULT 1,
            status varchar(40) NOT NULL DEFAULT 'planned',
            baidu_creative_id bigint NULL,
            main_reason varchar(30) NULL,
            detail_reason text NULL,
            rejection_recorded boolean NOT NULL DEFAULT false,
            creative_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            review_checked_at timestamptz NULL,
            submitted_at timestamptz NULL,
            deleted_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_creative_assignments_job_account_slot_generation UNIQUE (job_id, account_id, slot_number, generation),
            CONSTRAINT uq_creative_assignments_account_baidu_id UNIQUE (account_id, baidu_creative_id),
            CONSTRAINT ck_creative_assignments_slot CHECK (slot_number BETWEEN 1 AND 50),
            CONSTRAINT ck_creative_assignments_generation CHECK (generation >= 1)
        );
        CREATE INDEX IF NOT EXISTS ix_creative_assignments_job_id
            ON search_marketing.creative_assignments(job_id);
        CREATE INDEX IF NOT EXISTS ix_creative_assignments_account_id
            ON search_marketing.creative_assignments(account_id);
        CREATE INDEX IF NOT EXISTS ix_creative_assignments_combination_id
            ON search_marketing.creative_assignments(combination_id);
        CREATE INDEX IF NOT EXISTS ix_creative_assignments_review
            ON search_marketing.creative_assignments(project_id, status, review_checked_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS search_marketing.creative_assignments;
        DROP TABLE IF EXISTS search_marketing.creative_combinations;
        DROP TABLE IF EXISTS search_marketing.creative_segments;
        """
    )
