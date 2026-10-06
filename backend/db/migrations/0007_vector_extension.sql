-- migrate: admin
-- pgvector is not a trusted extension, so creating it needs superuser. The docker init script
-- installs it in the dev database only; this makes every database (tests, prod) consistent.
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;

-- The vector type and its operators live in schema public, which 0004 closed to PUBLIC.
-- The owner needs them to create embedding columns; t2s_app already has USAGE.
GRANT USAGE ON SCHEMA public TO t2s_owner;
