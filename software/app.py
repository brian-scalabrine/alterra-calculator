"""
Streamlit app to visualize boxtrades.com maturity date and effective yield data.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
from data_refresh import (
    format_last_refreshed,
    refresh_yield_data,
)
from portfolio import (
    aggregate_cashflows,
    aggregate_fee_rate_pct,
    aggregate_loan_structures,
    delete_loan,
    get_loan,
    list_loans_table,
    loan_exists,
    save_loan_snapshot,
)


def round_currency(value):
    """Round monetary values to 2 decimal places for consistent display."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0.0
    return round(float(value), 2)


def monetary_column(label, *, disabled=False, min_value=None, step=0.01):
    """Shared column config for dollar amounts ($1,234.56)."""
    kwargs = {"format": "dollar", "step": step}
    if disabled:
        kwargs["disabled"] = True
    if min_value is not None:
        kwargs["min_value"] = min_value
    return st.column_config.NumberColumn(label, **kwargs)


DEFAULT_FEE_RATE_PCT = 0.50


def get_annual_fee_rate():
    """Annual fee as a decimal (e.g. 0.005 for 0.50%)."""
    return st.session_state.get("fee_rate_pct", DEFAULT_FEE_RATE_PCT) / 100.0


def fee_methodology_note(fee_rate_pct):
    return (
        f"* Upfront fee deducted at funding: {fee_rate_pct:.2f}% annualized × "
        "(days to maturity ÷ 365, actual/365) × gross funded amount, per box spread. "
        "Net proceeds = gross funded − fee."
    )


def summary_stats_footnotes(fee_rate_pct):
    """Footnotes for summary stats marked with an asterisk."""
    return (
        "* Wtd Avg Rate: Σ(Rate × DTE × Box Amount) ÷ Σ(DTE × Box Amount), "
        "rows with Box Amount > 0 only.\n\n"
        "* Wtd Avg APR: Wtd Avg Rate + Annual Fee Rate "
        f"({fee_rate_pct:.2f}%).\n\n"
        "* Wtd Avg DTE: Σ(DTE × Box Amount) ÷ Σ(Box Amount), "
        "rows with Box Amount > 0 only.\n\n"
        f"* Total Fees: Sum of upfront fees per row (Annual Fee Rate {fee_rate_pct:.2f}% "
        "× DTE ÷ 365 × Funded Amount)."
    )


def compute_loan_summary_stats(loan_df, fee_rate_pct):
    """Build summary stat cards from the loan structure table."""
    summary = compute_loan_summary_dict(loan_df, fee_rate_pct)
    return [
        ("Total Box Amount", f"${summary['total_box_amount']:,.0f}"),
        ("Wtd Avg Rate*", f"{summary['weighted_avg_rate']:.2f}%"),
        ("Wtd Avg APR*", f"{summary['weighted_avg_apr']:.2f}%"),
        ("Wtd Avg DTE*", f"{summary['weighted_avg_dte']:.0f}"),
        ("Total Funded", f"${summary['total_funded']:,.0f}"),
        ("Total Fees*", f"${summary['total_fees']:,.0f}"),
        ("Net Proceeds", f"${summary['net_proceeds']:,.0f}"),
    ]


def compute_loan_summary_dict(loan_df, fee_rate_pct):
    """Numeric summary fields for portfolio storage."""
    total_box_amount = float(loan_df["Box Amount ($)"].sum())
    non_zero_df = loan_df[loan_df["Box Amount ($)"] > 0]

    if len(non_zero_df) > 0:
        weighted_sum_rate = (
            non_zero_df["Rate (%)"] * non_zero_df["DTE"] * non_zero_df["Box Amount ($)"]
        ).sum()
        weight_total = (non_zero_df["DTE"] * non_zero_df["Box Amount ($)"]).sum()
        weighted_avg_rate = weighted_sum_rate / weight_total if weight_total > 0 else 0.0

        weighted_sum_dte = (non_zero_df["DTE"] * non_zero_df["Box Amount ($)"]).sum()
        box_total = non_zero_df["Box Amount ($)"].sum()
        weighted_avg_dte = weighted_sum_dte / box_total if box_total > 0 else 0.0
    else:
        weighted_avg_rate = 0.0
        weighted_avg_dte = 0.0

    return {
        "total_box_amount": total_box_amount,
        "weighted_avg_rate": float(weighted_avg_rate),
        "weighted_avg_apr": float(weighted_avg_rate + fee_rate_pct),
        "weighted_avg_dte": float(weighted_avg_dte),
        "total_funded": float(loan_df["Funded Amount ($)"].sum()),
        "total_fees": float(loan_df["Fee ($)"].sum()),
        "net_proceeds": float(loan_df["Net Proceeds ($)"].sum()),
    }


