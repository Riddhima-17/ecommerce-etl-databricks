# E-commerce ETL Pipeline on Databricks

An end-to-end batch ETL pipeline that turns raw e-commerce CSV exports (orders, customers, products, brands, categories, calendar) into an analytics-ready **star schema** on the **Databricks Lakehouse**. It follows the **Medallion architecture** (Bronze → Silver → Gold), loads new order files **incrementally with Auto Loader**, and runs every day as a scheduled **Lakeflow Job** defined as code with **Databricks Asset Bundles**.

## Tech stack

| Area | Tools |
|---|---|
| Platform | Databricks (serverless compute), Unity Catalog (catalog, schemas, volumes) |
| Processing | Apache Spark: PySpark, Spark SQL |
| Storage | Delta Lake tables |
| Ingestion | Auto Loader (`cloudFiles`, Structured Streaming with `availableNow` trigger and checkpoints) |
| Orchestration | Lakeflow Jobs (8-task DAG, daily schedule, failure alerts) |
| Deployment | Databricks Asset Bundles, Databricks CLI |
| Serving / BI | Denormalised gold view, AI/BI Dashboard, Genie |
| Tooling | Python (test data generator) |

## Architecture

**Before: legacy AWS setup.** Data was pulled from the store database into S3 and processed by a mix of Lambda, Glue and cron jobs on EC2, then loaded into Redshift for reporting.

![Legacy architecture](resources/legacy_architecture.png)

**After: Databricks Lakehouse.** Storage, ETL and the warehouse are combined on one platform.

![Databricks architecture](resources/databricks_architecture.png)

### Pipeline (Lakeflow Job)

```
setup_catalog ──┬─> dim_bronze ─> dim_silver ─> dim_gold ──┐
                └─> fact_bronze ─> fact_silver ─> fact_gold ┴─> create_views
```

The dimension and fact branches run in parallel. The serving view is built once both gold layers have succeeded.

| Layer | Dimensions | Fact (order items) |
|---|---|---|
| **Bronze** | Full reload of the snapshot CSVs, plus source-file and ingest-time columns | **Incremental**: Auto Loader appends only files that haven't been loaded before |
| **Silver** | Cleaned and standardised | Deduplicated on `(order_id, item_seq)`, types fixed |
| **Gold** | `gld_dim_products`, `gld_dim_customers`, `gld_dim_date` | `gld_fact_order_items` |
| **Serving** | `fact_transactions_denorm` view for dashboards and Genie | |

Every task is safe to re-run: bronze is append-only through the checkpoint, and silver and gold are deterministic rebuilds.

## Data quality rules (Silver)

- **Products**: `"305g"` → `305` (int), `"22,2"` → `22.2` (float), upper-cased codes, misspelled materials fixed (`Coton` → `Cotton`, `Alumium` → `Aluminum`, `Ruber` → `Rubber`), negative rating counts made positive.
- **Brands / categories**: trimmed names, special characters removed from codes, category code fixes (`GROCERY` → `GRCY`, …), duplicates dropped.
- **Customers**: rows with null IDs dropped, missing phone numbers set to `Not Available`.
- **Calendar**: `dd-MM-yyyy` strings parsed to dates, duplicates dropped, day names in consistent case, negative week numbers fixed, `Q3-2025` / `Week31-2025` labels added.
- **Order items**: `"Two"` → `2`, `$` and `%` stripped from prices and discounts, timestamps parsed from two different formats, channel names standardised (`web` → `Website`, `app` → `Mobile`), coupon codes normalised.

## Gold metrics

- `gross_amount = quantity × unit_price`
- `discount_amount = ceil(gross × discount_pct / 100)`
- `net_amount = gross − discount + tax`
- `net_amount_inr`: converted from 7 currencies (INR, USD, GBP, AED, SGD, CAD, AUD) at fixed exchange rates
- Customers mapped to regions for 7 countries. The date dimension has `date_id`, month name and a weekend flag.

## Data

| Dataset | Rows |
|---|---|
| Order items (92 daily files, 2025-08-01 → 2025-10-31) | ~183K |
| Customers | 300K |
| Products | 50K |
| Brands, categories, calendar | small lookup tables |

`0_data/daily_uploads/` contains generated daily order files (from 2025-11-01) for testing the scheduled incremental loads. Generate more with:

```bash
python3 tools/generate_daily_orders.py --days 7
```

## Repository structure

```
├── 0_data/
│   ├── ecomm-raw-data/          # raw source CSVs (same layout as the Unity Catalog volume)
│   └── daily_uploads/           # generated daily order files for testing incremental loads
├── 1_codes/project_ecommerce/
│   ├── databricks.yml           # Asset Bundle: job, tasks, schedule, targets
│   ├── 1_setup/                 # catalog, schemas, volumes
│   ├── 2_medallion_processing_dim/   # bronze → silver → gold for dimensions
│   ├── 3_medallion_processing_fact/  # bronze (Auto Loader) → silver → gold for orders
│   └── 4_serving/               # denormalised view for BI
├── 2_genie_exploration/         # business questions for Genie
├── 3_dashboard/                 # view SQL and dashboard dataset queries
├── tools/generate_daily_orders.py
├── resources/                   # architecture diagrams
└── ETL_PIPELINE_GUIDE.md        # full setup, scheduling and operations guide
```

## Getting started

Requirements: a Databricks workspace with Unity Catalog and serverless jobs compute, and the [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html).

```bash
# 1. Authenticate
databricks auth login --host https://<your-workspace-host>

# 2. Set your host in 1_codes/project_ecommerce/databricks.yml, then deploy the notebooks and job
cd 1_codes/project_ecommerce
databricks bundle deploy -t dev

# 3. Create the catalog, schemas and volumes
databricks bundle run ecommerce_etl -t dev --only setup_catalog

# 4. Upload the raw data to the volume
cd ../..
databricks fs cp -r 0_data/ecomm-raw-data dbfs:/Volumes/ecommerce/source_data/raw --overwrite

# 5. Run the full pipeline
cd 1_codes/project_ecommerce
databricks bundle run ecommerce_etl -t dev
```

Deploying with `-t prod` turns on the daily 06:00 IST schedule. See [ETL_PIPELINE_GUIDE.md](ETL_PIPELINE_GUIDE.md) for the UI setup, daily operation, the dashboard and troubleshooting.

## Analytics questions answered

- How many transactions were made in USD?
- Monthly revenue (INR) and order lines for 2025
- Top 10 products by revenue in August, with category and brand
- The biggest single revenue day, and which product segments drove it
- Average revenue per customer by channel (Website vs Mobile) per month
- Customers by country, and average revenue per region

The queries are in [`3_dashboard/dashboard_datasets.sql`](3_dashboard/dashboard_datasets.sql).
