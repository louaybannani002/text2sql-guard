-- Structured relation definition (columns, types, comments, sample values, foreign keys and
-- inferred view joins) next to each document, so the retriever can walk the join graph and
-- render CREATE TABLE-style context without reading schema shop itself.
--
-- The catalog is derived data: clear it so the column can be NOT NULL; the next
-- `make catalog` rebuilds it (re-embedding the 10 documents costs a fraction of a cent).
DELETE FROM app.schema_docs;
DELETE FROM app.catalog_state;

ALTER TABLE app.schema_docs ADD COLUMN definition jsonb NOT NULL;

COMMENT ON COLUMN app.schema_docs.definition IS
    'The relation as JSON (text2sql.retrieval.documents.definition_json): what the retriever uses to expand joins and render schema context.';
