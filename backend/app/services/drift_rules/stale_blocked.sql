-- Drift rule: stale blocked tasks
-- Tasks stuck in "blocked" status for >5 days are invisible failures that the
-- weekly review should surface.
SELECT
    'stale_blocked'::text                 AS rule,
    'warn'::text                          AS severity,
    0.70::float                           AS salience,
    'task'::text                          AS entity_type,
    t.id::text                            AS entity_id,
    format('Task "%s" blocked %s days (%s)', t.title,
           EXTRACT(DAY FROM (now() - t.created_at))::int,
           COALESCE(t.blocked_reason, 'no reason given')) AS summary,
    jsonb_build_object(
        'task_id', t.id,
        'blocked_reason', t.blocked_reason,
        'age_days', EXTRACT(DAY FROM (now() - t.created_at))::int
    ) AS details
FROM tasks t
WHERE t.status = 'blocked'
  AND t.created_at < now() - INTERVAL '5 days'
