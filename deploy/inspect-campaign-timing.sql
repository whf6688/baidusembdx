\pset pager off
\pset format unaligned
\pset fieldsep '|'

SELECT
    id,
    status,
    created_at AT TIME ZONE 'Asia/Shanghai' AS created_bjt,
    heartbeat_at AT TIME ZONE 'Asia/Shanghai' AS completed_bjt,
    EXTRACT(EPOCH FROM (heartbeat_at - created_at))::integer AS duration_seconds,
    jsonb_array_length(COALESCE(result->'request'->'account_ids', '[]'::jsonb)) AS account_count,
    COALESCE(result->'state'->>'processed_accounts', '0') AS processed_accounts,
    COALESCE(result->'state'->>'discovered_plan_count', '0') AS discovered_plans,
    COALESCE(result->'state'->>'updated_plan_count', '0') AS updated_plans,
    COALESCE(result->'state'->>'campaign_cache_hits', '0') AS cache_hits,
    COALESCE(result->'state'->>'campaign_cache_refreshes', '0') AS cache_refreshes
FROM search_marketing.background_tasks
WHERE id = :'task_id'::uuid;

SELECT
    service,
    COUNT(*) AS calls,
    ROUND(AVG(elapsed_ms))::integer AS avg_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_ms)::integer AS p95_ms,
    MAX(elapsed_ms) AS max_ms,
    SUM(elapsed_ms) AS total_ms,
    COUNT(*) FILTER (WHERE status_code IS DISTINCT FROM 200 OR baidu_error_code IS NOT NULL) AS error_calls
FROM platform_core.api_audit
WHERE request_batch = 'campaign-batch:' || :'task_id'
GROUP BY service
ORDER BY service;

SELECT
    COUNT(*) AS total_calls,
    COUNT(DISTINCT target_account_id) AS account_count,
    SUM(elapsed_ms) AS api_total_ms,
    MIN(created_at) AT TIME ZONE 'Asia/Shanghai' AS first_call_bjt,
    MAX(created_at) AT TIME ZONE 'Asia/Shanghai' AS last_call_bjt,
    COUNT(*) FILTER (WHERE status_code IS DISTINCT FROM 200 OR baidu_error_code IS NOT NULL) AS error_calls
FROM platform_core.api_audit
WHERE request_batch = 'campaign-batch:' || :'task_id';
