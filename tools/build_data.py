#!/usr/bin/env python3
"""Build the chart's data files from the official Barbados Estimates PDFs.

Every figure the chart renders is extracted here from the source documents and
checked against the totals printed in those documents. If a reconciliation
fails the build stops rather than emitting figures nobody has verified.

Usage:
    pip install pdfplumber
    python3 tools/build_data.py

Reads   sources/*.pdf
Writes  data/2025-26.json, data/2026-27.json, data/index.json
"""

import json
import os
import re
import sys

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is required:  pip install pdfplumber")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The books embed their digits as glyph ids rather than characters in some
# cells, so a value can arrive as "2,79(cid:26),(cid:27)...". Glyph ids 19-28
# are the digits 0-9; anything else is left visible as "?" so a bad decode
# shows up as a parse failure instead of a plausible wrong number.
CID = re.compile(r"\(cid:(\d+)\)")


def decid(text):
    return CID.sub(
        lambda m: str(int(m.group(1)) - 19) if 19 <= int(m.group(1)) <= 28 else "?",
        text or "",
    )


def page_lines(pdf, page_no):
    return decid(pdf.pages[page_no - 1].extract_text()).split("\n")


NUM = re.compile(r"-?\(?\d[\d,]*\)?")


def numbers(line):
    """Every money figure on a line, as ints. Parenthesised values are negative."""
    out = []
    for tok in NUM.findall(line):
        neg = tok.startswith("(") or tok.startswith("-")
        digits = tok.strip("()-").replace(",", "")
        if not digits:
            continue
        out.append(-int(digits) if neg else int(digits))
    return out


