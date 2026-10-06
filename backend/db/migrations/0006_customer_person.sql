-- Repeat-customer analysis without exposing customer_unique_id (restricted in 0004).
-- person_key is an opaque integer: dense_rank() over customer_unique_id. It is recomputed on
-- every refresh (`make refresh-views`, run automatically by `make load-data`).

CREATE MATERIALIZED VIEW shop.customer_person AS
SELECT
    customer_id,
    dense_rank() OVER (ORDER BY customer_unique_id)::integer AS person_key
FROM shop.customers
WITH DATA;

-- Unique index: required for REFRESH ... CONCURRENTLY and serves joins from orders.
CREATE UNIQUE INDEX customer_person_customer_id_idx ON shop.customer_person (customer_id);
CREATE INDEX customer_person_person_key_idx ON shop.customer_person (person_key);

GRANT SELECT ON shop.customer_person TO t2s_reader;

COMMENT ON MATERIALIZED VIEW shop.customer_person IS
    'Maps each order''s customer_id to an anonymous person_key identifying the real shopper. Use it to count unique customers (COUNT(DISTINCT person_key)) and repeat customers (person_keys with more than one order). Join to orders on customer_id.';
COMMENT ON COLUMN shop.customer_person.customer_id IS
    'Buyer of one order; joins to orders.customer_id and customers.customer_id (one row per order).';
COMMENT ON COLUMN shop.customer_person.person_key IS
    'Anonymous integer identifying the real person behind the purchase: the same shopper gets the same person_key on every order. Use only for counting and grouping; values are renumbered when the data is refreshed, so never store or compare them across refreshes.';

-- Point the LLM at the new view from the places it would look first.
COMMENT ON COLUMN shop.customers.customer_unique_id IS
    'RESTRICTED personal data: identifier of the real person behind the purchase. Not queryable; use shop.customer_person.person_key to count unique or repeat customers.';
COMMENT ON TABLE shop.customers IS
    'Customer of a single order. Olist creates a new customer_id for every order, so one row = one order''s buyer and counting customers counts orders. To count real people or repeat buyers, join shop.customer_person and use person_key. Only customer_id and customer_state are queryable; the other columns are restricted personal data.';
