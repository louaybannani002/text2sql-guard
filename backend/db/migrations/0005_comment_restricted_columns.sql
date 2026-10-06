-- Personal-data columns are no longer readable by t2s_reader (0004). Update the comments the
-- LLM sees so it stops suggesting queries that are guaranteed to fail.

COMMENT ON TABLE shop.customers IS
    'Customer of a single order. Olist creates a new customer_id for every order, so one row = one order''s buyer and counting customers counts orders. Only customer_id and customer_state are queryable; the other columns are restricted personal data.';
COMMENT ON COLUMN shop.customers.customer_unique_id IS
    'RESTRICTED personal data: identifier of the real person behind the purchase. Not queryable.';
COMMENT ON COLUMN shop.customers.customer_zip_code_prefix IS
    'RESTRICTED personal data: postal code prefix of the delivery address. Not queryable.';
COMMENT ON COLUMN shop.customers.customer_city IS
    'RESTRICTED personal data: city of the delivery address. Not queryable; use customer_state for geography.';
COMMENT ON COLUMN shop.sellers.seller_zip_code_prefix IS
    'RESTRICTED: postal code prefix of the seller. Not queryable; use seller_city or seller_state.';
COMMENT ON TABLE shop.geolocations IS
    'Known coordinates for Brazilian postal code prefixes. A zip prefix has MANY rows (one per sampled address), so aggregate per prefix before use. Customer and seller zip codes are restricted, so this table cannot be joined to them.';
