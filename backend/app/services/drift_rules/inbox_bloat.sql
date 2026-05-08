-- Drift rule: inbox bloat
-- Unprocessed items (status=backlog, source=MANUAL or similar) older than 5 days
-- are a signal that the weekly review isn't clearing the inbox.
SELECT
    'inbox_bloat'::text                   AS rule,
    'info'::text                          AS severity,
    0.45::float                           AS salience,
    'inbox'::text                         AS entity_type,
    NULL::text                            AS entity_id,
    format('Inbox bloat: %s tasks in backlog >5d', count(*)) AS summary,
    jsonb_build_object(
        'count', count(*),
        'oldest_id', (array_agg(id ORDER BY created_at ASC))[1],
        'oldest_age_days', EXTRACT(DAY FROM now() - MIN(created_at))::int
    ) AS details
FROM tasks
WHERE status = 'backlog'
  AND created_at < now() - INTERVAL '5 days'
HAVING count(*) >= 5
