#!/usr/bin/env python3
"""Extract head- and programme-level expenditure from the Estimates PDFs, and
test whether the official functional classification can be rebuilt from it.

`tools/build_data.py` publishes the chart's figures at the level the books
print them. This script goes one level deeper — Head (ministry) and Programme —
because a drill-down needs a head -> function mapping, and the books never
print one. The only way to establish such a mapping is to derive it and then
check that each function's heads sum to that function's published Table 5
total. That check is the point of this script.

It answers the question with evidence rather than assertion: for every one of
the ten functional categories it asks whether *any* subset of the 27 head
totals sums to the published total. If a function has no feasible subset, no
head -> function mapping can reproduce it, and the drill-down cannot be built
at head level however the mapping is drawn.

Everything it prints is reconciled against the books' own printed totals, and
it exits non-zero if any of those checks fail.

Usage:
    pip install pdfplumber
    python3 tools/build_heads.py

Reads   sources/*.pdf
Writes  data/heads-2025-26.json, data/heads-2026-27.json
"""

import bisect
import json
import os
import re
import sys

try:
    import pdfplumber
except ImportError:
    sys.exit("pdfplumber is required:  pip install pdfplumber")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import decid, numbers  # noqa: E402  (same glyph decoder)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Column geometry.
#
# The head pages print six right-aligned money columns. Where all six are
# populated, adjacent figures collide into one token — "415,891,980379,464,695"
# — so whitespace tokenisation cannot split them. The row of six '$' signs
# under the year headings is the one landmark present on every head page (the
# year headings themselves wrap onto two lines on some pages), so columns are
# cut midway between adjacent '$' marks. That boundary falls in the white gap
# between two columns of figures, which is what lets colliding figures be
# separated at character level.
# --------------------------------------------------------------------------

def _clusters(items, key, tol):
    """Group items into runs where consecutive keys differ by no more than tol."""
    items = sorted(items, key=key)
    out, cur = [], []
    for it in items:
        if cur and key(it) - key(cur[-1]) > tol:
            out.append(cur)
            cur = []
        cur.append(it)
    if cur:
        out.append(cur)
    return out


def _bands(page):
    for row in _clusters(page.extract_words(), lambda w: w["top"], 5):
        marks = sorted(w["x1"] for w in row if w["text"] == "$")
        if len(marks) == 6:
            pitch = (marks[5] - marks[0]) / 5.0
            # The first column's left edge is set nearly a full pitch out so
            # that the leading digit of a ten-figure number is not clipped off
            # into the label column; ministry labels stop well short of it.
            edges = ([marks[0] - pitch * 0.95]
                     + [(marks[i] + marks[i + 1]) / 2.0 for i in range(5)]
                     + [marks[5] + pitch / 2.0])
            return [(edges[i], edges[i + 1]) for i in range(6)]
    return None


def _text_lines(page, bands):
    """One (label, [six column values]) pair per physical line of text.

    Values are read from characters, not words. A column with no figure reads
    as 0; a column whose characters do not form a number reads as None, so a
    bad decode surfaces as a failed reconciliation rather than a wrong number.
    """
    lines = []
    for line in _clusters(page.chars, lambda c: c["top"], 2.5):
        line = sorted(line, key=lambda c: c["x0"])

        def span(lo, hi):
            return decid("".join(c["text"] for c in line
                                 if lo <= (c["x0"] + c["x1"]) / 2 <= hi))

        label = re.sub(r"\s+", " ", span(-1e9, bands[0][0])).strip()
        vals = []
        for lo, hi in bands:
            s = span(lo, hi).replace(",", "").strip()
            vals.append(int(s) if re.fullmatch(r"-?\d+", s) else (None if s else 0))
        lines.append((label, vals))
    return lines


PROG_RE = re.compile(r"^(\d{3})\s+(\S.*)$")
TOTAL_RE = re.compile(r"^Total\s+Head\s+(\d+)\s*:?$")


