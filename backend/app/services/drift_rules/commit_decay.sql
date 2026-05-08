-- Drift rule: commit velocity decay
-- Fires when the 14-day commit EMA drops below 40% of the 8-week baseline.
-- Signals loss of momentum on an active project.
-- We approximate "commits" with task_events-style audit rows since Zero doesn't
-- yet have a git post-commit hook. Swaps to real commit counts in Phase 4.
SELECT
    'commit_decay'::text                  AS rule,
    'info'::text                          AS severity,
    0.55::float                           AS salience,
    'project'::text                       AS entity_type,
    p.id::text                            AS entity_id,
    format('Velocity decay on %s (14d avg %.1f/day vs 8w baseline %.1f/day)',
           p.name,
           COALESCE((t14.n::float / 14.0), 0),
           COALESCE((t56.n::float / 56.0), 0.001)) AS summary,
    jsonb_build_object(
        'project_id', p.id,
        'tasks_14d', COALESCE(t14.n, 0),
        'tasks_56d', COALESCE(t56.n, 0),
        'baseline_daily', COALESCE((t56.n::float / 56.0), 0)
    ) AS details
FROM projects p
LEFT JOIN LATERAL (
    SELECT count(*)::int AS n FROM tasks
    WHERE project_id = p.id AND created_at >= now() - INTERVAL '14 days'
) t14 ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*)::int AS n FROM tasks
    WHERE project_id = p.id AND created_at >= now() - INTERVAL '56 days'
) t56 ON TRUE
WHERE p.status = 'active'
  AND t56.n >= 10                          -- ignore brand-new projects with no baseline
  AND (t14.n::float / GREATEST(14.0, 1.0)) < 0.4 * (t56.n::float / 56.0)
