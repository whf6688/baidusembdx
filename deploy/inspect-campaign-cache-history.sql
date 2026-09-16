\pset pager off
\pset format unaligned
\pset fieldsep '|'

SELECT
    id,
    status,
    created_at AT TIME ZONE 'Asia/Shanghai' AS created_bjt,
    heartbeat_at AT TIME ZONE 'Asia/Shanghai' AS completed_bjt,
    COALESCE(result->'state'->>'processed_accounts', '0') AS processed_accounts,
    COALESCE(result->'state'->>'cached_plan_count', '0') AS cached_plans,
    last_error
FROM search_marketing.background_tasks
WHERE task_type = 'campaign_cache_sync'
ORDER BY created_at DESC
LIMIT 10;

SELECT
    COUNT(*) AS cache_api_calls,
    MIN(created_at) AT TIME ZONE 'Asia/Shanghai' AS first_cache_call_bjt,
    MAX(created_at) AT TIME ZONE 'Asia/Shanghai' AS last_cache_call_bjt,
    COUNT(DISTINCT target_account_id) AS cached_accounts
FROM platform_core.api_audit
WHERE request_batch LIKE 'campaign-cache:%';