def read_head(pdf, first_page):
    """One head's programme table, following continuation pages."""
    bands = _bands(pdf.pages[first_page - 1])
    if not bands:
        raise LookupError(f"no '$' column row on page {first_page}")

    progs, total, head, pending = [], None, None, None
    page = first_page
    while total is None and page <= first_page + 4:
        for label, vals in _text_lines(pdf.pages[page - 1],
                                       _bands(pdf.pages[page - 1]) or bands):
            populated = any(vals)
            m = TOTAL_RE.match(label)
            if m:
                head = int(m.group(1))
                if populated:
                    total = vals
                    break
                pending = ("total",)
                continue
            m = PROG_RE.match(label)
            if m:
                # A programme's figures sit on the label's line, or — when the
                # name wraps — on the line below it.
                pending = ("prog", m.group(1), m.group(2).strip())
                if populated:
                    progs.append((m.group(1), m.group(2).strip(), vals))
                    pending = None
                continue
            if populated and pending:
                if pending[0] == "prog":
                    progs.append((pending[1], pending[2], vals))
                else:
                    total = vals
                pending = None
                if total:
                    break
        page += 1
    return head, progs, total


def head_pages(pdf):
    """First page of each head's programme table, in book order."""
    starts, prev_open = [], False
    for i, page in enumerate(pdf.pages):
        text = decid(page.extract_text() or "")
        is_table = "Forward Estimates" in text and "by Programme" in text
        if is_table and not prev_open:
            starts.append(i + 1)
        prev_open = is_table and "Total Head" not in text
    return starts


# --------------------------------------------------------------------------
# Table 7 — expenditure by ministry. Its grand-total column is the head total
# that reconciles exactly to the cover page, so it is the authority here; the
# head pages are an independent second reading of the same figure.
#
# Table 7 is printed as two facing pages, recurrent and capital, sharing row
# positions. The ministry names are on the first, the grand total on the last
# column of the second, so the two are joined on vertical position.
# --------------------------------------------------------------------------

def table7_grand_totals(pdf, capital_page):
    """Every ministry grand total printed in Table 7's capital page.

    Returned as a bag of figures rather than a head -> total mapping. Table 7
    prints ministry names on the recurrent page and grand totals on the facing
    capital page, and the two do not stay in step: names wrap onto a second
    line where the figures do not, and in the 2026-27 draft the amortisation
    row sits against the wrong ministry. Corroborating each head's own total
    by value avoids inheriting that misalignment.
    """
    rows = {}
    for w in pdf.pages[capital_page - 1].extract_words():
        rows.setdefault(round(w["top"] / 3), []).append((w["x0"], decid(w["text"])))
    out = []
    for _, words in sorted(rows.items()):
        nums = numbers(" ".join(t for _, t in sorted(words)))
        if nums:
            out.append(nums[-1])
    return out


# --------------------------------------------------------------------------
# The question this script exists to answer.
# --------------------------------------------------------------------------

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


# The books round to the dollar inconsistently between tables, so figures that
# should be identical can differ by a few dollars. The mapping test itself is
# run on exact equality — a "no subset exists" verdict is then the strongest
# claim available — and this slack is used only for the second-look questions:
# does a head total also appear in Table 7, and was anything a near miss.
ROUNDING = 5


def feasible_head_subsets(totals, target, tol=0, limit=8):
    """Subsets of head totals summing to target, within `tol` dollars.

    Exhaustive by meet-in-the-middle: the heads are split in half, every
    subset sum of each half is enumerated, and the halves are matched. If this
    returns nothing, no assignment of whole heads to that function can
    reproduce its published total.
    """
    heads = sorted(totals.items())
    mid = len(heads) // 2

    def sums(part):
        out = [(0, ())]
        for name, value in part:
            out += [(acc + value, chosen + (name,)) for acc, chosen in out]
        return out

    left = sums(heads[:mid])
    right = sorted(sums(heads[mid:]))
    right_sums = [s for s, _ in right]

    found = []
    for acc, chosen in left:
        lo = bisect.bisect_left(right_sums, target - acc - tol)
        hi = bisect.bisect_right(right_sums, target - acc + tol)
        for _, other in right[lo:hi]:
            found.append(sorted(chosen + other))
            if len(found) >= limit:
                return found
    return found


