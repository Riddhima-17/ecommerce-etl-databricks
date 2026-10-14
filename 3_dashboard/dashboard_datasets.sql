-- Datasets for the Ecommerce Sales dashboard (Databricks AI/BI dashboard).
-- Each block is one dataset: paste it into Dashboard -> Data -> "Create from SQL",
-- rename the dataset to the name in the comment, then build the widget listed under it.
-- All revenue is in INR (net_amount_inr = after discount, plus tax).


-- ============================================================
-- Dataset: kpis
-- Widgets: 4 x Counter -> revenue_inr, orders, customers, avg_order_value_inr
-- ============================================================
SELECT
  ROUND(SUM(net_amount_inr))                                   AS revenue_inr,
  COUNT(DISTINCT transaction_id)                               AS orders,
  COUNT(DISTINCT customer_id)                                  AS customers,
  ROUND(SUM(net_amount_inr) / COUNT(DISTINCT transaction_id))  AS avg_order_value_inr
FROM ecommerce.gold.fact_transactions_denorm;


-- ============================================================
-- Dataset: usd_transactions
-- Q: How many transactions were made in USD currency?
-- Widget: Counter -> usd_orders (and optionally a second Counter -> usd_order_lines)
-- ============================================================
SELECT
  COUNT(DISTINCT transaction_id) AS usd_orders,
  COUNT(*)                       AS usd_order_lines
FROM ecommerce.gold.fact_transactions_denorm
WHERE unit_price_currency = 'USD';


-- ============================================================
-- Dataset: monthly_revenue
-- Q: Total revenue (INR) and number of order lines by month for 2025, as a trend.
-- Widget: Line chart -> X: month, Y: revenue_inr
--         (optional 2nd Line/Bar chart -> X: month, Y: order_lines)
-- ============================================================
SELECT
  DATE_TRUNC('MONTH', transaction_date) AS month,
  ROUND(SUM(net_amount_inr))            AS revenue_inr,
  COUNT(*)                              AS order_lines
FROM ecommerce.gold.fact_transactions_denorm
WHERE year = 2025
GROUP BY 1
ORDER BY 1;


-- ============================================================
-- Dataset: top_products_august
-- Q: Top 10 products by revenue (INR) for August, with category and brand.
-- Widget: Table (columns as below)  or  Bar chart -> X: revenue_inr, Y: sku
-- ============================================================
SELECT
  product_id,
  sku,
  category_name,
  brand_name,
  SUM(quantity)               AS units_sold,
  ROUND(SUM(net_amount_inr))  AS revenue_inr
FROM ecommerce.gold.fact_transactions_denorm
WHERE year = 2025 AND month_name = 'August'
GROUP BY product_id, sku, category_name, brand_name
ORDER BY revenue_inr DESC
LIMIT 10;


-- ============================================================
-- Dataset: daily_revenue
-- Q (part 1): Biggest single revenue day in the period.
-- Widget: Bar chart -> X: transaction_date, Y: revenue_inr
-- ============================================================
SELECT
  transaction_date,
  ROUND(SUM(net_amount_inr)) AS revenue_inr,
  COUNT(DISTINCT transaction_id) AS orders
FROM ecommerce.gold.fact_transactions_denorm
GROUP BY transaction_date
ORDER BY transaction_date;


-- ============================================================
-- Dataset: top_day_segments
-- Q (part 2): Which product segments drove the biggest revenue day?
-- Widget: Bar chart -> X: category_name, Y: revenue_inr   (title it with top_day)
-- ============================================================
WITH top_day AS (
  SELECT transaction_date
  FROM ecommerce.gold.fact_transactions_denorm
  GROUP BY transaction_date
  ORDER BY SUM(net_amount_inr) DESC
  LIMIT 1
)
SELECT
  f.transaction_date                AS top_day,
  f.category_name,
  ROUND(SUM(f.net_amount_inr))      AS revenue_inr,
  ROUND(100 * SUM(f.net_amount_inr) / SUM(SUM(f.net_amount_inr)) OVER (), 1) AS pct_of_day
FROM ecommerce.gold.fact_transactions_denorm f
JOIN top_day t ON f.transaction_date = t.transaction_date
GROUP BY f.transaction_date, f.category_name
ORDER BY revenue_inr DESC;


-- ============================================================
-- Dataset: revenue_per_customer_by_channel
-- Q: Average revenue per customer by channel (Website vs Mobile) across each month.
-- Widget: Bar chart (grouped) -> X: month, Y: revenue_per_customer_inr, Color: channel
-- ============================================================
SELECT
  DATE_TRUNC('MONTH', transaction_date) AS month,
  channel,
  ROUND(SUM(net_amount_inr) / COUNT(DISTINCT customer_id)) AS revenue_per_customer_inr
FROM ecommerce.gold.fact_transactions_denorm
GROUP BY 1, 2
ORDER BY 1, 2;


-- ============================================================
-- Dataset: customers_by_country
-- Q: Distribution of customers by country.
-- Widget: Bar chart -> X: country, Y: customers   (or Pie chart: Angle customers, Color country)
-- ============================================================
SELECT
  country,
  COUNT(*) AS customers
FROM ecommerce.gold.gld_dim_customers
GROUP BY country
ORDER BY customers DESC;


-- ============================================================
-- Dataset: revenue_by_region
-- Q: Average revenue per region.
-- Widget: Table, or Bar chart -> X: region, Y: revenue_per_customer_inr, Color: country
-- ============================================================
SELECT
  c.country,
  c.region,
  COUNT(DISTINCT f.customer_id)                                AS customers,
  ROUND(SUM(f.net_amount_inr))                                 AS revenue_inr,
  ROUND(SUM(f.net_amount_inr) / COUNT(DISTINCT f.customer_id)) AS revenue_per_customer_inr,
  ROUND(AVG(f.net_amount_inr))                                 AS avg_order_line_inr
FROM ecommerce.gold.fact_transactions_denorm f
JOIN ecommerce.gold.gld_dim_customers c ON f.customer_id = c.customer_id
GROUP BY c.country, c.region
ORDER BY revenue_inr DESC;
