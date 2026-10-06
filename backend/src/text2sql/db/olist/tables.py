"""Mapping from Olist CSV files to ``shop`` tables, in foreign-key load order."""

from dataclasses import dataclass

from text2sql.db.olist import cleaning as c


@dataclass(frozen=True, slots=True)
class Column:
    """One target column, the CSV header it comes from, and how to parse it."""

    name: str
    source: str
    parse: c.Parser


@dataclass(frozen=True, slots=True)
class TableSpec:
    """How to load one ``shop`` table from one CSV file."""

    table: str
    csv_file: str
    columns: tuple[Column, ...]
    deduplicate: bool = False

    @property
    def column_names(self) -> list[str]:
        """Target column names, in COPY order."""
        return [col.name for col in self.columns]


def _same(parse: c.Parser, *names: str) -> tuple[Column, ...]:
    return tuple(Column(n, n, parse) for n in names)


# Categories referenced by products but missing from the official translation file.
MISSING_CATEGORY_TRANSLATIONS: dict[str, str] = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_processors",
}

PRODUCT_CATEGORIES = TableSpec(
    "product_categories",
    "product_category_name_translation.csv",
    _same(c.text, "product_category_name", "product_category_name_english"),
)

TABLES: tuple[TableSpec, ...] = (
    PRODUCT_CATEGORIES,
    TableSpec(
        "customers",
        "olist_customers_dataset.csv",
        _same(
            c.text,
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
    ),
    TableSpec(
        "sellers",
        "olist_sellers_dataset.csv",
        _same(c.text, "seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"),
    ),
    TableSpec(
        "products",
        "olist_products_dataset.csv",
        (
            *_same(c.text, "product_id", "product_category_name"),
            # The source headers misspell "length".
            Column("product_name_length", "product_name_lenght", c.integer),
            Column("product_description_length", "product_description_lenght", c.integer),
            *_same(
                c.integer,
                "product_photos_qty",
                "product_weight_g",
                "product_length_cm",
                "product_height_cm",
                "product_width_cm",
            ),
        ),
    ),
    TableSpec(
        "orders",
        "olist_orders_dataset.csv",
        (
            *_same(c.text, "order_id", "customer_id", "order_status"),
            *_same(
                c.timestamp,
                "order_purchase_timestamp",
                "order_approved_at",
                "order_delivered_carrier_date",
                "order_delivered_customer_date",
            ),
            Column("order_estimated_delivery_date", "order_estimated_delivery_date", c.date_only),
        ),
    ),
    TableSpec(
        "order_items",
        "olist_order_items_dataset.csv",
        (
            *_same(c.text, "order_id"),
            *_same(c.integer, "order_item_id"),
            *_same(c.text, "product_id", "seller_id"),
            *_same(c.timestamp, "shipping_limit_date"),
            *_same(c.decimal, "price", "freight_value"),
        ),
    ),
    TableSpec(
        "order_payments",
        "olist_order_payments_dataset.csv",
        (
            *_same(c.text, "order_id"),
            *_same(c.integer, "payment_sequential"),
            *_same(c.text, "payment_type"),
            *_same(c.integer, "payment_installments"),
            *_same(c.decimal, "payment_value"),
        ),
    ),
    TableSpec(
        "order_reviews",
        "olist_order_reviews_dataset.csv",
        (
            *_same(c.text, "review_id", "order_id"),
            *_same(c.integer, "review_score"),
            *_same(c.text, "review_comment_title", "review_comment_message"),
            *_same(c.timestamp, "review_creation_date", "review_answer_timestamp"),
        ),
    ),
    TableSpec(
        "geolocations",
        "olist_geolocation_dataset.csv",
        (
            *_same(c.text, "geolocation_zip_code_prefix"),
            *_same(c.floating, "geolocation_lat", "geolocation_lng"),
            *_same(c.text, "geolocation_city", "geolocation_state"),
        ),
        # ~26% of source rows are exact duplicates and carry no information.
        deduplicate=True,
    ),
)