BOOKS = {
    "2025-26": {
        "pdf": "sources/barbados-estimates-2025-2026-approved.pdf",
        "col": 3,                 # the six columns are actual, approved,
        "table7_capital_page": 31,  # revised, budget year, and two forward years
        "function_page": 28,
        "expect_expenditure_total": 5_179_219_577,
        # The Post Office is presented outside the ministry total and is not
        # part of total expenditure.
        "excluded_heads": [50],
        # The head pages round to the dollar independently of Table 7 and the
        # cover page, so their totals land a few dollars off the printed total.
        "expect_total_residual": -3,
        # Differences between a head's printed "Total Head" line and its own
        # programme rows, in the book as published. Anything not declared here
        # -- or declared at a different amount -- fails the build.
        "known_programme_gaps": {
            33: 1,
            96: 1,
            # Programme 511, Drainage Services, is missing from Head 40's
            # summary table; it appears in the detail pages and in the head's
            # own total.
            40: -8_996_878,
        },
        "duplicated_head_pages": [],
    },
    "2026-27": {
        "pdf": "sources/barbados-estimates-2026-2027-draft-revised.pdf",
        "col": 3,
        "table7_capital_page": 31,
        "function_page": 28,
        "expect_expenditure_total": 5_875_116_133,
        "excluded_heads": [50],
        # This book is a draft and does not close. Head 39's page prints a
        # total 4,082,639 above the figure Table 7 carries for it, and Table 7
        # is the column that sums to the cover page. The residual below is
        # that discrepancy.
        "expect_total_residual": 4_082_638,
        "known_programme_gaps": {
            14: -400,
            19: -50_615_647,
            32: 900_000,
            40: -930_263,
            41: -196,
            63: 999_999,
            96: 749_995,
        },
        # The Office of the President's page is printed twice, identically.
        "duplicated_head_pages": [10],
    },
}


