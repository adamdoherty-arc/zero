-- Drift rule: intent drift (last week's top_3 not reflected in activity)
-- SecondBrain §6 rule #4. Reads yesterday's or most-recent daily-note frontmatter
-- from vault_chunks (partition=journal), pulls `top_3`, and compares to active work.
--
-- MVP implementation: compare count of tasks with status='in_progress' vs
-- the number of daily-note checkbox annotations under ## Today in the last 7 days.
-- If there's a mismatch >3, fire the rule.
SELECT
    'intent_drift'::text                  AS rule,
    'info'::text                          AS severity,
    0.50::float                           AS salience,
    'intent'::text                        AS entity_type,
    NULL::text                            AS entity_id,
    format('Intent drift: %s in-progress tasks vs %s today-checkboxes over last 7 days',
           in_progress_count, today_checkbox_count) AS summary,
    jsonb_build_object(
        'in_progress_count', in_progress_count,
        'today_checkbox_count', today_checkbox_count
    ) AS details
FROM (
    SELECT
        (SELECT count(*)::int FROM tasks WHERE status = 'in_progress') AS in_progress_count,
        (SELECT count(*)::int FROM vault_chunks
            WHERE partition = 'journal'
              AND file_mtime >= now() - INTERVAL '7 days'
              AND content ~ '^-\s\[[ xX]\]\s'
        ) AS today_checkbox_count
) s
WHERE abs(in_progress_count - today_checkbox_count) >= 3
