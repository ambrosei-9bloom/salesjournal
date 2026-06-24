"""
sales_journal_calendar.py
Streamlit app — upload sales journal PDFs, extract customer names automatically,
visualise each transaction date on a calendar with per-customer color-coding,
and click any date to see itemised details aggregated by customer.
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
# CUSTOMER COLOR PALETTE
# ─────────────────────────────────────────────────────────────────────────────

CUSTOMER_COLORS = [
    {"bg": "#2563EB", "light": "#DBEAFE", "border": "#BFDBFE", "text": "#1E40AF", "badge": "#1D4ED8"},
    {"bg": "#16A34A", "light": "#DCFCE7", "border": "#BBF7D0", "text": "#15803D", "badge": "#15803D"},
    {"bg": "#DC2626", "light": "#FEE2E2", "border": "#FECACA", "text": "#B91C1C", "badge": "#B91C1C"},
    {"bg": "#D97706", "light": "#FEF3C7", "border": "#FDE68A", "text": "#B45309", "badge": "#B45309"},
    {"bg": "#7C3AED", "light": "#EDE9FE", "border": "#DDD6FE", "text": "#6D28D9", "badge": "#6D28D9"},
    {"bg": "#0891B2", "light": "#CFFAFE", "border": "#A5F3FC", "text": "#0E7490", "badge": "#0E7490"},
    {"bg": "#BE185D", "light": "#FCE7F3", "border": "#FBCFE8", "text": "#9D174D", "badge": "#9D174D"},
]


def get_customer_color(index: int) -> dict:
    return CUSTOMER_COLORS[index % len(CUSTOMER_COLORS)]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%-m/%-d/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def extract_customer_name(text: str) -> str | None:
    """
    Extract customer name from the Filter Criteria line:
    'Filter Criteria includes: 1) Customer IDs from <Name> to <Name>'
    Returns the name, or None if not found.
    """
    match = re.search(
        r"Filter Criteria includes:.*?Customer IDs from (.+?) to \1",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    # Fallback: grab first name even if from/to differ
    match = re.search(
        r"Filter Criteria includes:.*?Customer IDs from (.+?) to ",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    return None


def extract_transactions(pdf_bytes: bytes) -> tuple[list[dict], str]:
    """
    Parse a sales-journal PDF.
    Returns (transactions, customer_name).
    Each transaction dict: { date, invoice, description, amount, customer }
    """
    transactions: list[dict] = []
    customer_name: str = "Unknown Customer"
    current_date = None
    current_invoice = None

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        # ── Extract customer name from full text (usually on page 1) ──
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

        extracted_name = extract_customer_name(full_text)
        if extracted_name:
            customer_name = extracted_name

        # ── Parse transactions page by page ──
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Header line: date + account + 7-digit invoice + desc + amount
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
                        transactions.append({
                            "date": current_date,
                            "invoice": current_invoice,
                            "description": desc.strip(),
                            "amount": float(amount_str.replace(",", "")),
                            "customer": customer_name,
                        })
                    continue

                # Detail line: 5-digit account + desc + amount
                detail_match = re.match(
                    r"^(\d{5})\s+(.+?)\s+([\d,]+\.\d{2})\s*$",
                    line,
                )
                if detail_match and current_date and current_invoice:
                    acct, desc, amount_str = detail_match.groups()
                    if acct == "11000":
                        continue
                    transactions.append({
                        "date": current_date,
                        "invoice": current_invoice,
                        "description": desc.strip(),
                        "amount": float(amount_str.replace(",", "")),
                        "customer": customer_name,
                    })

    return transactions, customer_name


def group_by_date(transactions: list[dict]) -> dict[date, list[dict]]:
    grouped: dict[date, list[dict]] = defaultdict(list)
    for t in transactions:
        grouped[t["date"]].append(t)
    return grouped


def daily_totals(grouped: dict[date, list[dict]]) -> dict[date, float]:
    return {d: sum(t["amount"] for t in txns) for d, txns in grouped.items()}


def customers_on_date(grouped: dict[date, list[dict]], d: date) -> list[str]:
    """Return unique customer names present on a given date."""
    if d not in grouped:
        return []
    return list(dict.fromkeys(t["customer"] for t in grouped[d]))


# ─────────────────────────────────────────────────────────────────────────────
# CALENDAR RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_calendar(
    year: int,
    month: int,
    grouped: dict[date, list[dict]],
    customer_color_map: dict[str, dict],
    selected: date | None,
):
    """
    Render one month as an HTML table.
    Dates with sales show colored dots per customer.
    Multi-customer dates show multiple dots.
    """
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdatescalendar(year, month)

    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    header = "".join(
        f"<th style='padding:6px 10px;color:#888;font-size:12px;font-weight:600;'>{d}</th>"
        for d in day_names
    )

    rows = ""
    for week in weeks:
        cells = ""
        for day in week:
            if day.month != month:
                cells += "<td style='padding:8px;'></td>"
            elif day in grouped:
                customers = customers_on_date(grouped, day)
                is_selected = selected == day

                # Determine cell background: use first customer's color
                first_color = customer_color_map.get(customers[0], CUSTOMER_COLORS[0])
                cell_bg = first_color["bg"] if is_selected else first_color["light"]
                cell_border = f"2px solid {first_color['bg']}"
                day_color = "#fff" if is_selected else first_color["text"]

                # Build customer dots
                dots = ""
                for cust in customers:
                    c = customer_color_map.get(cust, CUSTOMER_COLORS[0])
                    dot_color = "#fff" if is_selected else c["bg"]
                    dots += (
                        f"<span style='display:inline-block;width:6px;height:6px;"
                        f"border-radius:50%;background:{dot_color};margin:0 1px;'></span>"
                    )

                cells += (
                    f"<td style='padding:6px;text-align:center;'>"
                    f"<div style='background:{cell_bg};border:{cell_border};"
                    f"border-radius:10px;width:42px;min-height:42px;display:flex;"
                    f"flex-direction:column;align-items:center;justify-content:center;"
                    f"cursor:pointer;margin:auto;padding:4px 2px;'>"
                    f"<span style='font-weight:bold;font-size:14px;color:{day_color};'>{day.day}</span>"
                    f"<div style='margin-top:3px;'>{dots}</div>"
                    f"</div></td>"
                )
            else:
                cells += (
                    f"<td style='padding:6px;text-align:center;'>"
                    f"<div style='width:42px;height:42px;display:flex;"
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
if "customer_color_map" not in st.session_state:
    st.session_state.customer_color_map = {}
if "customer_names" not in st.session_state:
    st.session_state.customer_names = []
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None
if "view_year" not in st.session_state:
    st.session_state.view_year = date.today().year
if "view_month" not in st.session_state:
    st.session_state.view_month = date.today().month

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
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
            found_customers: list[str] = []

            with st.spinner("Extracting transactions…"):
                for f in uploaded:
                    txns, cust_name = extract_transactions(f.read())
                    all_txns.extend(txns)
                    if cust_name not in found_customers:
                        found_customers.append(cust_name)

            # Assign colors to each unique customer
            color_map = {
                name: get_customer_color(i)
                for i, name in enumerate(found_customers)
            }

            st.session_state.transactions = all_txns
            st.session_state.customer_color_map = color_map
            st.session_state.customer_names = found_customers
            st.session_state.selected_date = None

            if all_txns:
                earliest = min(t["date"] for t in all_txns)
                st.session_state.view_year = earliest.year
                st.session_state.view_month = earliest.month

            st.success(f"Loaded {len(all_txns)} line items from {len(uploaded)} file(s).")

    if st.session_state.transactions:
        st.divider()

        # ── Customer legend ──
        st.markdown("**Customers**")
        for name in st.session_state.customer_names:
            c = st.session_state.customer_color_map.get(name, CUSTOMER_COLORS[0])
            cust_txns = [t for t in st.session_state.transactions if t["customer"] == name]
            cust_total = sum(t["amount"] for t in cust_txns)
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:6px;'>"
                f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
                f"background:{c['bg']};flex-shrink:0;'></span>"
                f"<span style='font-size:13px;font-weight:600;color:#111;'>{name}</span>"
                f"</div>"
                f"<div style='margin-left:20px;font-size:12px;color:#666;margin-bottom:10px;'>"
                f"${cust_total:,.2f} across {len(set(t['date'] for t in cust_txns))} days</div>",
                unsafe_allow_html=True,
            )

        st.divider()
        grouped_all = group_by_date(st.session_state.transactions)
        totals_all = daily_totals(grouped_all)
        st.metric("Total Sale Days", len(grouped_all))
        st.metric("Grand Total", f"${sum(totals_all.values()):,.2f}")
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
color_map = st.session_state.customer_color_map

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

# ── Calendar grid ─────────────────────────────────────────────────────────────
year = st.session_state.view_year
month = st.session_state.view_month

calendar_html = render_calendar(year, month, grouped, color_map, st.session_state.selected_date)
st.markdown(calendar_html, unsafe_allow_html=True)

# ── Date selector ─────────────────────────────────────────────────────────────
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

    # Group transactions by customer first, then by invoice
    by_customer: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        by_customer[t["customer"]].append(t)

    for customer, cust_txns in by_customer.items():
        c = color_map.get(customer, CUSTOMER_COLORS[0])
        cust_day_total = sum(t["amount"] for t in cust_txns)

        # Customer header
        st.markdown(
            f"<div style='background:{c[\"light\"]};border-left:4px solid {c[\"bg\"]};"
            f"border-radius:6px;padding:10px 16px;margin-bottom:8px;'>"
            f"<span style='font-size:16px;font-weight:700;color:{c[\"text\"]};'>"
            f"👤 {customer}</span>"
            f"<span style='float:right;font-size:15px;font-weight:600;color:{c[\"text\"]};'>"
            f"${cust_day_total:,.2f}</span></div>",
            unsafe_allow_html=True,
        )

        # Group by invoice within this customer
        inv_groups: dict[str, list[dict]] = defaultdict(list)
        for t in cust_txns:
            inv_groups[t["invoice"]].append(t)

        for invoice, items in inv_groups.items():
            inv_total = sum(i["amount"] for i in items)
            with st.expander(f"Invoice #{invoice} — ${inv_total:,.2f}", expanded=True):
                for item in items:
                    cols = st.columns([5, 1])
                    cols[0].write(item["description"])
                    cols[1].write(f"**${item['amount']:,.2f}**")

        st.markdown("<div style='margin-bottom:16px;'></div>", unsafe_allow_html=True)

    # Day total footer
    st.markdown(
        f"<div style='background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;"
        f"padding:12px 20px;margin-top:4px;font-size:18px;font-weight:bold;color:#15803D;'>"
        f"Day Total (all customers): ${day_total:,.2f}</div>",
        unsafe_allow_html=True,
    )
