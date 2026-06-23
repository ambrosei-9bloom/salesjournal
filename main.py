"""
sales_journal_calendar.py
Streamlit app — upload sales journal PDFs, visualise each transaction date
on a calendar, and click any date to see itemised details.
"""

import re
import calendar
from datetime import date, datetime
from collections import defaultdict
from io import BytesIO

import streamlit as st
import pdfplumber

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sales Journal Calendar",
    page_icon="📅",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

DATE_PATTERNS = [
    r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",   # 1/7/26  or  01/07/2026
    r"\b(\d{4}-\d{2}-\d{2})\b",          # 2026-01-07
]

def parse_date(raw: str) -> date | None:
    """Try several common date formats and return a date object or None."""
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%-m/%-d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def extract_transactions(pdf_bytes: bytes) -> list[dict]:
    """
    Parse a sales-journal PDF and return a list of transaction dicts:
      { date, invoice, description, amount }

    Strategy:
    - Read every line.
    - Lines that start with a date + account ID + invoice number are
      "header" lines for a new invoice group.
    - Subsequent indented lines carry description + credit/debit amounts.
    - We collect the *credit* amount on the customer (11000) row as the
      invoice total; individual product lines carry debit amounts.
    """
    transactions: list[dict] = []
    current_date = None
    current_invoice = None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # ── Try to detect a header line: date + account + invoice ──
                # e.g.  "1/7/26 23100 2601041 DC: DC Sales Tax 18.30"
                header_match = re.match(
                    r"^(\d{1,2}/\d{1,2}/\d{2,4})\s+\d+\s+(\d{7})\s+(.+?)\s+([\d,]+\.\d{2})\s*$",
                    line,
                )
                if header_match:
                    raw_date, invoice, desc, amount_str = header_match.groups()
                    parsed = parse_date(raw_date)
                    if parsed:
                        current_date = parsed
                        current_invoice = invoice
                        transactions.append(
                            {
                                "date": current_date,
                                "invoice": current_invoice,
                                "description": desc.strip(),
                                "amount": float(amount_str.replace(",", "")),
                            }
                        )
                    continue

                # ── Detail line: account + description + amount ──
                # e.g.  "40200 Oversize Color Light WO#4929 300.00"
                detail_match = re.match(
                    r"^(\d{5})\s+(.+?)\s+([\d,]+\.\d{2})\s*$",
                    line,
                )
                if detail_match and current_date and current_invoice:
                    acct, desc, amount_str = detail_match.groups()
                    # Skip the customer receivable line (11000) — it's the total,
                    # not a purchased item.
                    if acct == "11000":
                        continue
                    transactions.append(
                        {
                            "date": current_date,
                            "invoice": current_invoice,
                            "description": desc.strip(),
                            "amount": float(amount_str.replace(",", "")),
                        }
                    )

    return transactions


def group_by_date(transactions: list[dict]) -> dict[date, list[dict]]:
    """Return {date: [transaction, ...]} mapping."""
    grouped: dict[date, list[dict]] = defaultdict(list)
    for t in transactions:
        grouped[t["date"]].append(t)
    return grouped


def daily_totals(grouped: dict[date, list[dict]]) -> dict[date, float]:
    return {d: sum(t["amount"] for t in txns) for d, txns in grouped.items()}


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_calendar(year: int, month: int, sale_dates: set[date], selected: date | None):
    """
    Render one month as an HTML table.
    Dates with sales get a highlighted cell with a button-like style.
    """
    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    weeks = cal.monthdatescalendar(year, month)

    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    header = "".join(f"<th style='padding:6px 10px;color:#888;font-size:12px;'>{d}</th>" for d in day_names)

    rows = ""
    for week in weeks:
        cells = ""
        for day in week:
            if day.month != month:
                cells += "<td style='padding:8px;'></td>"
            elif day in sale_dates:
                is_selected = selected == day
                bg = "#2563EB" if is_selected else "#DBEAFE"
                color = "#fff" if is_selected else "#1E40AF"
                border = "2px solid #2563EB" if is_selected else "2px solid #BFDBFE"
                cells += (
                    f"<td style='padding:6px;text-align:center;'>"
                    f"<div style='background:{bg};color:{color};border:{border};"
                    f"border-radius:50%;width:36px;height:36px;display:flex;"
                    f"align-items:center;justify-content:center;"
                    f"font-weight:bold;font-size:14px;cursor:pointer;margin:auto;'>"
                    f"{day.day}</div></td>"
                )
            else:
                cells += (
                    f"<td style='padding:6px;text-align:center;'>"
                    f"<div style='width:36px;height:36px;display:flex;"
                    f"align-items:center;justify-content:center;"
                    f"font-size:14px;color:#374151;margin:auto;'>{day.day}</div></td>"
                )
        rows += f"<tr>{cells}</tr>"

    html = f"""
    <table style='border-collapse:separate;border-spacing:4px;width:100%;'>
      <thead><tr>{header}</tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """
    return html


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────