def calculate_gross_funded(loan_amount, rate_pct, dte):
    """Gross funded amount before upfront fee."""
    if loan_amount > 0 and rate_pct > 0 and dte > 0:
        rate_decimal = rate_pct / 100.0
        discount_factor = np.exp(rate_decimal * (dte / 360.0))
        return round_currency(loan_amount / discount_factor)
    return 0.0


def calculate_upfront_fee(funded_amount, dte, annual_fee_rate=None):
    """Upfront fee scaled by actual/365 days to maturity."""
    if annual_fee_rate is None:
        annual_fee_rate = get_annual_fee_rate()
    if funded_amount > 0 and dte > 0:
        return round_currency(annual_fee_rate * (dte / 365.0) * funded_amount)
    return 0.0


def calculate_net_proceeds(funded_amount, dte, annual_fee_rate=None):
    """Cash to borrower after upfront fee."""
    fee = calculate_upfront_fee(funded_amount, dte, annual_fee_rate)
    return round_currency(funded_amount - fee)


def build_loan_dataframe(df, loan_inputs, today, fee_rate_pct=None):
    """Build the full loan table from session-state box amounts."""
    loan_data = []
    if fee_rate_pct is None:
        annual_fee_rate = get_annual_fee_rate()
    else:
        annual_fee_rate = fee_rate_pct / 100.0
    for _, row in df.iterrows():
        maturity_date = (
            row['Maturity Date'].date()
            if hasattr(row['Maturity Date'], 'date')
            else pd.to_datetime(row['Maturity Date']).date()
        )
        date_str = maturity_date.strftime('%Y-%m-%d')
        effective_yield = row['Effective Yield']
        loan_amount = round_currency(loan_inputs.get(date_str, 0.0))
        dte = (maturity_date - today).days
        funded_amount = calculate_gross_funded(loan_amount, effective_yield, dte)
        upfront_fee = calculate_upfront_fee(funded_amount, dte, annual_fee_rate)
        net_proceeds = calculate_net_proceeds(funded_amount, dte, annual_fee_rate)
        loan_data.append({
            'Maturity Date': date_str,
            'Box Amount ($)': loan_amount,
            'DTE': int(dte),
            'Rate (%)': effective_yield,
            'Funded Amount ($)': funded_amount,
            'Fee ($)': upfront_fee,
            'Net Proceeds ($)': net_proceeds,
        })
    return pd.DataFrame(loan_data)


def build_cashflow_schedule(loan_df, today):
    """Build cashflow schedule DataFrame from a loan structure table."""
    cashflow_data = []
    maturity_dates = []
    net_proceeds_by_date = {}
    loan_amounts_by_date = {}

    for _, row in loan_df.iterrows():
        if row["Box Amount ($)"] > 0:
            mat_date = pd.to_datetime(row["Maturity Date"]).date()
            maturity_dates.append(mat_date)
            net_proceeds_by_date[mat_date] = row["Net Proceeds ($)"]
            loan_amounts_by_date[mat_date] = row["Box Amount ($)"]

    total_net_proceeds_cf = sum(net_proceeds_by_date.values())

    all_dates = [today]
    end_date = max(maturity_dates) if maturity_dates else today + timedelta(days=365 * 5)
    current_date = today
    while current_date <= end_date:
        if current_date.month == 12:
            first_of_month = datetime(current_date.year + 1, 1, 1).date()
        else:
            first_of_month = datetime(current_date.year, current_date.month + 1, 1).date()
        if first_of_month not in all_dates:
            all_dates.append(first_of_month)
        current_date = first_of_month

    for mat_date in maturity_dates:
        if mat_date not in all_dates:
            all_dates.append(mat_date)

    all_dates.sort()

    for date in all_dates:
        if date == today:
            amount = round_currency(total_net_proceeds_cf)
        elif date in loan_amounts_by_date:
            amount = round_currency(-loan_amounts_by_date[date])
        else:
            amount = 0.0

        cashflow_data.append({
            "Date": date.strftime("%Y-%m-%d"),
            "Amount ($)": amount,
        })

    return pd.DataFrame(cashflow_data)


