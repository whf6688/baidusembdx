"""Bind account managers and accounts to a project workspace."""

from alembic import op

revision = "20260713_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS search_marketing.account_managers (
            id uuid PRIMARY KEY,
            project_id uuid NOT NULL REFERENCES search_marketing.projects(id),
            baidu_user_id bigint NULL,
            login_name varchar(150) NOT NULL,
            display_name varchar(150) NULL,
            auth_status varchar(30) NOT NULL DEFAULT 'unchecked',
            is_active boolean NOT NULL DEFAULT true,
            last_synced_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_account_managers_project_login UNIQUE (project_id, login_name)
        );
        CREATE INDEX IF NOT EXISTS ix_account_managers_project_id
            ON search_marketing.account_managers(project_id);
        ALTER TABLE search_marketing.accounts ADD COLUMN IF NOT EXISTS manager_id uuid NULL;
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'search_marketing.accounts'::regclass
                  AND contype = 'f'
                  AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (manager_id)%'
            ) THEN
                ALTER TABLE search_marketing.accounts
                    ADD CONSTRAINT fk_accounts_manager_id
                    FOREIGN KEY (manager_id) REFERENCES search_marketing.account_managers(id);
            END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS ix_accounts_project_manager
            ON search_marketing.accounts(project_id, manager_id);
        """
    )
    op.execute(
        """
        INSERT INTO search_marketing.account_managers
            (id, project_id, login_name, auth_status, is_active, created_at)
        SELECT
            (
                substr(md5(project_id::text || ':' || manager_login_name), 1, 8) || '-' ||
                substr(md5(project_id::text || ':' || manager_login_name), 9, 4) || '-' ||
                substr(md5(project_id::text || ':' || manager_login_name), 13, 4) || '-' ||
                substr(md5(project_id::text || ':' || manager_login_name), 17, 4) || '-' ||
                substr(md5(project_id::text || ':' || manager_login_name), 21, 12)
            )::uuid,
            project_id,
            manager_login_name,
            'unchecked',
            true,
            now()
        FROM search_marketing.accounts
        WHERE manager_login_name IS NOT NULL AND manager_login_name <> ''
        ON CONFLICT (project_id, login_name) DO NOTHING;

        UPDATE search_marketing.accounts AS account
        SET manager_id = manager.id
        FROM search_marketing.account_managers AS manager
        WHERE manager.project_id = account.project_id
          AND manager.login_name = account.manager_login_name
          AND account.manager_id IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE search_marketing.accounts DROP CONSTRAINT IF EXISTS fk_accounts_manager_id")
    op.execute("ALTER TABLE search_marketing.accounts DROP COLUMN IF EXISTS manager_id")
    op.execute("DROP TABLE IF EXISTS search_marketing.account_managers")
