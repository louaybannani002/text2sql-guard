-- Olist Brazilian e-commerce marketplace data, 2016-09 .. 2018-10.
-- Timestamps carry no time zone in the source; they are Brazilian local time.

CREATE SCHEMA IF NOT EXISTS shop;

-- 32-character lowercase hex identifiers used by Olist for every entity.
CREATE DOMAIN shop.olist_id AS text
    CHECK (VALUE ~ '^[0-9a-f]{32}$');

-- First five digits of a Brazilian postal code (CEP), leading zeros preserved.
CREATE DOMAIN shop.zip_code_prefix AS text
    CHECK (VALUE ~ '^[0-9]{5}$');

-- Two-letter Brazilian state code (UF), e.g. SP, RJ.
CREATE DOMAIN shop.state_code AS text
    CHECK (VALUE ~ '^[A-Z]{2}$');

CREATE TABLE shop.customers (
    customer_id              shop.olist_id        PRIMARY KEY,
    customer_unique_id       shop.olist_id        NOT NULL,
    customer_zip_code_prefix shop.zip_code_prefix NOT NULL,
    customer_city            text                 NOT NULL,
    customer_state           shop.state_code      NOT NULL
);

CREATE TABLE shop.sellers (
    seller_id              shop.olist_id        PRIMARY KEY,
    seller_zip_code_prefix shop.zip_code_prefix NOT NULL,
    seller_city            text                 NOT NULL,
    seller_state           shop.state_code      NOT NULL
);

CREATE TABLE shop.product_categories (
    product_category_name         text PRIMARY KEY,
    product_category_name_english text NOT NULL UNIQUE
);

CREATE TABLE shop.products (
    product_id                 shop.olist_id PRIMARY KEY,
    product_category_name      text REFERENCES shop.product_categories (product_category_name),
    product_name_length        integer CHECK (product_name_length >= 0),
    product_description_length integer CHECK (product_description_length >= 0),
    product_photos_qty         integer CHECK (product_photos_qty >= 0),
    product_weight_g           integer CHECK (product_weight_g >= 0),
    product_length_cm          integer CHECK (product_length_cm >= 0),
    product_height_cm          integer CHECK (product_height_cm >= 0),
    product_width_cm           integer CHECK (product_width_cm >= 0)
);

CREATE TABLE shop.orders (
    order_id                      shop.olist_id PRIMARY KEY,
    customer_id                   shop.olist_id NOT NULL UNIQUE
                                  REFERENCES shop.customers (customer_id),
    order_status                  text          NOT NULL CHECK (order_status IN (
                                      'created', 'approved', 'invoiced', 'processing',
                                      'shipped', 'delivered', 'canceled', 'unavailable')),
    order_purchase_timestamp      timestamp     NOT NULL,
    order_approved_at             timestamp,
    order_delivered_carrier_date  timestamp,
    order_delivered_customer_date timestamp,
    order_estimated_delivery_date date          NOT NULL
);

CREATE TABLE shop.order_items (
    order_id            shop.olist_id NOT NULL REFERENCES shop.orders (order_id),
    order_item_id       smallint      NOT NULL CHECK (order_item_id >= 1),
    product_id          shop.olist_id NOT NULL REFERENCES shop.products (product_id),
    seller_id           shop.olist_id NOT NULL REFERENCES shop.sellers (seller_id),
    shipping_limit_date timestamp     NOT NULL,
    price               numeric(10, 2) NOT NULL CHECK (price >= 0),
    freight_value       numeric(10, 2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE shop.order_payments (
    order_id             shop.olist_id  NOT NULL REFERENCES shop.orders (order_id),
    payment_sequential   smallint       NOT NULL CHECK (payment_sequential >= 1),
    payment_type         text           NOT NULL CHECK (payment_type IN (
                                            'credit_card', 'boleto', 'voucher',
                                            'debit_card', 'not_defined')),
    payment_installments smallint       NOT NULL CHECK (payment_installments >= 0),
    payment_value        numeric(10, 2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE shop.order_reviews (
    review_id               shop.olist_id NOT NULL,
    order_id                shop.olist_id NOT NULL REFERENCES shop.orders (order_id),
    review_score            smallint      NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title    text,
    review_comment_message  text,
    review_creation_date    timestamp     NOT NULL,
    review_answer_timestamp timestamp     NOT NULL,
    PRIMARY KEY (review_id, order_id)
);

CREATE TABLE shop.geolocations (
    geolocation_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    geolocation_zip_code_prefix shop.zip_code_prefix NOT NULL,
    geolocation_lat             double precision     NOT NULL CHECK (geolocation_lat BETWEEN -90 AND 90),
    geolocation_lng             double precision     NOT NULL CHECK (geolocation_lng BETWEEN -180 AND 180),
    geolocation_city            text                 NOT NULL,
    geolocation_state           shop.state_code      NOT NULL
);
