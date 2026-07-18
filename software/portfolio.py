"""
Persist saved loan structures for the Portfolio tab.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

import pandas as pd

PORTFOLIO_FILE = "portfolio.json"


def _empty_store() -> dict[str, Any]:
    return {"loans": {}}


def load_portfolio(path: str = PORTFOLIO_FILE) -> dict[str, Any]:
    if not os.path.exists(path):
        return _empty_store()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict) or "loans" not in data:
        return _empty_store()
    return data


def save_portfolio(data: dict[str, Any], path: str = PORTFOLIO_FILE) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def loan_exists(loan_number: str, path: str = PORTFOLIO_FILE) -> bool:
    return loan_number in load_portfolio(path)["loans"]


def get_loan(loan_number: str, path: str = PORTFOLIO_FILE) -> Optional[dict[str, Any]]:
    return load_portfolio(path)["loans"].get(loan_number)


def delete_loan(loan_number: str, path: str = PORTFOLIO_FILE) -> bool:
    data = load_portfolio(path)
    if loan_number not in data["loans"]:
        return False
    del data["loans"][loan_number]
    save_portfolio(data, path)
    return True


def save_loan_snapshot(
    loan_number: str,
    *,
    client: str,
    fee_rate_pct: float,
    as_of_date: str,
    loan_structure: pd.DataFrame,
    cashflow: pd.DataFrame,
    summary: dict[str, Any],
    path: str = PORTFOLIO_FILE,
) -> dict[str, Any]:
    data = load_portfolio(path)
    record = {
        "loan_number": loan_number,
        "client": client,
        "saved_at": datetime.now().isoformat(),
        "fee_rate_pct": fee_rate_pct,
        "as_of_date": as_of_date,
        "loan_structure": loan_structure.to_dict("records"),
        "cashflow": cashflow.to_dict("records"),
        "summary": summary,
    }
    data["loans"][loan_number] = record
    save_portfolio(data, path)
    return record


def list_loans_table(path: str = PORTFOLIO_FILE) -> pd.DataFrame:
    """One row per saved loan for the Portfolio summary table."""
    loans = load_portfolio(path)["loans"]
    if not loans:
        return pd.DataFrame(
            columns=[
                "Loan #",
                "Client",
                "Saved",
                "Total Box Amount",
                "Wtd Avg Rate",
                "Wtd Avg APR",
                "Wtd Avg DTE",
                "Total Funded",
                "Total Fees",
                "Net Proceeds",
            ]
        )

    rows = []
    for loan_number in sorted(loans.keys(), key=_loan_sort_key):
        loan = loans[loan_number]
        summary = loan.get("summary", {})
        saved_at = loan.get("saved_at", "")
        saved_display = ""
        if saved_at:
            try:
                saved_display = datetime.fromisoformat(saved_at).strftime("%Y-%m-%d %I:%M %p")
            except ValueError:
                saved_display = saved_at

        rows.append(
            {
                "Loan #": loan_number,
                "Client": loan.get("client", ""),
                "Saved": saved_display,
                "Total Box Amount": summary.get("total_box_amount", 0.0),
                "Wtd Avg Rate": summary.get("weighted_avg_rate", 0.0),
                "Wtd Avg APR": summary.get("weighted_avg_apr", 0.0),
                "Wtd Avg DTE": summary.get("weighted_avg_dte", 0.0),
                "Total Funded": summary.get("total_funded", 0.0),
                "Total Fees": summary.get("total_fees", 0.0),
                "Net Proceeds": summary.get("net_proceeds", 0.0),
            }
        )
    return pd.DataFrame(rows)


def _loan_sort_key(loan_number: str):
    try:
        return (0, int(loan_number))
    except ValueError:
        return (1, loan_number.lower())


def aggregate_cashflows(path: str = PORTFOLIO_FILE) -> pd.DataFrame:
    """Sum cashflow amounts by date across all portfolio loans."""
    loans = load_portfolio(path)["loans"]
    if not loans:
        return pd.DataFrame(columns=["Date", "Amount ($)"])

    totals_by_date: dict[str, float] = {}
    for loan in loans.values():
        for row in loan.get("cashflow", []):
            date = row["Date"]
            totals_by_date[date] = totals_by_date.get(date, 0.0) + float(row["Amount ($)"])

    return pd.DataFrame(
        [{"Date": date, "Amount ($)": round(totals_by_date[date], 2)}
         for date in sorted(totals_by_date)]
    )


def aggregate_loan_structures(path: str = PORTFOLIO_FILE) -> pd.DataFrame:
    """Combine loan structure rows from every saved loan."""
    loans = load_portfolio(path)["loans"]
    frames = [pd.DataFrame(loan["loan_structure"]) for loan in loans.values() if loan.get("loan_structure")]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def aggregate_fee_rate_pct(path: str = PORTFOLIO_FILE) -> float:
    """Box-amount-weighted average fee rate across portfolio loans."""
    loans = load_portfolio(path)["loans"]
    weighted_sum = 0.0
    weight_total = 0.0
    for loan in loans.values():
        box_amount = loan.get("summary", {}).get("total_box_amount", 0.0)
        if box_amount > 0:
            weighted_sum += loan.get("fee_rate_pct", 0.0) * box_amount
            weight_total += box_amount
    return weighted_sum / weight_total if weight_total > 0 else 0.0