def render_cashflow_panel(cashflow_df, fee_rate_pct, *, chart_height=400, table_height=800):
    """Display cashflow table, chart, and fee methodology note."""
    st.dataframe(
        cashflow_df,
        column_config={
            "Date": st.column_config.TextColumn("Date", disabled=True, width="small"),
            "Amount ($)": monetary_column("Amount ($)", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        height=table_height,
    )

    dates = [pd.to_datetime(d) for d in cashflow_df["Date"]]
    amounts = cashflow_df["Amount ($)"].tolist()
    colors = [
        "#5EFFAF" if a > 0 else "#E57373" if a < 0 else "#B0BEC5"
        for a in amounts
    ]

    fig_cashflow = go.Figure()
    fig_cashflow.add_trace(go.Bar(
        x=dates,
        y=amounts,
        marker_color=colors,
        name="Cashflow",
    ))
    fig_cashflow.update_layout(
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        height=chart_height,
        showlegend=False,
        **alterra_chart_layout(title="Cashflow Schedule*"),
        xaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(10,22,20,0.08)"),
        yaxis=dict(showgrid=True, gridwidth=1, gridcolor="rgba(10,22,20,0.08)"),
    )
    st.plotly_chart(fig_cashflow, use_container_width=True)
    st.caption(fee_methodology_note(fee_rate_pct))


def persist_loan_to_portfolio(loan_number, client, loan_df, cashflow_df, fee_rate_pct, as_of_date):
    """Save a loan structure snapshot to the portfolio."""
    save_loan_snapshot(
        loan_number,
        client=client.strip(),
        fee_rate_pct=fee_rate_pct,
        as_of_date=as_of_date.isoformat(),
        loan_structure=loan_df,
        cashflow=cashflow_df,
        summary=compute_loan_summary_dict(loan_df, fee_rate_pct),
    )


def parse_loan_number(loan_number_input):
    """
    Validate Loan # as a positive integer string (no decimals).
    Returns (loan_number_str, error_message).
    """
    if loan_number_input is None:
        return None, "Enter a Loan # before saving."

    if isinstance(loan_number_input, float):
        if not loan_number_input.is_integer():
            return None, "Loan # must be a whole number (no decimals)."
        loan_number_input = int(loan_number_input)
    elif isinstance(loan_number_input, str):
        loan_number_input = loan_number_input.strip()
        if not loan_number_input:
            return None, "Enter a Loan # before saving."
        if "." in loan_number_input:
            return None, "Loan # must be a whole number (no decimals)."
        try:
            loan_number_input = int(loan_number_input)
        except ValueError:
            return None, "Loan # must be a whole number."
    elif isinstance(loan_number_input, int):
        pass
    else:
        return None, "Loan # must be a whole number."

    if loan_number_input < 1:
        return None, "Loan # must be a positive whole number."

    return str(loan_number_input), None


ALTERRA_TITLE_FONT = "Bodoni MT, Libre Bodoni, serif"
ALTERRA_CHART_LAYOUT = dict(
    paper_bgcolor="#FFFFFF",
    plot_bgcolor="#FFFFFF",
    font=dict(family="DM Sans, sans-serif", color="#1a2e2a", size=12),
)


def alterra_chart_layout(*, title=None):
    """Plotly layout defaults; only include title_font when a title is set."""
    layout = dict(ALTERRA_CHART_LAYOUT)
    if title:
        layout["title"] = title
        layout["title_font"] = dict(
            family=ALTERRA_TITLE_FONT, color="#0a1614", size=16
        )
    return layout


def alterra_brand_title_html(*, sidebar=False):
    """Brand wordmark: Bodoni MT, all lowercase."""
    size = "1.35rem" if sidebar else "1.75rem"
    margin = "margin: 0 0 0.5rem 0;" if sidebar else "margin: 0 0 1rem 0;"
    return (
        f'<p class="alterra-brand-title" style="font-size: {size}; {margin}">'
        "alterra</p>"
    )


def render_summary_stats(stats):
    """Render a row of summary stat cards. stats: list of (label, value) tuples."""
    cards = "".join(
        f'<div class="summary-stat">'
        f'<div class="summary-stat-label">{label}</div>'
        f'<div class="summary-stat-value">{value}</div>'
        f'</div>'
        for label, value in stats
    )
    st.markdown(f'<div class="summary-stats-row">{cards}</div>', unsafe_allow_html=True)


@st.dialog("Delete from Portfolio")
def portfolio_delete_dialog(loan_number: str):
    """Confirm loan deletion in a modal popup."""
    st.markdown(
        f"Delete Loan **#{loan_number}** from the Portfolio? "
        "This cannot be undone."
    )
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(
            "Yes, delete loan",
            type="primary",
            use_container_width=True,
            key=f"dialog_confirm_delete_{loan_number}",
        ):
            delete_loan(loan_number)
            st.session_state.portfolio_delete_message = (
                f"Loan #{loan_number} removed from Portfolio."
            )
            st.rerun()
    with cancel_col:
        if st.button(
            "Cancel",
            use_container_width=True,
            key=f"dialog_cancel_delete_{loan_number}",
        ):
            st.rerun()


def render_portfolio_table(portfolio_df):
    """Render portfolio loans as a table with a delete button on each row."""
    st.markdown(
        """
        <style>
            .portfolio-table-header {
                font-size: 0.72rem;
                font-weight: 600;
                color: #4a635e;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                padding: 8px 4px;
                border-bottom: 1px solid rgba(10, 22, 20, 0.12);
            }
            .portfolio-table-cell {
                font-size: 0.82rem;
                color: #1a2e2a;
                padding: 10px 4px;
                border-bottom: 1px solid rgba(10, 22, 20, 0.06);
                font-variant-numeric: tabular-nums;
            }
            [class*="st-key-portfolio_delete_"] button[kind="secondary"] {
                background-color: #C62828 !important;
                color: #FFFFFF !important;
                border-color: #C62828 !important;
                font-size: 0.72rem !important;
                padding: 0.1rem 0.5rem !important;
                min-height: 1.35rem !important;
                height: 1.35rem !important;
            }
            [class*="st-key-portfolio_delete_"] button[kind="secondary"]:hover {
                background-color: #B71C1C !important;
                border-color: #B71C1C !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col_widths = [0.55, 1.0, 1.15, 1.05, 0.85, 0.85, 0.7, 0.95, 0.85, 0.95, 0.55]
    headers = [
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
        "",
    ]

    header_cols = st.columns(col_widths)
    for col, label in zip(header_cols, headers):
        col.markdown(f'<div class="portfolio-table-header">{label}</div>', unsafe_allow_html=True)

    for _, row in portfolio_df.iterrows():
        loan_number = str(row["Loan #"])
        row_cols = st.columns(col_widths)
        values = [
            loan_number,
            row.get("Client", "") or "—",
            row.get("Saved", ""),
            f"${row['Total Box Amount']:,.0f}",
            f"{row['Wtd Avg Rate']:.2f}%",
            f"{row['Wtd Avg APR']:.2f}%",
            f"{int(row['Wtd Avg DTE'])}",
            f"${row['Total Funded']:,.0f}",
            f"${row['Total Fees']:,.0f}",
            f"${row['Net Proceeds']:,.0f}",
        ]

        for col, value in zip(row_cols[:-1], values):
            col.markdown(f'<div class="portfolio-table-cell">{value}</div>', unsafe_allow_html=True)

        with row_cols[-1]:
            if st.button("Delete", key=f"portfolio_delete_{loan_number}", use_container_width=True):
                portfolio_delete_dialog(loan_number)

# Page configuration
st.set_page_config(
    page_title="Alterra",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)


def get_refresh_settings():
    """Read optional refresh schedule overrides from Streamlit secrets."""
    return {
        "tz_name": st.secrets.get("refresh_timezone", "America/New_York"),
        "hour": int(st.secrets.get("refresh_hour", 15)),
        "minute": int(st.secrets.get("refresh_minute", 0)),
    }


def require_auth():
    """Simple password gate when app_password is configured in secrets."""
    configured_password = st.secrets.get("app_password")
    if not configured_password:
        return

    if st.session_state.get("authenticated"):
        return

    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { visibility: hidden; }
            [data-testid="stSidebar"] + div { margin-left: 0; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(alterra_brand_title_html(), unsafe_allow_html=True)
    st.caption("Sign in to access the lending calculator.")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Sign in", type="primary"):
        if password == configured_password:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


require_auth()


def init_loan_inputs_from_df(df):
    """Ensure loan_inputs has an entry for each maturity date in df."""
    if "loan_inputs" not in st.session_state:
        st.session_state.loan_inputs = {}
    for _, row in df.iterrows():
        date_str = row["Maturity Date"].strftime("%Y-%m-%d")
        if date_str not in st.session_state.loan_inputs:
            st.session_state.loan_inputs[date_str] = 0.0

# Initialize session state for data (auto-refresh once daily after 3 PM ET when due)
if "yield_data" not in st.session_state:
    refresh_settings = get_refresh_settings()
    df, _, last_refreshed_at, refresh_error = refresh_yield_data(**refresh_settings)
    st.session_state.yield_data = df
    st.session_state.last_refreshed_at = last_refreshed_at
    if refresh_error:
        st.session_state.data_refresh_error = refresh_error
    if not df.empty:
        init_loan_inputs_from_df(df)

# Initialize session state for loan inputs
if "loan_inputs" not in st.session_state:
    st.session_state.loan_inputs = {}

# Initialize current page in session state
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Loan Structure"

if 'fee_rate_pct' not in st.session_state:
    st.session_state.fee_rate_pct = DEFAULT_FEE_RATE_PCT

if "portfolio_overwrite_loan" not in st.session_state:
    st.session_state.portfolio_overwrite_loan = None

# Alterra brand styling (meetalterra.com)
st.markdown("""
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,700;1,400&family=Libre+Bodoni:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
    :root {
        --alterra-bg: #FFFFFF;
        --alterra-accent: #5EFFAF;
        --alterra-dark: #0a1614;
        --alterra-text: #1a2e2a;
        --alterra-muted: #4a635e;
        --alterra-input: #BFDBFE;
        --alterra-input-border: #2563EB;
        --alterra-card: #FFFFFF;
        --alterra-title-font: 'Bodoni MT', 'Libre Bodoni', serif;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        color: var(--alterra-text);
    }

    .stApp {
        background-color: var(--alterra-bg);
    }

    .main .block-container {
        font-size: 0.9rem;
        padding-top: 1.5rem;
    }

    h1, h2, h3,
    [data-testid="stSidebar"] h1 {
        font-family: var(--alterra-title-font) !important;
        color: var(--alterra-dark) !important;
        font-weight: 700 !important;
    }

    .alterra-brand-title {
        font-family: var(--alterra-title-font) !important;
        color: var(--alterra-dark) !important;
        font-weight: 700 !important;
        text-transform: lowercase !important;
    }

    h1 { font-size: 1.75rem !important; }
    h2, h3 { font-size: 1.15rem !important; }
    [data-testid="stSidebar"] h1 { font-size: 1.35rem !important; }

    [data-testid="stCaptionContainer"] {
        font-size: 0.8rem;
        color: var(--alterra-muted);
    }

    [data-testid="stDataEditor"],
    [data-testid="stDataFrame"] {
        font-size: 0.82rem;
    }

    [data-testid="stSidebar"] {
        background-color: var(--alterra-card);
        border-right: 1px solid rgba(10, 22, 20, 0.08);
    }

    .stButton > button {
        font-family: 'DM Sans', sans-serif;
        border-color: rgba(10, 22, 20, 0.15);
        color: var(--alterra-dark);
        background: var(--alterra-card);
        font-size: 0.85rem;
        border-radius: 6px;
    }

    .stButton > button[kind="primary"] {
        background-color: var(--alterra-dark);
        color: #FFFFFF;
        border-color: var(--alterra-dark);
    }

    .stButton > button[kind="primary"]:hover {
        background-color: #16302c;
        border-color: #16302c;
    }

    [data-testid="stNumberInput"] label,
    [data-testid="stTextInput"] label {
        font-family: 'DM Sans', sans-serif;
        color: var(--alterra-dark);
        font-weight: 500;
    }

    /* Visible borders for text/number input boxes */
    [data-testid="stTextInput"] [data-baseweb="input"],
    [data-testid="stTextInput"] [data-baseweb="base-input"],
    [data-testid="stNumberInput"] [data-baseweb="input"],
    [data-testid="stNumberInput"] [data-baseweb="base-input"] {
        border: 1px solid rgba(10, 22, 20, 0.35) !important;
        border-radius: 6px !important;
        background-color: #FFFFFF !important;
    }

    [data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
    [data-testid="stNumberInput"] [data-baseweb="input"]:focus-within {
        border-color: var(--alterra-input-border) !important;
        box-shadow: 0 0 0 1px var(--alterra-input-border) !important;
    }

    /* Summary stats bar */
    .summary-stats-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 14px 0;
        padding: 12px 14px;
        background: var(--alterra-card);
        border: 1px solid rgba(10, 22, 20, 0.1);
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(10, 22, 20, 0.06);
    }

    .summary-stat {
        flex: 1 1 120px;
        min-width: 110px;
        padding: 10px 12px;
        background: #F8F9FA;
        border-radius: 8px;
        border: 1px solid rgba(94, 255, 175, 0.45);
        text-align: center;
    }

    .summary-stat-label {
        font-size: 0.65rem;
        font-weight: 600;
        color: var(--alterra-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 4px;
        line-height: 1.2;
    }

    .summary-stat-value {
        font-family: 'DM Sans', sans-serif;
        font-size: 1.05rem;
        font-weight: 700;
        color: var(--alterra-dark);
        line-height: 1.25;
        font-variant-numeric: tabular-nums;
    }

    .loan-input-callout {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
        padding: 6px 12px;
        background: #EFF6FF;
        border: 1px solid var(--alterra-input-border);
        border-radius: 6px;
        font-size: 0.8rem;
        color: #1E3A8A;
        font-weight: 500;
    }

    .loan-input-callout span {
        display: inline-block;
        padding: 2px 8px;
        background: var(--alterra-input-border);
        color: white;
        border-radius: 4px;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    /* Box Amount column highlight (2nd column; canvas grid uses background overlay) */
    [data-testid="stDataEditor"] {
        position: relative;
        border-radius: 8px;
        overflow: hidden;
        background: linear-gradient(
            90deg,
            #FFFFFF 0%,
            #FFFFFF 17%,
            rgba(191, 219, 254, 0.55) 17%,
            rgba(191, 219, 254, 0.55) 31%,
            #FFFFFF 31%,
            #FFFFFF 100%
        );
    }

    [data-testid="stDataEditor"]::after {
        content: "";
        position: absolute;
        top: 0;
        bottom: 0;
        left: 17%;
        width: 14%;
        border: 2px solid var(--alterra-input-border);
        border-radius: 4px;
        pointer-events: none;
        z-index: 2;
        box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.5);
    }
</style>
""", unsafe_allow_html=True)

# Navigation sidebar
with st.sidebar:
    st.markdown(alterra_brand_title_html(sidebar=True), unsafe_allow_html=True)
    st.markdown("---")
    
    # Navigation buttons
    if st.button("Loan Structure", use_container_width=True, 
                 type="primary" if st.session_state.current_page == "Loan Structure" else "secondary"):
        st.session_state.current_page = "Loan Structure"
        st.rerun()

    if st.button("Portfolio", use_container_width=True,
                 type="primary" if st.session_state.current_page == "Portfolio" else "secondary"):
        st.session_state.current_page = "Portfolio"
        st.rerun()
    
    if st.button("Term Structure", use_container_width=True,
                 type="primary" if st.session_state.current_page == "Term Structure" else "secondary"):
        st.session_state.current_page = "Term Structure"
        st.rerun()
    
    st.markdown("---")

    refresh_settings = get_refresh_settings()
    last_refreshed = st.session_state.get("last_refreshed_at")
    st.caption(
        f"Market data last updated: {format_last_refreshed(last_refreshed, refresh_settings['tz_name'])}"
    )
    st.caption("Auto-refreshes once daily after 3:00 PM Eastern when someone opens the app.")

    if st.button("Force refresh now", use_container_width=True):
        with st.spinner("Loading data from boxtrades.com..."):
            fresh_data, did_refresh, last_refreshed_at, refresh_error = refresh_yield_data(
                force=True,
                **refresh_settings,
            )
            st.session_state.yield_data = fresh_data
            st.session_state.last_refreshed_at = last_refreshed_at
            if refresh_error:
                st.session_state.data_refresh_error = refresh_error
            elif "data_refresh_error" in st.session_state:
                del st.session_state.data_refresh_error
            if did_refresh and not fresh_data.empty:
                init_loan_inputs_from_df(fresh_data)
        st.rerun()

if st.session_state.get("data_refresh_error"):
    st.warning(f"Could not refresh market data: {st.session_state.data_refresh_error}")

# Get current page
page = st.session_state.current_page

# Page routing
if page == "Loan Structure":
    st.title("Loan Structure")
    
    # Get data from session state
    df = st.session_state.yield_data
    
    if df.empty:
        st.info("Market data is not available yet. It will load automatically after the next 3:00 PM Eastern refresh window, or use **Force refresh now** in the sidebar.")
    else:
        today = datetime.now().date()

        for _, row in df.iterrows():
            date_str = (
                row['Maturity Date'].date()
                if hasattr(row['Maturity Date'], 'date')
                else pd.to_datetime(row['Maturity Date']).date()
            ).strftime('%Y-%m-%d')
            if date_str not in st.session_state.loan_inputs:
                st.session_state.loan_inputs[date_str] = 0.0

        fee_col, _ = st.columns([1, 7])
        with fee_col:
            fee_rate_pct = st.number_input(
                "Annual Fee Rate (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(st.session_state.fee_rate_pct),
                step=0.01,
                format="%.2f",
                help="Annualized rate used to calculate the upfront fee on each box spread.",
            )
        if fee_rate_pct != st.session_state.fee_rate_pct:
            st.session_state.fee_rate_pct = fee_rate_pct
            st.session_state.pop("loan_structure_editor", None)
            st.rerun()

        loan_df = build_loan_dataframe(df, st.session_state.loan_inputs, today)

        if not loan_df.empty:
            render_summary_stats(
                compute_loan_summary_stats(loan_df, st.session_state.fee_rate_pct)
            )

            with st.expander(
                "Save to Portfolio",
                expanded=bool(st.session_state.portfolio_overwrite_loan),
            ):
                save_col1, save_col2 = st.columns([1, 3])
                with save_col1:
                    loan_number_input = st.number_input(
                        "Loan #",
                        min_value=1,
                        step=1,
                        format="%d",
                        key="portfolio_loan_number_input",
                    )
                    client_input = st.text_input(
                        "Client",
                        key="portfolio_client_input",
                    )
                with save_col2:
                    st.caption(
                        "Enter a whole-number Loan # and client name, then save this "
                        "structure to the Portfolio tab."
                    )

                save_clicked = st.button("Save to Portfolio", type="primary")

                if save_clicked:
                    loan_number, loan_number_error = parse_loan_number(loan_number_input)
                    if loan_number_error:
                        st.error(loan_number_error)
                    elif loan_df["Box Amount ($)"].sum() <= 0:
                        st.error("Add at least one Box Amount before saving to the Portfolio.")
                    elif loan_exists(loan_number):
                        st.session_state.portfolio_overwrite_loan = loan_number
                    else:
                        cashflow_to_save = build_cashflow_schedule(loan_df, today)
                        persist_loan_to_portfolio(
                            loan_number,
                            client_input,
                            loan_df,
                            cashflow_to_save,
                            st.session_state.fee_rate_pct,
                            today,
                        )
                        st.success(f"Loan #{loan_number} saved to Portfolio.")
                        st.session_state.portfolio_overwrite_loan = None

                if st.session_state.portfolio_overwrite_loan:
                    overwrite_loan = st.session_state.portfolio_overwrite_loan
                    st.warning(
                        f"Loan **#{overwrite_loan}** already exists in the Portfolio. "
                        "Overwrite it with the current Loan Structure?"
                    )
                    confirm_col, cancel_col = st.columns(2)
                    with confirm_col:
                        if st.button("Yes, overwrite existing loan", type="primary"):
                            cashflow_to_save = build_cashflow_schedule(loan_df, today)
                            persist_loan_to_portfolio(
                                overwrite_loan,
                                client_input,
                                loan_df,
                                cashflow_to_save,
                                st.session_state.fee_rate_pct,
                                today,
                            )
                            st.session_state.portfolio_overwrite_loan = None
                            st.success(f"Loan #{overwrite_loan} updated in Portfolio.")
                            st.rerun()
                    with cancel_col:
                        if st.button("Cancel overwrite"):
                            st.session_state.portfolio_overwrite_loan = None
                            st.rerun()

            # Create two columns: table on left, cashflow chart on right
            col_table, col_chart = st.columns([1.5, 1])
            
            with col_table:
                st.subheader("Loan Structure")
                st.markdown(
                    '<div class="loan-input-callout">'
                    '<span>Input</span> Edit <strong>Box Amount ($)</strong> — '
                    'outlined column in the table below'
                    '</div>',
                    unsafe_allow_html=True,
                )

                with st.container(border=True):
                    edited_df = st.data_editor(
                    loan_df,
                    column_config={
                        "Maturity Date": st.column_config.TextColumn(
                            "Maturity Date",
                            disabled=True,
                            width="small",
                        ),
                        "Box Amount ($)": monetary_column(
                            "Box Amount ($)",
                            min_value=0.0,
                        ),
                        "DTE": st.column_config.NumberColumn(
                            "DTE",
                            disabled=True,
                            format="%d",
                            width="small",
                        ),
                        "Rate (%)": st.column_config.NumberColumn(
                            "Rate (%)",
                            disabled=True,
                            format="%.2f%%",
                            width="small",
                        ),
                        "Funded Amount ($)": monetary_column(
                            "Funded Amount ($)",
                            disabled=True,
                        ),
                        "Fee ($)": monetary_column(
                            "Fee ($)",
                            disabled=True,
                        ),
                        "Net Proceeds ($)": monetary_column(
                            "Net Proceeds ($)",
                            disabled=True,
                        ),
                    },
                    column_order=[
                        "Maturity Date",
                        "Box Amount ($)",
                        "DTE",
                        "Rate (%)",
                        "Funded Amount ($)",
                        "Fee ($)",
                        "Net Proceeds ($)",
                    ],
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    key="loan_structure_editor",
                    )

                st.caption(summary_stats_footnotes(st.session_state.fee_rate_pct))

                loan_inputs_changed = False
                for _, row in edited_df.iterrows():
                    date_str = row['Maturity Date']
                    loan_amount = row['Box Amount ($)']
                    if pd.isna(loan_amount):
                        continue
                    loan_amount = round_currency(loan_amount)
                    if st.session_state.loan_inputs.get(date_str, 0.0) != loan_amount:
                        st.session_state.loan_inputs[date_str] = loan_amount
                        loan_inputs_changed = True

                if loan_inputs_changed:
                    st.session_state.pop("loan_structure_editor", None)
                    st.rerun()

                edited_df = build_loan_dataframe(df, st.session_state.loan_inputs, today)
            
            with col_chart:
                st.subheader("Cashflow Schedule*")
                cashflow_df = build_cashflow_schedule(edited_df, today)
                render_cashflow_panel(cashflow_df, st.session_state.fee_rate_pct)
    
elif page == "Portfolio":
    st.title("Portfolio")

    if st.session_state.get("portfolio_delete_message"):
        st.success(st.session_state.portfolio_delete_message)
        del st.session_state.portfolio_delete_message

    portfolio_df = list_loans_table()

    if portfolio_df.empty:
        st.info(
            "No loans saved yet. Build a structure on **Loan Structure** and use "
            "**Save to Portfolio** to add one here."
        )
    else:
        render_portfolio_table(portfolio_df)

        st.markdown("---")
        st.subheader("Cashflow Schedules")

        cashflow_labels = ["Aggregate"]
        cashflow_label_to_loan = {"Aggregate": None}
        for _, row in portfolio_df.iterrows():
            loan_num = str(row["Loan #"])
            client = row.get("Client", "") or "—"
            label = f"{loan_num} / {client}"
            cashflow_labels.append(label)
            cashflow_label_to_loan[label] = loan_num

        cf_col, _ = st.columns([1, 4])
        with cf_col:
            selected_cashflow = st.selectbox(
                "View cashflow",
                cashflow_labels,
                key="portfolio_cashflow_select",
            )

        if selected_cashflow == "Aggregate":
            combined_structure = aggregate_loan_structures()
            aggregate_fee = aggregate_fee_rate_pct()
            st.caption("Combined cashflows and summary totals across all saved loans.")
            if not combined_structure.empty:
                render_summary_stats(
                    compute_loan_summary_stats(combined_structure, aggregate_fee)
                )
            cashflow_df = aggregate_cashflows()
            render_cashflow_panel(
                cashflow_df,
                aggregate_fee,
                chart_height=350,
                table_height=400,
            )
        else:
            loan_number = cashflow_label_to_loan[selected_cashflow]
            loan = get_loan(loan_number)
            if loan:
                client_name = loan.get("client", "")
                client_label = f" · Client: {client_name}" if client_name else ""
                st.caption(
                    f"Saved {loan.get('saved_at', '')[:16].replace('T', ' ')} · "
                    f"As of {loan.get('as_of_date', '')} · "
                    f"Fee rate {loan.get('fee_rate_pct', 0):.2f}%{client_label}"
                )
                render_summary_stats(
                    compute_loan_summary_stats(
                        pd.DataFrame(loan["loan_structure"]),
                        loan.get("fee_rate_pct", DEFAULT_FEE_RATE_PCT),
                    )
                )
                cashflow_df = pd.DataFrame(loan["cashflow"])
                render_cashflow_panel(
                    cashflow_df,
                    loan.get("fee_rate_pct", DEFAULT_FEE_RATE_PCT),
                    chart_height=350,
                    table_height=400,
                )

elif page == "Term Structure":
    st.title("Term Structure")
    
    # Get data from session state
    df = st.session_state.yield_data
    
    if df.empty:
        st.info("Market data is not available yet. It will load automatically after the next 3:00 PM Eastern refresh window, or use **Force refresh now** in the sidebar.")
    else:
        # Create the yield curve chart
        # Use Plotly for interactive chart
        fig = go.Figure()
        
        # Add line chart
        fig.add_trace(go.Scatter(
            x=df['Maturity Date'],
            y=df['Effective Yield'],
            mode='lines+markers',
            name='Effective Yield',
            line=dict(color='#0a1614', width=2),
            marker=dict(size=8, color='#5EFFAF', line=dict(color='#0a1614', width=1)),
            hovertemplate='<b>Maturity Date:</b> %{x|%Y-%m-%d}<br>' +
                          '<b>Effective Yield:</b> %{y:.2f}%<extra></extra>'
        ))
        
        # Update layout
        fig.update_layout(
            xaxis_title="Maturity Date",
            yaxis_title="Effective Yield (%)",
            hovermode='x unified',
            height=500,
            showlegend=False,
            **ALTERRA_CHART_LAYOUT,
            xaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(10,22,20,0.08)'
            ),
            yaxis=dict(
                showgrid=True,
                gridwidth=1,
                gridcolor='rgba(10,22,20,0.08)'
            )
        )
        
        st.plotly_chart(fig, use_container_width=True)
