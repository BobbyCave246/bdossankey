# Data provenance

Every figure rendered by the chart lives in `data.json`. This file records where
those figures are said to come from, what has actually been checked, and the
discrepancies found so far.

**Nothing in `data.json` is yet verified line by line against a primary
document.** Source entries carry `"verified": false` and the page renders an
"unverified" badge next to each. Flip the flag only after someone has opened the
cited document and reconciled the numbers.

## Cited sources

| Source | Supports | Verified |
| --- | --- | --- |
| [Ministry of Finance, Economic Affairs & Investment — Mid-Year Review FY2025/26](https://www.barbadosparliament.com/uploads/sittings/attachments/68eeefee95cbd02fdee0e1c474878743.pdf) | Revenue by category, expenditure | No |
| [Medium-Term Fiscal Framework 2025/26–2027/28 (Appendix I)](https://www.barbadosparliament.com/uploads/sittings/attachments/3cbc58ce1bc360806372fa476f67157f.pdf) | Multi-year projections | No |
| [Central Bank of Barbados — Review of the Economy, Jan–Mar 2026](https://www.centralbank.org.bb/news/economic-reviews/economic-review-january-march-2026) | FY2025/26 outturn, debt ratio | No |
| [Barbados Statistical Service](https://stats.gov.bb/statistics/) | Population | No |
| [IMF Country Report No. 25/153 — Barbados](https://www.imf.org/-/media/files/publications/cr/2025/english/1brbea2025001-print-pdf.pdf) | Independent cross-check | No |

## What has been checked, and how

Checks so far are **indirect**: the documents above could not be retrieved
directly from the environment this was assembled in, so the figures below come
from published summaries of those documents, not from the documents themselves.
Treat them as corroboration, not verification.

### Corroborated

- **Total revenue.** Reported projections for the 12 months ending 31 March 2026
  are about BDS$3.98bn on an accrual basis and BDS$3.88bn on a cash basis. The
  revenue in `data.json` totals **BDS$3,864.51m**, consistent with the cash basis.
- **Debt interest.** The Central Bank reports an FY2025/26 primary surplus of
  BDS$647.3m and an overall deficit of BDS$58.3m, which implies interest of about
  **BDS$705.6m**. `data.json` carries **BDS$718.02m** — a difference of ~1.8%,
  within what different vintages and definitions would explain.

### Discrepancies to resolve

1. **Expenditure basis (important).** Coverage of the Estimates quotes total
   spending near BDS$5.13bn accrual / BDS$5.08bn cash, against the
   **BDS$3,905.73m** in `data.json` — a gap of roughly BDS$1.2bn. The likely
   explanation is that the larger figure includes **debt amortisation**
   (repayment of principal), a financing item excluded from the fiscal balance.
   The chart's total is consistent with a near-balanced outturn, so the basis is
   probably right, but it must be confirmed and is now stated on the page via
   `meta.basisNote`. Publishing a BDS$3.9bn "total spending" figure without that
   caveat invites an easy and damaging correction.

2. **Deficit vintage.** `data.json` shows a deficit of **BDS$41.22m**; the Central
   Bank reports **BDS$58.3m** (0.4% of GDP) for the FY2025/26 outturn. These are
   different vintages — revised estimate versus outturn. Decide which the page is
   presenting and label it accordingly; the subtitle currently says "revised
   estimates".

3. **Population.** The Barbados Statistical Service end-2025 figure is reported as
   **261,692**; the World Bank puts 2025 population near **282,600** — an ~8%
   spread that moves every per-resident headline. `data.json` uses the national
   figure, on the basis that a Barbadian civic chart should use the national
   statistic. Confirm against the current BSS publication.

## The unresolved structural issue

The seven right-hand categories are an **editorial grouping**, not official line
items, and no mapping from the official Estimates to these categories is
published. Until that exists:

- `administration` holds BDS$1,041.91m — 27% of all spending — in a single
  catch-all bucket.
- No reader can reconcile the categories back to the source document.

The fix is a `mapping.json` assigning each official line item to a citizen
category, plus a generated reconciliation showing the categories summing to
official totals. That work needs the Estimates as machine-readable line items.
