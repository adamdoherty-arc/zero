-- Convert character_carousels to native Postgres monthly partitioning (W6).
--
-- Idempotent: detects if the table is already partitioned and exits early.
-- Drops inbound FK from character_carousel_versions.carousel_id (cascade cleanup
-- is now app-responsibility; see cleanup_orphaned_carousel_versions scheduler job).
--
-- Run manually via psql once, not via Alembic (Zero uses Base.metadata.create_all
-- for schema, so Alembic isn't the source of truth for ongoing deployments).
--
-- Usage:
--   docker exec -i zero-postgres psql -U zero -d zero < 036_carousel_partitioning.sql
--
-- Safe to re-run. Wraps the whole conversion in a single BEGIN/COMMIT so a
-- failure rolls back cleanly.

BEGIN;

DO $$
DECLARE
    is_partitioned boolean;
    start_month date;
    end_month date;
    cur_month date;
    next_month date;
    oldest date;
BEGIN
    -- Skip if already partitioned
    SELECT EXISTS (
        SELECT 1 FROM pg_partitioned_table pt
        JOIN pg_class c ON c.oid = pt.partrelid
        WHERE c.relname = 'character_carousels'
    ) INTO is_partitioned;

    IF is_partitioned THEN
        RAISE NOTICE 'character_carousels is already partitioned; no-op';
        RETURN;
    END IF;

    -- 1. Drop inbound FK (recreated at app level)
    EXECUTE 'ALTER TABLE character_carousel_versions DROP CONSTRAINT IF EXISTS character_carousel_versions_carousel_id_fkey';

    -- 2. Rename current table
    EXECUTE 'ALTER TABLE character_carousels RENAME TO character_carousels_old';

    -- 3. Create new partitioned table (LIKE copies columns + defaults + constraints
    --    except PKs and FKs). Partition key must be part of PK.
    EXECUTE $sql$
        CREATE TABLE character_carousels
        (LIKE character_carousels_old INCLUDING DEFAULTS INCLUDING GENERATED)
        PARTITION BY RANGE (created_at)
    $sql$;

    -- 4. Composite PK (partition key must be included)
    EXECUTE 'ALTER TABLE character_carousels ADD PRIMARY KEY (id, created_at)';

    -- 5. Determine partition window from historical data
    SELECT COALESCE(date_trunc('month', MIN(created_at))::date, date_trunc('month', now())::date)
      INTO oldest FROM character_carousels_old;
    start_month := oldest;
    end_month := date_trunc('month', now() + interval '4 months')::date;

    -- 6. Create monthly partitions covering history + next 4 months
    cur_month := start_month;
    WHILE cur_month < end_month LOOP
        next_month := (cur_month + interval '1 month')::date;
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS character_carousels_%s PARTITION OF character_carousels FOR VALUES FROM (%L) TO (%L)',
            to_char(cur_month, 'YYYY_MM'), cur_month, next_month
        );
        cur_month := next_month;
    END LOOP;

    -- 7. Default partition catches anything outside the defined range (future-future,
    --    or legacy rows with NULL created_at should they exist).
    EXECUTE 'CREATE TABLE IF NOT EXISTS character_carousels_default PARTITION OF character_carousels DEFAULT';

    -- 8. Copy data
    EXECUTE 'INSERT INTO character_carousels SELECT * FROM character_carousels_old';

    -- 9. Recreate indexes (partitioned indexes cascade to partitions)
    CREATE INDEX IF NOT EXISTS idx_carousel_character_status ON character_carousels (character_id, status);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_character_id ON character_carousels (character_id);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_angle ON character_carousels (angle);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_content_type ON character_carousels (content_type);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_status ON character_carousels (status);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_publish_status ON character_carousels (publish_status);
    CREATE INDEX IF NOT EXISTS ix_character_carousels_media_title_id ON character_carousels (media_title_id);

    -- 10. Drop old table
    EXECUTE 'DROP TABLE character_carousels_old';

    RAISE NOTICE 'character_carousels partitioned successfully';
END $$;

COMMIT;
