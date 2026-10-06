-- Indexes on every foreign key not already covered by a leading primary-key column,
-- plus the columns analysts filter and group by most (dates, status, state).

-- customers
CREATE INDEX customers_customer_unique_id_idx ON shop.customers (customer_unique_id);
CREATE INDEX customers_customer_state_idx     ON shop.customers (customer_state);
CREATE INDEX customers_customer_zip_idx       ON shop.customers (customer_zip_code_prefix);

-- sellers
CREATE INDEX sellers_seller_state_idx ON shop.sellers (seller_state);
CREATE INDEX sellers_seller_zip_idx   ON shop.sellers (seller_zip_code_prefix);

-- products
CREATE INDEX products_product_category_name_idx ON shop.products (product_category_name);

-- orders (customer_id FK is covered by its UNIQUE constraint)
CREATE INDEX orders_order_status_idx                  ON shop.orders (order_status);
CREATE INDEX orders_order_purchase_timestamp_idx      ON shop.orders (order_purchase_timestamp);
CREATE INDEX orders_order_approved_at_idx             ON shop.orders (order_approved_at);
CREATE INDEX orders_order_delivered_customer_date_idx ON shop.orders (order_delivered_customer_date);
CREATE INDEX orders_order_estimated_delivery_date_idx ON shop.orders (order_estimated_delivery_date);

-- order_items (order_id FK is the leading PK column)
CREATE INDEX order_items_product_id_idx          ON shop.order_items (product_id);
CREATE INDEX order_items_seller_id_idx           ON shop.order_items (seller_id);
CREATE INDEX order_items_shipping_limit_date_idx ON shop.order_items (shipping_limit_date);

-- order_payments (order_id FK is the leading PK column)
CREATE INDEX order_payments_payment_type_idx ON shop.order_payments (payment_type);

-- order_reviews (PK leads with review_id, so order_id needs its own index)
CREATE INDEX order_reviews_order_id_idx             ON shop.order_reviews (order_id);
CREATE INDEX order_reviews_review_score_idx         ON shop.order_reviews (review_score);
CREATE INDEX order_reviews_review_creation_date_idx ON shop.order_reviews (review_creation_date);

-- geolocations
CREATE INDEX geolocations_zip_code_prefix_idx ON shop.geolocations (geolocation_zip_code_prefix);
CREATE INDEX geolocations_state_idx           ON shop.geolocations (geolocation_state);
