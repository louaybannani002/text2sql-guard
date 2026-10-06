-- Retrieval catalog: one document per shop relation, plus few-shot examples, each with an
-- embedding (text-embedding-3-small, 1536 dimensions) and a keyword-search tsvector.
-- Written by `make catalog` (as t2s_owner); read by the app (t2s_app). Never by t2s_reader.

CREATE TABLE app.schema_docs (
    relation        text        PRIMARY KEY,
    kind            text        NOT NULL CHECK (kind IN ('table', 'view', 'materialized view')),
    content         text        NOT NULL,
    content_hash    text        NOT NULL,
    embedding       public.vector(1536) NOT NULL,
    embedding_model text        NOT NULL,
    search          tsvector    GENERATED ALWAYS AS (
                        setweight(to_tsvector('simple', relation), 'A')
                        || setweight(to_tsvector('english', content), 'B')
                    ) STORED,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX schema_docs_embedding_idx ON app.schema_docs
    USING hnsw (embedding public.vector_cosine_ops);
CREATE INDEX schema_docs_search_idx ON app.schema_docs USING gin (search);

CREATE TABLE app.examples (
    example_id      text        PRIMARY KEY CHECK (example_id ~ '^[a-z0-9_]+$'),
    question        text        NOT NULL,
    sql             text        NOT NULL,
    content_hash    text        NOT NULL,
    embedding       public.vector(1536) NOT NULL,
    embedding_model text        NOT NULL,
    search          tsvector    GENERATED ALWAYS AS (to_tsvector('english', question)) STORED,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX examples_embedding_idx ON app.examples
    USING hnsw (embedding public.vector_cosine_ops);
CREATE INDEX examples_search_idx ON app.examples USING gin (search);

-- Single row: the catalog version currently stored.
CREATE TABLE app.catalog_state (
    singleton       boolean     PRIMARY KEY DEFAULT true CHECK (singleton),
    schema_version  text        NOT NULL,
    embedding_model text        NOT NULL,
    documents       integer     NOT NULL,
    examples        integer     NOT NULL,
    built_at        timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE app.schema_docs IS
    'Retrieval documents describing each shop relation readable by t2s_reader (columns, comments, example values, foreign keys). Rebuilt by make catalog.';
COMMENT ON TABLE app.examples IS
    'Hand-reviewed question/SQL pairs used as few-shot examples. Source of truth: db/seeds/examples.toml.';
COMMENT ON TABLE app.catalog_state IS
    'Hash of the current catalog (schema_version) and when it was built; re-embedding happens only when it changes.';
