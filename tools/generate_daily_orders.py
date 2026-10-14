"""Generate daily order_items CSV files for testing the scheduled ETL pipeline.

Files look like the ones in 0_data/ecomm-raw-data/order_items/landing/ (same columns,
same raw quirks such as "Two" quantities, "$" prices and "%" discounts) and only use
customer and product IDs that exist in the dimension files.

Usage (from the project_assets folder):
    python3 tools/generate_daily_orders.py                      # next day after the latest file
    python3 tools/generate_daily_orders.py --days 14            # next 14 days
    python3 tools/generate_daily_orders.py --start 2025-11-20 --days 3
"""
import argparse
import csv
import datetime as dt
import glob
import math
import os
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "0_data", "ecomm-raw-data")
LANDING_DIR = os.path.join(RAW_DIR, "order_items", "landing")
DEFAULT_OUT = os.path.join(ROOT, "0_data", "daily_uploads")

COLUMNS = ["dt", "order_ts", "customer_id", "order_id", "item_seq", "product_id", "quantity",
           "unit_price_currency", "unit_price", "discount_pct", "tax_amount", "channel", "coupon_code"]

CURRENCY_BY_COUNTRY = {
    "India": "INR", "United States": "USD", "United Kingdom": "GBP", "United Arab Emirates": "AED",
    "Singapore": "SGD", "Canada": "CAD", "Australia": "AUD",
}
# Same INR rates as 3_fact_gold, used to keep prices realistic per currency
INR_PER_UNIT = {"INR": 1.0, "AED": 24.18, "AUD": 57.55, "CAD": 62.93, "GBP": 117.98, "SGD": 68.18, "USD": 88.29}

ITEMS_PER_ORDER = ([1, 2, 3, 4, 5], [55, 25, 12, 6, 2])
QUANTITY = (["1", "Two", "3", "4"], [75, 18, 5, 2])
CHANNEL = (["app", "web"], [55, 45])
COUPON = (["", "FEST20", "PRIME5", "NEW10", "SAVE50"], [65, 12, 10, 8, 5])
TAX_RATE = [0.05, 0.10, 0.12, 0.18]


def load_ids():
    with open(os.path.join(RAW_DIR, "customers", "customers.csv"), newline="") as fh:
        customers = [(r["customer_id"], r["country"]) for r in csv.DictReader(fh)
                     if r["customer_id"] and r["country"] in CURRENCY_BY_COUNTRY]
    with open(os.path.join(RAW_DIR, "products", "products.csv"), newline="") as fh:
        products = [r["product_id"] for r in csv.DictReader(fh) if r["product_id"]]
    with open(os.path.join(RAW_DIR, "date", "date.csv"), newline="") as fh:
        dates = {r["date"] for r in csv.DictReader(fh)}
    return customers, products, dates


def existing_files(out_dir):
    return glob.glob(os.path.join(LANDING_DIR, "order_items_*.csv")) + \
        glob.glob(os.path.join(out_dir, "order_items_*.csv"))


def max_order_id(files):
    max_id = 0
    for f in files:
        with open(f, newline="") as fh:
            for r in csv.DictReader(fh):
                if r["order_id"].isdigit():
                    max_id = max(max_id, int(r["order_id"]))
    return max_id


def latest_date(files):
    days = [os.path.basename(f)[len("order_items_"):-len(".csv")] for f in files]
    return max(dt.date.fromisoformat(d) for d in days)


def pick(rng, choices):
    return rng.choices(choices[0], weights=choices[1])[0]


def generate_day(day, customers, products, next_order_id):
    rng = random.Random(day.isoformat())
    target_rows = rng.randint(1200, 3600)
    rows = []
    while len(rows) < target_rows:
        customer_id, country = rng.choice(customers)
        currency = CURRENCY_BY_COUNTRY[country]
        channel, coupon = pick(rng, CHANNEL), pick(rng, COUPON)
        ts = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=rng.randrange(86400))
        for item_seq in range(1, pick(rng, ITEMS_PER_ORDER) + 1):
            quantity = pick(rng, QUANTITY)
            price_inr = min(max(rng.lognormvariate(math.log(3400), 1.2), 99), 150000)
            price = max(1, round(price_inr / INR_PER_UNIT[currency]))
            discount = 0 if rng.random() < 0.17 else rng.randint(1, 30)
            qty = 2 if quantity == "Two" else int(quantity)
            tax = round(price * qty * (1 - discount / 100) * rng.choice(TAX_RATE))
            rows.append([
                day.isoformat(), ts.strftime("%Y-%m-%d %H:%M:%S"), customer_id, next_order_id, item_seq,
                rng.choice(products), quantity, currency,
                f"${price}" if currency == "USD" else price, f"{discount}%", tax, channel, coupon,
            ])
        next_order_id += 1
    return rows, next_order_id


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=dt.date.fromisoformat, help="first date (YYYY-MM-DD); default: day after the latest existing file")
    parser.add_argument("--days", type=int, default=1, help="number of daily files to create (default 1)")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    files = existing_files(args.out)
    start = args.start or latest_date(files) + dt.timedelta(days=1)
    customers, products, dates = load_ids()
    next_order_id = max_order_id(files) + 1

    for i in range(args.days):
        day = start + dt.timedelta(days=i)
        path = os.path.join(args.out, f"order_items_{day.isoformat()}.csv")
        if os.path.exists(path):
            print(f"skip   {path} (already exists)")
            continue
        if day.strftime("%d-%m-%Y") not in dates:
            print(f"WARNING {day} is not in date/date.csv; these orders won't appear in fact_transactions_denorm")
        rows, next_order_id = generate_day(day, customers, products, next_order_id)
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            writer.writerows(rows)
        print(f"wrote  {path} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
