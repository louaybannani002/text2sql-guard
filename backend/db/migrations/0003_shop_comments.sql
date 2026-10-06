-- Business-language descriptions of every table and column.
-- These are read by the retrieval layer and shown to the LLM, so write them for an analyst.

COMMENT ON SCHEMA shop IS
    'Olist, a Brazilian online marketplace: about 100k orders placed between September 2016 and October 2018. Each order is bought by one customer and can contain items from several independent sellers. All timestamps are Brazilian local time.';

-- customers
COMMENT ON TABLE shop.customers IS
    'Customer of a single order. Olist creates a new customer_id for every order, so one row = one order''s buyer. Use customer_unique_id to identify the same real person across orders (repeat customers).';
COMMENT ON COLUMN shop.customers.customer_id IS
    'Identifier of the buyer for one specific order; joins to orders.customer_id (exactly one order per customer_id).';
COMMENT ON COLUMN shop.customers.customer_unique_id IS
    'Identifier of the real person behind the purchase. Count DISTINCT customer_unique_id to count unique shoppers or find repeat buyers.';
COMMENT ON COLUMN shop.customers.customer_zip_code_prefix IS
    'First five digits of the customer''s delivery postal code (CEP). Can be matched to geolocations.geolocation_zip_code_prefix for coordinates.';
COMMENT ON COLUMN shop.customers.customer_city IS
    'City of the customer''s delivery address, lowercase without accents (e.g. ''sao paulo'').';
COMMENT ON COLUMN shop.customers.customer_state IS
    'Two-letter Brazilian state code of the delivery address (e.g. SP = São Paulo, RJ = Rio de Janeiro, MG = Minas Gerais).';

-- sellers
COMMENT ON TABLE shop.sellers IS
    'Independent merchants who sell products through the Olist marketplace and ship the items.';
COMMENT ON COLUMN shop.sellers.seller_id IS
    'Unique identifier of the seller.';
COMMENT ON COLUMN shop.sellers.seller_zip_code_prefix IS
    'First five digits of the seller''s postal code (CEP). Can be matched to geolocations.geolocation_zip_code_prefix for coordinates.';
COMMENT ON COLUMN shop.sellers.seller_city IS
    'City where the seller is located, lowercase.';
COMMENT ON COLUMN shop.sellers.seller_state IS
    'Two-letter Brazilian state code where the seller is located (e.g. SP, PR, MG).';

-- product_categories
COMMENT ON TABLE shop.product_categories IS
    'Lookup of product categories with their original Portuguese name and English translation. Prefer the English name when reporting.';
COMMENT ON COLUMN shop.product_categories.product_category_name IS
    'Category name in Portuguese as used by Olist (e.g. ''beleza_saude''); joins to products.product_category_name.';
COMMENT ON COLUMN shop.product_categories.product_category_name_english IS
    'Category name in English (e.g. ''health_beauty''). Use this for human-readable reports.';

-- products
COMMENT ON TABLE shop.products IS
    'Catalogue of products sold on the marketplace, with category and physical package attributes. Product titles and descriptions themselves are not available, only their lengths.';
COMMENT ON COLUMN shop.products.product_id IS
    'Unique identifier of the product.';
COMMENT ON COLUMN shop.products.product_category_name IS
    'Portuguese category name; join to product_categories for the English name. NULL for about 600 products with no category.';
COMMENT ON COLUMN shop.products.product_name_length IS
    'Number of characters in the product''s listing title. NULL when unknown.';
COMMENT ON COLUMN shop.products.product_description_length IS
    'Number of characters in the product''s listing description. NULL when unknown.';
COMMENT ON COLUMN shop.products.product_photos_qty IS
    'Number of photos published on the product listing. NULL when unknown.';
COMMENT ON COLUMN shop.products.product_weight_g IS
    'Shipping weight of the product in grams.';
COMMENT ON COLUMN shop.products.product_length_cm IS
    'Package length in centimetres.';
COMMENT ON COLUMN shop.products.product_height_cm IS
    'Package height in centimetres.';
COMMENT ON COLUMN shop.products.product_width_cm IS
    'Package width in centimetres.';

-- orders
COMMENT ON TABLE shop.orders IS
    'One row per customer order, with its lifecycle status and key dates from purchase to delivery. Central table: items, payments and reviews all link here by order_id.';
COMMENT ON COLUMN shop.orders.order_id IS
    'Unique identifier of the order.';
COMMENT ON COLUMN shop.orders.customer_id IS
    'Buyer of this order; joins to customers.customer_id (one customer_id per order).';
COMMENT ON COLUMN shop.orders.order_status IS
    'Current state of the order: created, approved, invoiced, processing, shipped, delivered, canceled or unavailable. Most completed sales are ''delivered''.';
COMMENT ON COLUMN shop.orders.order_purchase_timestamp IS
    'When the customer placed the order. Use this as the order date for sales over time.';
COMMENT ON COLUMN shop.orders.order_approved_at IS
    'When the payment was approved. NULL if never approved (e.g. canceled before payment).';
