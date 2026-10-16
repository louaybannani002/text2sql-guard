# Business glossary

These definitions are the default meaning of common business terms in this database. Apply them
unless the question explicitly asks for something else; when you rely on one that the question
leaves open, state it in `assumptions`.

## Grain: orders, not items

- Metrics are **order-level** by default. "Orders", "deliveries", "late deliveries", "sales
  count", "average order value" all count each order once: use `count(DISTINCT o.order_id)`
  whenever a join to `shop.order_items` or `shop.order_payments` can repeat an order.
- Use the item level only when the question is about items, units or products sold ("how many
  items", "units sold", "best-selling products"). One `shop.order_items` row is one unit.
- An average "per order" aggregates to one row per order first (in a CTE), then averages those.
  Never average item rows when the question is about orders.
- Reviews belong to orders. When a review is joined to items, sellers or categories, keep one
  row per review (or per review and grouping value) so a 3-item order does not count 3 times.

## Order date and periods

- The **order date** is `order_purchase_timestamp`. "Orders in 2017", "monthly sales" and
  similar periods filter and group on it, unless the question names another event ("delivered
  in March" uses the delivery date).
- Filter periods with half-open ranges on the timestamp
  (`>= DATE '2017-01-01' AND < DATE '2018-01-01'`). Months are `date_trunc('month', ...)::date`.

## Order statuses

- **Revenue / sales value** counts only fulfilled orders: `order_status = 'delivered'`.
- **Order volume** ("how many orders were placed") counts orders of every status unless the
  question restricts it.
- **Delivery metrics** (delivery time, late, on time, early) use only orders that reached the
  customer: `order_status = 'delivered'` and `order_delivered_customer_date IS NOT NULL`.
- `canceled` and `unavailable` orders were never fulfilled; `shipped` orders are on their way.

## Money

- **Revenue** = `sum(order_items.price)`: item prices only, freight excluded, over delivered
  orders. **Freight** is `order_items.freight_value`, reported separately.
- **Amount paid** (what customers paid, including freight and instalment interest) is
  `sum(order_payments.payment_value)`. An order may have several payment rows.

## Delivery

- **Delivery time** = from `order_purchase_timestamp` to `order_delivered_customer_date`, in
  days (`extract(epoch FROM delivered - purchased) / 86400`, rounded for display).
- **Late** = delivered on a later calendar day than promised:
  `order_delivered_customer_date::date > order_estimated_delivery_date`. Delivered on the
  promised day counts as on time.

## Places and people

- A **city** is always identified together with its state: group and display by both
  (`seller_city, seller_state`). The same city name exists in several states.
- A **customer** in the sense of a person is `shop.customer_person.person_key`; `customer_id`
  identifies the buyer of one order only.

## Presentation

- Percentages are on a 0-100 scale (`100.0 * part / total`), rounded to 1 decimal.
- "Top N" results are ordered by the metric, with a stable tie-breaker (e.g. the name or id).