if "transactions" not in st.session_state:
    st.session_state.transactions = []
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None
if "view_year" not in st.session_state:
    st.session_state.view_year = date.today().year
if "view_month" not in st.session_state:
    st.session_state.view_month = date.today().month

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — upload
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📂 Upload Sales Journals")
    uploaded = st.file_uploader(
        "Select one or more PDF sales journals",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if uploaded:
        if st.button("📊 Process Journals", use_container_width=True):
            all_txns: list[dict] = []
            with st.spinner("Extracting transactions…"):
                for f in uploaded:
                    txns = extract_transactions(f.read())
                    all_txns.extend(txns)
            st.session_state.transactions = all_txns
            st.session_state.selected_date = None
            if all_txns:
                # Jump calendar to earliest transaction month
                earliest = min(t["date"] for t in all_txns)
                st.session_state.view_year = earliest.year
                st.session_state.view_month = earliest.month
            st.success(f"Loaded {len(all_txns)} line items from {len(uploaded)} file(s).")

    if st.session_state.transactions:
        st.divider()
        grouped = group_by_date(st.session_state.transactions)
        totals = daily_totals(grouped)
        st.metric("Total Sale Days", len(grouped))
        st.metric("Grand Total", f"${sum(totals.values()):,.2f}")

        st.divider()
        st.caption("Click a highlighted date on the calendar to see details.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONTENT
# ─────────────────────────────────────────────────────────────────────────────

st.title("📅 Sales Journal Calendar")

if not st.session_state.transactions:
    st.info("Upload one or more sales journal PDFs in the sidebar to get started.")
    st.stop()

grouped = group_by_date(st.session_state.transactions)
totals = daily_totals(grouped)
sale_dates = set(grouped.keys())

# ── Month navigator ───────────────────────────────────────────────────────────
col_prev, col_title, col_next = st.columns([1, 4, 1])
with col_prev:
    if st.button("◀ Prev"):
        m = st.session_state.view_month - 1
        y = st.session_state.view_year
        if m < 1:
            m, y = 12, y - 1
        st.session_state.view_month, st.session_state.view_year = m, y
with col_next:
    if st.button("Next ▶"):
        m = st.session_state.view_month + 1
        y = st.session_state.view_year
        if m > 12:
            m, y = 1, y + 1
        st.session_state.view_month, st.session_state.view_year = m, y
with col_title:
    month_name = datetime(st.session_state.view_year, st.session_state.view_month, 1).strftime("%B %Y")
    st.markdown(f"<h2 style='text-align:center;margin:0;'>{month_name}</h2>", unsafe_allow_html=True)

st.divider()

# ── Calendar grid + date picker ───────────────────────────────────────────────
year = st.session_state.view_year
month = st.session_state.view_month

# Show the static HTML calendar
calendar_html = render_calendar(year, month, sale_dates, st.session_state.selected_date)
st.markdown(calendar_html, unsafe_allow_html=True)

# Date selector for highlighted days (replaces click since Streamlit is stateless)
month_sale_dates = sorted(d for d in sale_dates if d.year == year and d.month == month)

if month_sale_dates:
    st.markdown("---")
    st.markdown("**Select a date to view transactions:**")
    date_options = {d.strftime("%B %d, %Y"): d for d in month_sale_dates}
    chosen_label = st.selectbox(
        "Sales dates this month",
        options=["— pick a date —"] + list(date_options.keys()),
        label_visibility="collapsed",
    )
    if chosen_label != "— pick a date —":
        st.session_state.selected_date = date_options[chosen_label]
else:
    st.markdown(
        "<p style='color:#9CA3AF;text-align:center;'>No sales recorded this month.</p>",
        unsafe_allow_html=True,
    )

# ── Detail panel ─────────────────────────────────────────────────────────────
if st.session_state.selected_date:
    sel = st.session_state.selected_date
    txns = grouped.get(sel, [])
    day_total = totals.get(sel, 0)

    st.divider()
    st.subheader(f"🗓 {sel.strftime('%A, %B %d, %Y')}")

    # Group by invoice
    inv_groups: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        inv_groups[t["invoice"]].append(t)

    for invoice, items in inv_groups.items():
        inv_total = sum(i["amount"] for i in items)
        with st.expander(f"Invoice #{invoice} — ${inv_total:,.2f}", expanded=True):
            for item in items:
                cols = st.columns([5, 1])
                cols[0].write(item["description"])
                cols[1].write(f"**${item['amount']:,.2f}**")

    st.markdown(
        f"<div style='background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;"
        f"padding:12px 20px;margin-top:12px;font-size:18px;font-weight:bold;color:#15803D;'>"
        f"Day Total: ${day_total:,.2f}</div>",
        unsafe_allow_html=True,
    )