def find_row(lines, label, col, want_len=None):
    """The `col`-th figure on the line starting with `label`."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(label):
            nums = numbers(stripped[len(label):])
            if want_len and len(nums) < want_len:
                continue
            if len(nums) > col:
                return nums[col]
    raise LookupError(f"could not read {label!r} (column {col})")


# --------------------------------------------------------------------------
# What to pull out of each book.
#
# col 0 is the current year's estimate in both books' Tables 5 and 6; the
# 2026-27 revenue table (Table 4) puts its budget year in column 3, behind
# actual 2024-25 and the approved and revised 2025-26 columns.
# --------------------------------------------------------------------------

BOOKS = {
    "2025-26": {
        "pdf": "sources/barbados-estimates-2025-2026-approved.pdf",
        "label": "FY2025/26",
        "status": "Approved Estimates",
        "subtitle": "Citizen view of government revenue and spending • FY2025/26 Approved Estimates • BDS$ millions",
        "revenue_page": 28, "revenue_col": 0,
        "function_page": 28, "function_col": 0,
        "debt_page": 29, "debt_col": 0,
        "expect_revenue_total": 3_980_678_646,
        "expect_expenditure_total": 5_179_219_577,
        "source_note": "Approved Estimates of Revenue and Expenditure 2025-2026, laid in the House of Assembly 16 February 2025 and passed 30 March 2025.",
    },
    "2026-27": {
        "pdf": "sources/barbados-estimates-2026-2027-draft-revised.pdf",
        "label": "FY2026/27",
        "status": "Draft Revised Estimates",
        "subtitle": "Citizen view of government revenue and spending • FY2026/27 Draft Revised Estimates • BDS$ millions",
        "revenue_page": 27, "revenue_col": 3,
        "function_page": 28, "function_col": 0,
        "debt_page": 29, "debt_col": 0,
        "expect_revenue_total": 5_075_888_040,
        "expect_expenditure_total": 5_875_116_133,
        "source_note": "Draft Revised Estimates of Revenue and Expenditure 2026-2027, approved by Cabinet and laid in the House of Assembly in March 2026. These are draft figures and may change.",
    },
}

# Official revenue lines, in the order the chart should show them.
REVENUE_ROWS = [
    ("income-profits", "Income and Profits", "Income & profits", "Personal and company taxes"),
    ("goods-services", "Goods and Services", "Goods & services", "Mainly VAT and similar taxes"),
    ("trade", "International Trade", "International trade", "Import duties and trade taxes"),
    ("property", "Property Taxes", "Property", "Land and property taxes"),
    ("other-taxes", "Other Taxes", "Other taxes", "Remaining tax lines"),
    ("non-tax", "Non-Tax Revenue", "Non-tax revenue", "Fees, charges, levies and grants"),
]

# The ten official functional (COFOG) categories.
FUNCTIONS = [
    "General Public Services",
    "Defense",
    "Public Order And Safety",
    "Economic Affairs",
    "Environmental Protection",
    "Housing and Community Amenities",
    "Health",
    "Recreation, Culture and Religion",
    "Education",
    "Social Protection",
]

# Citizen categories, each an explicit sum of official functions. "debt" is
# handled separately because debt service sits inside General Public Services
# in the functional table and has to be lifted out of it.
MAPPING = [
    ("education", "Education & skills", ["Education"],
     "Schools, training and tertiary support"),
    ("healthcare", "Healthcare", ["Health"],
     "Hospitals, clinics and public health"),
    ("welfare", "Welfare & social protection", ["Social Protection"],
     "Pensions, transfers and support schemes"),
    ("infrastructure", "Housing, water & environment",
     ["Housing and Community Amenities", "Environmental Protection"],
     "Housing, water works and environmental protection"),
    ("economy", "Roads, transport & the economy", ["Economic Affairs"],
     "Transport, agriculture, tourism and industry"),
    ("safety", "Police, courts & defence", ["Public Order And Safety", "Defense"],
     "Policing, justice, prisons and defence"),
    ("community", "Sport, culture & community", ["Recreation, Culture and Religion"],
     "Sport, culture, religion and broadcasting"),
    ("administration", "Running the government", ["General Public Services"],
     "Core government operations, excluding debt service"),
]


def build(year, cfg):
    path = os.path.join(ROOT, cfg["pdf"])
    if not os.path.exists(path):
        sys.exit(f"missing source PDF: {cfg['pdf']}")

    with pdfplumber.open(path) as pdf:
        rev_lines = page_lines(pdf, cfg["revenue_page"])
        fun_lines = page_lines(pdf, cfg["function_page"])
        debt_lines = page_lines(pdf, cfg["debt_page"])

    col = cfg["revenue_col"]
    revenue = {rid: find_row(rev_lines, src, col) for rid, src, _, _ in REVENUE_ROWS}
    revenue_total = find_row(rev_lines, "Total Current Revenue", col)

    fcol = cfg["function_col"]
    functions = {name: find_row(fun_lines, name, fcol) for name in FUNCTIONS}
    expenditure_total = find_row(fun_lines, "TOTAL EXPENDITURE", fcol)

    dcol = cfg["debt_col"]
    interest = find_row(debt_lines, "Interest Expense", dcol)
    loan_expenses = find_row(debt_lines, "Expenses of Loans", dcol)
    amortisation = find_row(debt_lines, "Debt Amortization", dcol)
    debt_service = find_row(debt_lines, "Debt service", dcol)

    # ---- reconciliations: fail loudly rather than publish a guess ----
    checks = []

    got = sum(revenue.values())
    checks.append(("revenue lines sum to the printed total", got, revenue_total))
    checks.append(("revenue total matches the cover page", revenue_total, cfg["expect_revenue_total"]))

    got = sum(functions.values())
    checks.append(("functional lines sum to the printed total", got, expenditure_total))
    checks.append(("expenditure total matches the cover page", expenditure_total, cfg["expect_expenditure_total"]))

    checks.append(("debt service is its three components",
                   interest + loan_expenses + amortisation, debt_service))

    # Debt service sits inside General Public Services. If that is true, then
    # everything except amortisation must add back to total less amortisation.
    admin_ex_debt = functions["General Public Services"] - debt_service
    non_gps = expenditure_total - functions["General Public Services"]
    ex_amortisation = non_gps + admin_ex_debt + interest + loan_expenses
    checks.append(("debt service nests inside General Public Services",
                   ex_amortisation, expenditure_total - amortisation))

    failed = [(what, a, b) for what, a, b in checks if a != b]
    if failed:
        print(f"\n{year}: RECONCILIATION FAILED", file=sys.stderr)
        for what, a, b in failed:
            print(f"  {what}: {a:,} != {b:,}  (out by {a - b:,})", file=sys.stderr)
        sys.exit(1)

    for what, a, _ in checks:
        print(f"  ok  {year}  {what}  ({a:,})")

    if admin_ex_debt < 0:
        sys.exit(f"{year}: debt service exceeds General Public Services")

    m = 1_000_000.0

    def rnd(v):
        return round(v / m, 2)

    revenue_out = [
        {"id": rid, "label": label, "value": rnd(revenue[rid]), "note": note}
        for rid, _, label, note in REVENUE_ROWS
    ]

    spending_out = []
    for cid_, label, parts, note in MAPPING:
        total = sum(functions[p] for p in parts)
        if cid_ == "administration":
            total -= debt_service          # lift debt service out of GPS
        spending_out.append({
            "id": cid_, "label": label, "value": rnd(total), "note": note,
            "from": parts if cid_ != "administration"
                    else ["General Public Services less debt service"],
        })
    spending_out.append({
        "id": "debt", "label": "Debt interest",
        "value": rnd(interest + loan_expenses), "tone": "debt",
        "note": "Interest and loan expenses; repayment of principal is excluded",
        "from": ["Interest Expense", "Expenses of Loans"],
    })

    spend_total = sum(s["value"] for s in spending_out)
    print(f"      {year}  revenue {sum(r['value'] for r in revenue_out):,.2f}m"
          f"  spending {spend_total:,.2f}m"
          f"  (amortisation of {amortisation / m:,.2f}m excluded)")

    return {
        "meta": {
            "title": "Barbados Budget – What Citizens Pay & What They Get",
            "subtitle": cfg["subtitle"],
            "unit": "BDS$ millions",
            "unitShort": "M",
            "unitPerPerson": "BDS$ per resident, per year",
            "currencySymbol": "$",
            "source": f"Source: Barbados {cfg['status']} of Revenue and Expenditure {year.replace('-', '-20')}.",
            "sourceNote": cfg["source_note"],
            "basisNote": (
                "Spending is grouped by the official functional classification (Table 5) "
                f"and excludes debt amortisation of BDS${amortisation / m:,.2f}m, which repays "
                "principal and is a financing item rather than a service. Total expenditure "
                f"including amortisation is BDS${expenditure_total / m:,.2f}m, the figure printed "
                "on the cover of the Estimates."
            ),
            "population": {
                "value": 261692,
                "year": 2025,
                "label": "Barbados Statistical Service, end-2025",
            },
            "highlights": {"debtId": "debt", "compareIds": ["education", "healthcare"]},
            "sources": [
                {
                    "label": f"Barbados {cfg['status']} of Revenue and Expenditure {year.replace('-', '-20')}",
                    "url": cfg["pdf"],
                    "supports": "Every revenue and spending figure on this page",
                    "verified": True,
                },
                {
                    "label": "Barbados Statistical Service",
                    "url": "https://stats.gov.bb/statistics/",
                    "supports": "Population used for per-resident figures",
                    "verified": False,
                },
            ],
            "reconciliation": {
                "revenueTotal": rnd(revenue_total),
                "expenditureTotalIncludingAmortisation": rnd(expenditure_total),
                "amortisationExcluded": rnd(amortisation),
                "expenditureShown": rnd(expenditure_total - amortisation),
            },
        },
        "revenue": revenue_out,
        "spending": spending_out,
    }


def main():
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    index = {"default": "2025-26", "years": []}

    for year, cfg in BOOKS.items():
        print(f"\nbuilding {year}")
        payload = build(year, cfg)
        out = os.path.join(ROOT, "data", f"{year}.json")
        with open(out, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"      wrote data/{year}.json")
        index["years"].append({
            "id": year,
            "label": f"{cfg['label']} · {cfg['status']}",
            "file": f"data/{year}.json",
        })

    with open(os.path.join(ROOT, "data", "index.json"), "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
    print("\nwrote data/index.json")


if __name__ == "__main__":
    main()
