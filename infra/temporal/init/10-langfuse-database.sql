-- Langfuse self-hosted reuses the Temporal Postgres for its small relational
-- store. Trace volume goes to ClickHouse; this database holds users, projects,
-- API keys, datasets, and prompt-version metadata.
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
