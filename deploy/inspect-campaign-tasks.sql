\pset pager off
\pset format unaligned
\pset fieldsep '|'

SELECT
    id,
    status,
    current_node,
    progress,
    retry_count,
    created_at AT TIME ZONE 'Asia/Shanghai' AS created_bjt,
    heartbeat_at AT TIME ZONE 'Asia/Shanghai' AS heartbeat_bjt,
    last_error,
    result->'request'->>'action' AS action,
    jsonb_array_length(COALESCE(result->'request'->'account_ids', '[]'::jsonb)) AS account_count,
    COALESCE(result->'state'->>'cursor', '0') AS cursor,
    COALESCE(result->'state'->>'processed_accounts', '0') AS processed,
    COALESCE(result->'state'->>'discovered_plan_count', '0') AS discovered,
    COALESCE(result->'state'->>'updated_plan_count', '0') AS updated,
    COALESCE(result->'state'->>'unchanged_plan_count', '0') AS unchanged
FROM search_marketing.background_tasks
WHERE task_type = 'campaign_batch_update'
ORDER BY created_at DESC
LIMIT 5;
