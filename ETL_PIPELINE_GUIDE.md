# Ecommerce ETL Pipeline: Build and Schedule Guide

Medallion pipeline on Databricks (Unity Catalog):

```
/Volumes/ecommerce/source_data/raw/   (CSV files you upload)
        │
setup_catalog ──┬─> dim_bronze ─> dim_silver ─> dim_gold ──┐
                └─> fact_bronze ─> fact_silver ─> fact_gold ┴─> create_views
```

| Layer | Dimensions (brands, category, products, customers, date) | Fact (order_items) |
|---|---|---|
| Bronze | Full reload of the snapshot CSVs (overwrite) | **Incremental**: Auto Loader appends only new files from `landing/` |
| Silver | Cleaned, overwrite | Rebuilt from all of bronze, deduplicated on `order_id, item_seq` |
| Gold | `gld_dim_products`, `gld_dim_customers`, `gld_dim_date` | `gld_fact_order_items` |
| Serving | `gold.fact_transactions_denorm` view for the dashboard and Genie | |

Every task is safe to re-run.

---

## Prerequisites

- A Databricks workspace with **Unity Catalog** and **serverless jobs compute** enabled. Without serverless, see step 5 for using a job cluster.
- Permission to `CREATE CATALOG` (or ask an admin to create the `ecommerce` catalog and grant you `ALL PRIVILEGES` on it).

---

## Step 1: Import the notebooks into the workspace

Pick **one** option.

**Option A: Databricks UI**
1. **Workspace → Users → your user → Create → Folder** → name it `project_ecommerce`.
2. Inside it, create the folders `1_setup`, `2_medallion_processing_dim`, `3_medallion_processing_fact` and `4_serving`.
3. In each folder, use **⋮ → Import → File** to upload the matching `.ipynb` files from `1_codes/project_ecommerce/`.

**Option B: Databricks CLI with the Asset Bundle (recommended, also creates the job)**
1. Install the CLI: `brew tap databricks/tap && brew install databricks`
2. Log in: `databricks auth login --host https://<your-workspace-host>`
3. In `1_codes/project_ecommerce/databricks.yml`, replace `<your-workspace-host>` (both targets).
4. From `1_codes/project_ecommerce/`, run:
   ```bash
   databricks bundle validate -t dev
   databricks bundle deploy -t dev
   ```
   This uploads the notebooks and creates the job. With `-t dev`, the job is named `[dev <you>] ecommerce_etl` and its schedule stays **paused**.

## Step 2: Create the catalog, schemas and volumes

Open `1_setup/setup_catalog` in the workspace and click **Run all**. It creates:

- Catalog `ecommerce` with the schemas `bronze`, `silver`, `gold` and `source_data`
- Volume `ecommerce.source_data.raw` for the raw CSV files
- Volume `ecommerce.source_data.checkpoints` for the Auto Loader state

## Step 3: Upload the raw data into the volume

The folder layout must match the paths the notebooks read:

```
/Volumes/ecommerce/source_data/raw/
├── brands/brands.csv
├── category/category.csv
├── customers/customers.csv
├── date/date.csv
├── products/products.csv
└── order_items/landing/order_items_2025-08-01.csv ... order_items_2025-10-31.csv
```

**UI:** go to **Catalog → ecommerce → source_data → Volumes → raw**. Use **Create directory** to make each folder above, then **Upload to this volume** to add the files from `0_data/ecomm-raw-data/`.

**CLI** (from the `project_assets` folder):
```bash
databricks fs cp -r 0_data/ecomm-raw-data dbfs:/Volumes/ecommerce/source_data/raw --overwrite
```
Check the result with `databricks fs ls dbfs:/Volumes/ecommerce/source_data/raw/order_items/landing`.

## Step 4: Test each notebook once (optional but recommended)

Run them in this order and check that each finishes without errors:

1. `2_medallion_processing_dim/1_dim_bronze` → `2_dim_silver` → `3_dim_gold`
2. `3_medallion_processing_fact/1_fact_bronze` → `2_fact_silver` → `3_fact_gold`
3. `4_serving/1_create_views`

On its first run, `1_fact_bronze` prints `No checkpoint found, rebuilding ...`. It then loads every file in `landing/`, and its last cell shows the row count per file. If you run it again, it ingests 0 new files, which is expected.

## Step 5: Create the job

**If you used the bundle (Option B)**, the job already exists. Skip to step 6.

**Otherwise, use the UI:**
1. Go to **Jobs & Pipelines → Create → Job** and name it `ecommerce_etl`.
2. Add these tasks. For each one: **Type = Notebook**, **Source = Workspace**, pick the notebook, and set **Compute = Serverless**.

   | Task name | Notebook | Depends on |
   |---|---|---|
   | `setup_catalog` | `1_setup/setup_catalog` | |
   | `dim_bronze` | `2_medallion_processing_dim/1_dim_bronze` | `setup_catalog` |
   | `dim_silver` | `2_medallion_processing_dim/2_dim_silver` | `dim_bronze` |
   | `dim_gold` | `2_medallion_processing_dim/3_dim_gold` | `dim_silver` |
   | `fact_bronze` | `3_medallion_processing_fact/1_fact_bronze` | `setup_catalog` |
   | `fact_silver` | `3_medallion_processing_fact/2_fact_silver` | `fact_bronze` |
   | `fact_gold` | `3_medallion_processing_fact/3_fact_gold` | `fact_silver` |
   | `create_views` | `4_serving/1_create_views` | `dim_gold`, `fact_gold` |

