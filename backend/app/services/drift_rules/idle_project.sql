-- Drift rule: idle project
-- Fires when an active project has had no updates in 7+ days.
-- Note: Zero's `projects` table doesn't carry a priority column today, so the
-- heuristic is binary (active + stale). When a priority column lands, re-add
-- a `AND p.priority <= 2` filter to narrow to load-bearing projects.
SELECT
    'idle_project'::text                  AS rule,
    'warn'::text                          AS severity,
    0.60::float                           AS salience,
    'project'::text                       AS entity_type,
    p.id::text                            AS entity_id,
    format('Project %s idle %s days',
           p.name,
           EXTRACT(DAY FROM (now() - p.updated_at))::int) AS summary,
    jsonb_build_object(
        'project_id', p.id,
        'last_activity', to_char(p.updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF')
    ) AS details
FROM projects p
WHERE p.status = 'active'
  AND p.updated_at < now() - INTERVAL '7 days'
