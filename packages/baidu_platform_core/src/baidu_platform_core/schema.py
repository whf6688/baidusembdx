from sqlalchemy import text


DDL = """
CREATE SCHEMA IF NOT EXISTS platform_core;
CREATE TABLE IF NOT EXISTS platform_core.authorization_tokens (
  id uuid PRIMARY KEY,
  baidu_application_code varchar(80) NOT NULL,
  owner_type varchar(30) NOT NULL,
  owner_id varchar(160) NOT NULL,
  login_name varchar(160) NOT NULL DEFAULT '',
  user_id bigint,
  open_id varchar(240),
  access_token_encrypted text NOT NULL,
  refresh_token_encrypted text NOT NULL,
  expires_at timestamptz NOT NULL,
  refresh_expires_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (baidu_application_code, owner_type, owner_id)
);
ALTER TABLE platform_core.authorization_tokens ADD COLUMN IF NOT EXISTS login_name varchar(160) NOT NULL DEFAULT '';
ALTER TABLE platform_core.authorization_tokens ADD COLUMN IF NOT EXISTS user_id bigint;
ALTER TABLE platform_core.authorization_tokens ADD COLUMN IF NOT EXISTS open_id varchar(240);
ALTER TABLE platform_core.authorization_tokens ADD COLUMN IF NOT EXISTS refresh_expires_at timestamptz;
CREATE TABLE IF NOT EXISTS platform_core.oauth_states (
  state_hash varchar(64) PRIMARY KEY,
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS platform_core.account_bindings (
  baidu_application_code varchar(80) NOT NULL,
  manager_login_name varchar(160) NOT NULL,
  target_account_id bigint NOT NULL,
  target_login_name varchar(160) NOT NULL,
  permission_status varchar(30) NOT NULL DEFAULT 'unchecked',
  PRIMARY KEY (baidu_application_code, target_account_id)
);
CREATE TABLE IF NOT EXISTS platform_core.distributed_locks (
  lock_key varchar(240) PRIMARY KEY,
  owner_id varchar(160) NOT NULL,
  expires_at timestamptz NOT NULL,
  heartbeat_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS platform_core.rate_limit_leases (
  bucket_key varchar(240) NOT NULL,
  lease_at timestamptz NOT NULL DEFAULT now(),
  app_code varchar(20) NOT NULL,
  request_batch varchar(160) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rate_limit_bucket_time ON platform_core.rate_limit_leases(bucket_key, lease_at);
CREATE TABLE IF NOT EXISTS platform_core.idempotency_records (
  idempotency_key varchar(160) PRIMARY KEY,
  app_code varchar(20) NOT NULL,
  target_account_id bigint NOT NULL,
  service varchar(200) NOT NULL,
  status varchar(30) NOT NULL,
  result_summary jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS platform_core.api_audit (
  id bigserial PRIMARY KEY,
  app_code varchar(20) NOT NULL,
  baidu_application_code varchar(80) NOT NULL,
  manager_login_name varchar(160),
  target_account_id bigint,
  target_login_name varchar(160),
  service varchar(200) NOT NULL,
  status_code integer,
  baidu_error_code varchar(80),
  elapsed_ms integer NOT NULL,
  retry_count integer NOT NULL DEFAULT 0,
  request_batch varchar(160),
  idempotency_key varchar(160),
  result_summary jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def ensure_platform_schema(engine) -> None:
    with engine.begin() as connection:
        for statement in [item.strip() for item in DDL.split(";") if item.strip()]:
            connection.execute(text(statement))
