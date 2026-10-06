# Schema shop (PostgreSQL 16). Only columns readable by the query role are listed.
## shop.customer_person (materialized view)
Maps each order's customer_id to an anonymous person_key identifying the real shopper. Use it to count unique customers (COUNT(DISTINCT person_key)) and repeat customers (person_keys with more than one order). Join to orders on customer_id.

- customer_id (shop.olist_id, nullable): Buyer of one order; joins to orders.customer_id and customers.customer_id (one row per order).
- person_key (integer, nullable): Anonymous integer identifying the real person behind the purchase: the same shopper gets the same person_key on every order. Use only for counting and grouping; values are renumbered when the data is refreshed, so never store or compare them across refreshes.

## shop.customers (table)
Customer of a single order. Olist creates a new customer_id for every order, so one row = one order's buyer and counting customers counts orders. To count real people or repeat buyers, join shop.customer_person and use person_key. Only customer_id and customer_state are queryable; the other columns are restricted personal data.

- customer_id (shop.olist_id): Identifier of the buyer for one specific order; joins to orders.customer_id (exactly one order per customer_id).
- customer_state (shop.state_code): Two-letter Brazilian state code of the delivery address (e.g. SP = São Paulo, RJ = Rio de Janeiro, MG = Minas Gerais).

## shop.geolocations (table)
Known coordinates for Brazilian postal code prefixes. A zip prefix has MANY rows (one per sampled address), so aggregate per prefix before use. Customer and seller zip codes are restricted, so this table cannot be joined to them.

- geolocation_id (bigint): Surrogate row identifier (has no business meaning).
- geolocation_zip_code_prefix (shop.zip_code_prefix): First five digits of a postal code (CEP); matches customers.customer_zip_code_prefix and sellers.seller_zip_code_prefix.
- geolocation_lat (double precision): Latitude in decimal degrees (negative = south of the equator).
- geolocation_lng (double precision): Longitude in decimal degrees (negative = west of Greenwich).
- geolocation_city (text): City name for this postal code as recorded by Olist (spelling and accents may vary).
- geolocation_state (shop.state_code): Two-letter Brazilian state code for this postal code.

## shop.order_items (table)
Individual items within an order. An order with 3 units has 3 rows (order_item_id 1, 2, 3), possibly from different sellers. Revenue = SUM(price); total paid by the customer for items = SUM(price + freight_value).

- order_id (shop.olist_id): Order this item belongs to; joins to orders.order_id.
- order_item_id (smallint): Sequential number of the item within its order, starting at 1. MAX(order_item_id) per order = number of items in the order.
- product_id (shop.olist_id): Product sold; joins to products.product_id.
- seller_id (shop.olist_id): Seller who sold and ships this item; joins to sellers.seller_id.
- shipping_limit_date (timestamp without time zone): Deadline for the seller to hand the item over to the carrier.
- price (numeric(10,2)): Price of this single item in Brazilian reais (BRL), excluding freight.
- freight_value (numeric(10,2)): Shipping cost charged for this item in Brazilian reais (BRL). When an order has several items, the order's freight is split across them.

## shop.order_payments (table)
Payments made for orders. An order can be paid with several methods (e.g. a voucher plus a credit card), giving several rows. SUM(payment_value) per order = total amount paid.

- order_id (shop.olist_id): Order being paid; joins to orders.order_id.
- payment_sequential (smallint): Sequence number of this payment within the order, starting at 1.
- payment_type (text): Payment method: credit_card, boleto (Brazilian bank slip, paid in cash/online banking), voucher, debit_card, or not_defined.
- payment_installments (smallint): Number of monthly instalments chosen by the customer (mainly for credit cards); 1 means paid in full.
- payment_value (numeric(10,2)): Amount paid with this payment method, in Brazilian reais (BRL).

## shop.order_reviews (table)
Satisfaction surveys sent to customers after delivery (or the estimated delivery date). Most orders have one review; a few have several.

- review_id (shop.olist_id): Identifier of the review. Not unique on its own: the same survey can be linked to more than one order.
- order_id (shop.olist_id): Order being reviewed; joins to orders.order_id.
- review_score (smallint): Customer satisfaction rating from 1 (very dissatisfied) to 5 (very satisfied).
- review_comment_title (text, nullable): Optional short title written by the customer, in Portuguese. Usually NULL.
- review_comment_message (text, nullable): Optional free-text comment written by the customer, in Portuguese. NULL for most reviews.
- review_creation_date (timestamp without time zone): When the satisfaction survey was sent to the customer.
- review_answer_timestamp (timestamp without time zone): When the customer submitted the survey answer.

## shop.orders (table)
One row per customer order, with its lifecycle status and key dates from purchase to delivery. Central table: items, payments and reviews all link here by order_id.

- order_id (shop.olist_id): Unique identifier of the order.
- customer_id (shop.olist_id): Buyer of this order; joins to customers.customer_id (one customer_id per order).
- order_status (text): Current state of the order: created, approved, invoiced, processing, shipped, delivered, canceled or unavailable. Most completed sales are 'delivered'.
- order_purchase_timestamp (timestamp without time zone): When the customer placed the order. Use this as the order date for sales over time.
- order_approved_at (timestamp without time zone, nullable): When the payment was approved. NULL if never approved (e.g. canceled before payment).
- order_delivered_carrier_date (timestamp without time zone, nullable): When the seller handed the order to the logistics carrier. NULL if not yet shipped.
- order_delivered_customer_date (timestamp without time zone, nullable): When the order was actually delivered to the customer. NULL if not delivered. Compare with order_estimated_delivery_date to measure late deliveries.
- order_estimated_delivery_date (date): Delivery date promised to the customer at the time of purchase.

## shop.product_categories (table)
Lookup of product categories with their original Portuguese name and English translation. Prefer the English name when reporting.

- product_category_name (text): Category name in Portuguese as used by Olist (e.g. 'beleza_saude'); joins to products.product_category_name.
- product_category_name_english (text): Category name in English (e.g. 'health_beauty'). Use this for human-readable reports.

## shop.products (table)
Catalogue of products sold on the marketplace, with category and physical package attributes. Product titles and descriptions themselves are not available, only their lengths.

- product_id (shop.olist_id): Unique identifier of the product.
- product_category_name (text, nullable): Portuguese category name; join to product_categories for the English name. NULL for about 600 products with no category.
- product_name_length (integer, nullable): Number of characters in the product's listing title. NULL when unknown.
- product_description_length (integer, nullable): Number of characters in the product's listing description. NULL when unknown.
- product_photos_qty (integer, nullable): Number of photos published on the product listing. NULL when unknown.
- product_weight_g (integer, nullable): Shipping weight of the product in grams.
- product_length_cm (integer, nullable): Package length in centimetres.
- product_height_cm (integer, nullable): Package height in centimetres.
- product_width_cm (integer, nullable): Package width in centimetres.

## shop.sellers (table)
Independent merchants who sell products through the Olist marketplace and ship the items.

- seller_id (shop.olist_id): Unique identifier of the seller.
- seller_city (text): City where the seller is located, lowercase.
- seller_state (shop.state_code): Two-letter Brazilian state code where the seller is located (e.g. SP, PR, MG).