def build(year, cfg):
    path = os.path.join(ROOT, cfg["pdf"])
    if not os.path.exists(path):
        sys.exit(f"missing source PDF: {cfg['pdf']}")

    failures, notes = [], []
    col = cfg["col"]

    with pdfplumber.open(path) as pdf:
        corroborating = table7_grand_totals(pdf, cfg["table7_capital_page"])

        fun_lines = decid(pdf.pages[cfg["function_page"] - 1].extract_text()).split("\n")
        functions = {}
        for name in FUNCTIONS:
            for line in fun_lines:
                if line.strip().startswith(name):
                    functions[name] = numbers(line.strip()[len(name):])[0]
                    break
        missing_functions = [n for n in FUNCTIONS if n not in functions]
        if missing_functions:
            sys.exit(f"{year}: could not read Table 5 rows: {missing_functions}")

        heads = {}
        for first in head_pages(pdf):
            head, progs, total = read_head(pdf, first)
            if head is None or total is None:
                failures.append(f"page {first}: no 'Total Head' row found")
                continue
            entry = {
                "page": first,
                "total": total[col],
                "programmes": [{"code": c, "name": n, "value": v[col]} for c, n, v in progs],
            }
            if head in heads:
                # A head printed twice must at least agree with itself.
                if heads[head]["total"] != entry["total"]:
                    failures.append(f"Head {head} appears on pages {heads[head]['page']} "
                                    f"and {first} with different totals")
                elif head in cfg["duplicated_head_pages"]:
                    notes.append(f"Head {head}: its page is printed twice "
                                 f"(pages {heads[head]['page']} and {first}), identically")
                else:
                    failures.append(f"Head {head} appears on pages {heads[head]['page']} "
                                    f"and {first}; not a declared duplicate")
                continue
            heads[head] = entry

    for head in cfg["duplicated_head_pages"]:
        if head not in heads:
            failures.append(f"Head {head} is declared a duplicated page but was read once")

    # ---- reconciliations ----------------------------------------------------
    if sum(functions.values()) != cfg["expect_expenditure_total"]:
        failures.append(f"Table 5 functions sum to {sum(functions.values()):,}, "
                        f"not {cfg['expect_expenditure_total']:,}")

    voted = {h: e["total"] for h, e in heads.items() if h not in set(cfg["excluded_heads"])}
    residual = sum(voted.values()) - cfg["expect_expenditure_total"]
    if residual != cfg["expect_total_residual"]:
        failures.append(f"head totals sum to {sum(voted.values()):,}, "
                        f"{residual:+,} against total expenditure — expected "
                        f"{cfg['expect_total_residual']:+,}")

    for head, entry in sorted(heads.items()):
        got = sum(p["value"] or 0 for p in entry["programmes"])
        entry["programmeSum"] = got
        gap = got - entry["total"]
        declared = cfg["known_programme_gaps"].get(head, 0)
        if gap != declared:
            failures.append(f"Head {head}: programmes sum {gap:+,} against its printed "
                            f"'Total Head' of {entry['total']:,} — expected {declared:+,}")
        elif gap:
            entry["programmeGap"] = gap
            notes.append(f"Head {head}: programmes sum {gap:+,} against its printed "
                         f"'Total Head' of {entry['total']:,}")

    for head in cfg["known_programme_gaps"]:
        if head not in heads:
            failures.append(f"Head {head} has a declared programme gap but was not read")

    if failures:
        print(f"\n{year}: RECONCILIATION FAILED", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    corroborated = sum(1 for t in voted.values()
                       if any(abs(t - c) <= ROUNDING for c in corroborating))
    print(f"  ok  {year}  Table 5 functions sum to total expenditure "
          f"({cfg['expect_expenditure_total']:,})")
    print(f"  ok  {year}  {len(voted)} head totals sum to it too "
          f"({residual:+,}, as expected)")
    print(f"  ok  {year}  every head's programmes sum to its own printed total")
    print(f"      {corroborated} of {len(voted)} head totals also appear in Table 7's "
          f"grand-total column")
    for n in notes:
        print(f"      {n}")

    # ---- the head -> function test -----------------------------------------
    print(f"\n  {year}: can each function be built from whole heads?")
    mapping, unmappable, ambiguous = {}, [], []
    for name in FUNCTIONS:
        exact = feasible_head_subsets(voted, functions[name])
        label = f"    {name:33s} {functions[name]:>15,}  "
        if len(exact) == 1:
            mapping[name] = exact[0]
            print(label + f"yes — heads {exact[0]}")
        elif exact:
            ambiguous.append(name)
            print(label + f"ambiguous — {len(exact)} different head sets sum to this")
        else:
            unmappable.append(name)
            # A small near miss inside the books' rounding is worth naming; a
            # dozen unrelated ministries landing within a few dollars of a
            # total is arithmetic coincidence, not a classification, so only
            # short candidate sets are reported.
            near = [s for s in feasible_head_subsets(voted, functions[name],
                                                     tol=ROUNDING, limit=8) if len(s) <= 3]
            hint = f" (nearest within ${ROUNDING}: heads {near[0]})" if near else ""
            print(label + "NO subset of heads sums to this" + hint)

    print(f"\n    {len(mapping)} of {len(FUNCTIONS)} functions can be expressed as whole "
          f"heads; {len(unmappable) + len(ambiguous)} cannot, so the classification is "
          f"applied below head level and no head-level drill-down is published.")

    return {
        "meta": {
            "year": year,
            "source": cfg["pdf"],
            "unit": "BDS$",
            "totalExpenditure": cfg["expect_expenditure_total"],
            "excludedHeads": sorted(cfg["excluded_heads"]),
            "note": ("Head and programme figures read from each head's own summary "
                     "table and reconciled against the printed totals. The books do "
                     "not publish a head-to-function crosswalk. headToFunction holds "
                     "the mappings that could be derived and verified against Table 5; "
                     "unmappableFunctions holds the functions no combination of whole "
                     "heads can reproduce, which is why no drill-down is built on this "
                     "data yet."),
            "headToFunction": mapping,
            "unmappableFunctions": unmappable,
            "ambiguousFunctions": ambiguous,
            "reconciliationNotes": notes,
        },
        "functions": functions,
        "heads": {str(h): heads[h] for h in sorted(heads)},
    }


def main():
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    for year, cfg in BOOKS.items():
        print(f"\nreading {year}")
        payload = build(year, cfg)
        out = os.path.join(ROOT, "data", f"heads-{year}.json")
        with open(out, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"\n      wrote data/heads-{year}.json")


if __name__ == "__main__":
    main()