3. In the job settings panel on the right:
   - **Maximum concurrent runs = 1**, so two runs never overwrite the same tables at the same time.
   - **Job notifications → Add → Failure** → your email.
   - Optional: on `fact_bronze`, set **Retries = 1**.

   If serverless isn't available, create one **job cluster** (e.g. a recent LTS runtime with 1–2 workers) and select it for every task.

## Step 6: Do one manual run

Click **Run now** and watch the graph. All 8 tasks should turn green, and the dim and fact branches run in parallel. Then check the output:

```sql
SELECT count(*) FROM ecommerce.gold.gld_fact_order_items;
SELECT * FROM ecommerce.gold.fact_transactions_denorm LIMIT 10;
```

## Step 7: Add the schedule

Pick **one** trigger type.

**A. Time-based (daily)**
- UI: **Schedules & Triggers → Add trigger → Scheduled**. Choose **Advanced**, set the cron to `0 0 6 * * ?` and the timezone to `Asia/Kolkata`, which runs daily at 06:00 IST.
- Bundle: already set in `databricks.yml`. Deploy to prod to activate it: `databricks bundle deploy -t prod`. Dev mode keeps the schedule paused.

**B. File arrival (runs when a new order file is uploaded)**
- UI: **Add trigger → File arrival** → URL `/Volumes/ecommerce/source_data/raw/order_items/landing/`.
- Bundle: replace the `schedule:` block with the commented `trigger: file_arrival:` block in `databricks.yml`, then deploy again.

Make sure the trigger shows as **Active**, not Paused.

---

## Day-to-day operation

- **New orders:** upload each new day's file to `/Volumes/ecommerce/source_data/raw/order_items/landing/` with a **new file name**, e.g. `order_items_2025-11-01.csv`. The next run picks up only that file.
  - Auto Loader does **not** re-ingest a file whose name it has already seen, even if the content changed. To correct a day's data, upload it under a new name (e.g. `order_items_2025-11-01_v2.csv`). Silver deduplicates on `order_id, item_seq`.
- **Dimension changes:** replace `brands.csv`, `products.csv` and so on in their folders. Each run fully reloads the dimensions.
- **Full rebuild of order_items bronze:** delete the folder `/Volumes/ecommerce/source_data/checkpoints/brz_order_items`. On the next run, `1_fact_bronze` drops `brz_order_items` and reloads every file still in `landing/`. Don't delete old files from `landing/` if you might need a rebuild later.
- **Monitoring:** go to **Jobs & Pipelines → ecommerce_etl → Runs** for run history, durations and failed-task output. You get an email when a run fails.
- **FX rates** are hardcoded in `3_medallion_processing_fact/3_fact_gold` (rates as of 2025-10-15). Update that cell when the rates change.

## Test data for daily uploads

`0_data/daily_uploads/` contains generated order files for 2025-11-01 to 2025-11-14. They have the same format and raw quirks as the original data, continue the order IDs, and use only existing customers and products. `date/date.csv` has been extended to 2026-12-31 so the new dates join in the dashboard view.

1. **One time:** upload the extended date file:
   ```bash
   databricks fs cp 0_data/ecomm-raw-data/date/date.csv dbfs:/Volumes/ecommerce/source_data/raw/date/date.csv --overwrite
   ```
2. **Each day:** upload the next file before 06:00 IST:
   ```bash
   databricks fs cp 0_data/daily_uploads/order_items_2025-11-01.csv dbfs:/Volumes/ecommerce/source_data/raw/order_items/landing/
   ```
3. **Check after the run:**
   ```sql
   SELECT transaction_date, count(*) FROM ecommerce.gold.fact_transactions_denorm
   WHERE transaction_date >= '2025-11-01' GROUP BY 1 ORDER BY 1;
   ```
4. **More files:** `python3 tools/generate_daily_orders.py --days 7` creates the next 7 days after the latest file.

## Troubleshooting

| Error | Cause / fix |
|---|---|
| `PATH_NOT_FOUND` / `[UNABLE_TO_INFER_SCHEMA]` in a bronze notebook | The files aren't in the expected folder. Recheck step 3. |
| `PERMISSION_DENIED: CREATE CATALOG` | Ask an admin to create the `ecommerce` catalog, or remove the `setup_catalog` task after the first run (also remove it from `depends_on`). |
| `create_views` fails with `TABLE_OR_VIEW_NOT_FOUND` | One of the gold tasks failed. Fix that task, then use **Repair run**. |
