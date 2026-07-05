"""
Remove expired maturity dates from yield data.

Any maturity date before today is dropped — e.g. on 2026-06-19 there should
be no 2026-01-15 row because that tenor has already expired.
"""

import argparse
import json
import os
from datetime import date, datetime

import pandas as pd

DEFAULT_CACHE = "yield_data_cache.json"


def remove_expired_maturities(df, as_of=None):
    """Drop rows whose maturity date is strictly before as_of (default: today)."""
    if df.empty:
        return df

    if as_of is None:
        as_of = datetime.now().date()
    elif isinstance(as_of, datetime):
        as_of = as_of.date()
    elif isinstance(as_of, pd.Timestamp):
        as_of = as_of.date()

    df = df.copy()
    df["Maturity Date"] = pd.to_datetime(df["Maturity Date"])
    df = df[df["Maturity Date"].dt.date >= as_of]
    return df.sort_values("Maturity Date").reset_index(drop=True)


def load_cache(cache_path):
    if not os.path.exists(cache_path):
        return pd.DataFrame(columns=["Maturity Date", "Effective Yield"])

    with open(cache_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = raw.get("records", [])
    else:
        return pd.DataFrame(columns=["Maturity Date", "Effective Yield"])

    return pd.DataFrame(records)


def save_cache(df, cache_path):
    df_cache = df.copy()
    df_cache["Maturity Date"] = df_cache["Maturity Date"].dt.strftime("%Y-%m-%d")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump({"records": df_cache.to_dict("records")}, f)


def update_cache_file(cache_path=DEFAULT_CACHE, as_of=None, dry_run=False):
    """Load cache, remove expired maturities, and save unless dry_run."""
    df = load_cache(cache_path)
    if df.empty:
        return df, []

    df["Maturity Date"] = pd.to_datetime(df["Maturity Date"])
    expired = df[df["Maturity Date"].dt.date < (as_of or datetime.now().date())]
    removed = [
        {
            "Maturity Date": row["Maturity Date"].strftime("%Y-%m-%d"),
            "Effective Yield": row["Effective Yield"],
        }
        for _, row in expired.iterrows()
    ]

    updated = remove_expired_maturities(df, as_of=as_of)
    if not dry_run and len(removed) > 0:
        save_cache(updated, cache_path)

    return updated, removed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Remove expired maturity dates from yield_data_cache.json"
    )
    parser.add_argument(
        "--cache",
        default=DEFAULT_CACHE,
        help=f"Path to cache JSON (default: {DEFAULT_CACHE})",
    )
    parser.add_argument(
        "--as-of",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="Reference date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without writing the cache file",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    as_of = args.as_of or datetime.now().date()

    if not os.path.exists(args.cache):
        print(f"Cache file not found: {args.cache}")
        return 1

    updated, removed = update_cache_file(
        cache_path=args.cache, as_of=as_of, dry_run=args.dry_run
    )

    print(f"As of {as_of.isoformat()}:")
    if removed:
        print(f"\nRemoved {len(removed)} expired maturity date(s):")
        for row in removed:
            print(f"  - {row['Maturity Date']} ({row['Effective Yield']:.4f}%)")
    else:
        print("\nNo expired maturity dates found.")

    print(f"\nRemaining rows: {len(updated)}")
    if args.dry_run and removed:
        print("(dry run — cache file not modified)")
    elif removed:
        print(f"Updated {args.cache}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
