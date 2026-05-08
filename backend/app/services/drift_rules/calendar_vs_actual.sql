-- Drift rule: calendar-vs-actual divergence
-- Placeholder — fires when there were scheduled deep-work blocks in the last 3
-- days but no corresponding commits / task updates. Needs GCal MCP integration
-- to be real (Phase 4). For now we detect "empty work days" instead: weekdays
-- with zero task activity.
SELECT
    'calendar_vs_actual'::text            AS rule,
    'info'::text                          AS severity,
    0.40::float                           AS salience,
    'calendar'::text                      AS entity_type,
    NULL::text                            AS entity_id,
    format('Calendar-vs-actual: %s weekday(s) in last 7d with zero task activity', cnt) AS summary,
    jsonb_build_object(
        'empty_days', cnt
    ) AS details
FROM (
    SELECT count(*)::int AS cnt
    FROM generate_series(
        (now() - INTERVAL '7 days')::date,
        now()::date,
        INTERVAL '1 day'
    ) AS d(day)
    WHERE EXTRACT(ISODOW FROM d.day) BETWEEN 1 AND 5  -- weekdays
      AND NOT EXISTS (
        SELECT 1 FROM tasks
         WHERE date_trunc('day', created_at AT TIME ZONE 'UTC') = d.day
            OR date_trunc('day', COALESCE(completed_at, created_at) AT TIME ZONE 'UTC') = d.day
      )
) s
WHERE cnt >= 2