COMMENT ON COLUMN shop.orders.order_delivered_carrier_date IS
    'When the seller handed the order to the logistics carrier. NULL if not yet shipped.';
COMMENT ON COLUMN shop.orders.order_delivered_customer_date IS
    'When the order was actually delivered to the customer. NULL if not delivered. Compare with order_estimated_delivery_date to measure late deliveries.';
COMMENT ON COLUMN shop.orders.order_estimated_delivery_date IS
    'Delivery date promised to the customer at the time of purchase.';

-- order_items
COMMENT ON TABLE shop.order_items IS
    'Individual items within an order. An order with 3 units has 3 rows (order_item_id 1, 2, 3), possibly from different sellers. Revenue = SUM(price); total paid by the customer for items = SUM(price + freight_value).';
COMMENT ON COLUMN shop.order_items.order_id IS
    'Order this item belongs to; joins to orders.order_id.';
COMMENT ON COLUMN shop.order_items.order_item_id IS
    'Sequential number of the item within its order, starting at 1. MAX(order_item_id) per order = number of items in the order.';
COMMENT ON COLUMN shop.order_items.product_id IS
    'Product sold; joins to products.product_id.';
COMMENT ON COLUMN shop.order_items.seller_id IS
    'Seller who sold and ships this item; joins to sellers.seller_id.';
COMMENT ON COLUMN shop.order_items.shipping_limit_date IS
    'Deadline for the seller to hand the item over to the carrier.';
COMMENT ON COLUMN shop.order_items.price IS
    'Price of this single item in Brazilian reais (BRL), excluding freight.';
COMMENT ON COLUMN shop.order_items.freight_value IS
    'Shipping cost charged for this item in Brazilian reais (BRL). When an order has several items, the order''s freight is split across them.';

-- order_payments
COMMENT ON TABLE shop.order_payments IS
    'Payments made for orders. An order can be paid with several methods (e.g. a voucher plus a credit card), giving several rows. SUM(payment_value) per order = total amount paid.';
COMMENT ON COLUMN shop.order_payments.order_id IS
    'Order being paid; joins to orders.order_id.';
COMMENT ON COLUMN shop.order_payments.payment_sequential IS
    'Sequence number of this payment within the order, starting at 1.';
COMMENT ON COLUMN shop.order_payments.payment_type IS
    'Payment method: credit_card, boleto (Brazilian bank slip, paid in cash/online banking), voucher, debit_card, or not_defined.';
COMMENT ON COLUMN shop.order_payments.payment_installments IS
    'Number of monthly instalments chosen by the customer (mainly for credit cards); 1 means paid in full.';
COMMENT ON COLUMN shop.order_payments.payment_value IS
    'Amount paid with this payment method, in Brazilian reais (BRL).';

-- order_reviews
COMMENT ON TABLE shop.order_reviews IS
    'Satisfaction surveys sent to customers after delivery (or the estimated delivery date). Most orders have one review; a few have several.';
COMMENT ON COLUMN shop.order_reviews.review_id IS
    'Identifier of the review. Not unique on its own: the same survey can be linked to more than one order.';
COMMENT ON COLUMN shop.order_reviews.order_id IS
    'Order being reviewed; joins to orders.order_id.';
COMMENT ON COLUMN shop.order_reviews.review_score IS
    'Customer satisfaction rating from 1 (very dissatisfied) to 5 (very satisfied).';
COMMENT ON COLUMN shop.order_reviews.review_comment_title IS
    'Optional short title written by the customer, in Portuguese. Usually NULL.';
COMMENT ON COLUMN shop.order_reviews.review_comment_message IS
    'Optional free-text comment written by the customer, in Portuguese. NULL for most reviews.';
COMMENT ON COLUMN shop.order_reviews.review_creation_date IS
    'When the satisfaction survey was sent to the customer.';
COMMENT ON COLUMN shop.order_reviews.review_answer_timestamp IS
    'When the customer submitted the survey answer.';

-- geolocations
COMMENT ON TABLE shop.geolocations IS
    'Known coordinates for Brazilian postal code prefixes. A zip prefix has MANY rows (one per sampled address), so aggregate (e.g. AVG of lat/lng per prefix) before joining to customers or sellers to avoid multiplying rows. Not every customer/seller prefix is present.';
COMMENT ON COLUMN shop.geolocations.geolocation_id IS
    'Surrogate row identifier (has no business meaning).';
COMMENT ON COLUMN shop.geolocations.geolocation_zip_code_prefix IS
    'First five digits of a postal code (CEP); matches customers.customer_zip_code_prefix and sellers.seller_zip_code_prefix.';
COMMENT ON COLUMN shop.geolocations.geolocation_lat IS
    'Latitude in decimal degrees (negative = south of the equator).';
COMMENT ON COLUMN shop.geolocations.geolocation_lng IS
    'Longitude in decimal degrees (negative = west of Greenwich).';
COMMENT ON COLUMN shop.geolocations.geolocation_city IS
    'City name for this postal code as recorded by Olist (spelling and accents may vary).';
COMMENT ON COLUMN shop.geolocations.geolocation_state IS
    'Two-letter Brazilian state code for this postal code.';
