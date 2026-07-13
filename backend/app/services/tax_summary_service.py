"""Consolidated tax-savings summary for ADA AI LLC.

Rolls every deductible category into one YTD picture + an *estimate* of the
personal tax it saves. Because ADA AI LLC is a single-member LLC taxed as a
disregarded entity, deductions flow to the owner's Schedule C and reduce both
federal income tax and self-employment tax.

Single source of truth per category (NO double-counting):

* **Ledger actuals** (bookkeeper YTD snapshot, `Expenses:*`) for everything
  posted through the books — AI/software, cloud, office, travel, legal,
  professional, education, insurance, bank fees, etc. Meals are halved (the 50%
  rule). Categories owned by a dedicated worksheet/register are EXCLUDED here so
  they aren't counted twice:
    - ``Expenses:Hardware``  → counted via the **asset register** instead
    - ``Expenses:Phone``     → counted via the **cell-phone worksheet** instead
    - ``Expenses:Auto``      → counted via the **vehicle/mileage worksheet** instead
* **Home office** (worksheet: actual if available, else simplified). Already
  includes rent/utilities/electricity/insurance/internet allocation — not re-added.
* **Cell phone + vehicle** (mixed-use worksheets).
* **Hardware/equipment** (asset register, current-year §179/depreciation est.).

Everything here is an estimate, not tax advice — the CPA confirms at filing.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from app.services.asset_service import get_asset_service
from app.services.bookkeeper_service import get_bookkeeper_service
from app.services.company_facts_service import get_company_facts_service
from app.services.schedule_c_map import build_rollup, map_category, map_worksheet

# Categories whose deduction is owned by a dedicated worksheet/register, so they
# must NOT also be summed from the ledger.
_LEDGER_EXCLUDE_PREFIXES = ("Expenses:Hardware", "Expenses:Phone", "Expenses:Auto")
_MEALS_PREFIX = "Expenses:Meals"

DEFAULT_MARGINAL_FEDERAL_PCT = 22.0
# Self-employment tax: 15.3% (12.4% SS + 2.9% Medicare) on 92.35% of net SE earnings.
_SE_BASE = 0.9235
_SE_RATE = 0.153


async def _fact_value(key: str) -> str | None:
    fact = await get_company_facts_service().get_fact(key)
    return fact.value if fact else None


def _to_float(raw: str | None, default: float) -> float:
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).replace("$", "").replace(",", "").replace("%", "").strip())
    except Exception:
        return default


def _to_bool(raw: str | None, default: bool) -> bool:
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


class TaxSummaryService:
    async def summary(self, *, year: int | None = None) -> dict[str, Any]:
        year = year or date.today().year
        line_items: list[dict[str, Any]] = []

        # ---- 1. Ledger actuals (YTD) -------------------------------------
        snapshot = await get_bookkeeper_service().snapshot(period="YTD")
        ledger_total = 0.0
        ledger_breakdown: dict[str, float] = {}
        for category, amount in (snapshot.by_category or {}).items():
            if not category.startswith("Expenses:"):
                continue
            if any(category.startswith(p) for p in _LEDGER_EXCLUDE_PREFIXES):
                continue
            value = float(amount or 0.0)
            if category.startswith(_MEALS_PREFIX):
                value = value * 0.5  # 50% meals rule
            ledger_breakdown[category] = round(value, 2)
            ledger_total += value
        ledger_total = round(ledger_total, 2)
        line_items.append({
            "key": "ledger",
            "label": "Booked business expenses (YTD)",
            "amount": ledger_total,
            "source": "bookkeeper ledger",
            "detail": ledger_breakdown,
            "note": "Meals counted at 50%. Hardware, phone, and vehicle excluded here (tracked below).",
        })

        # ---- 2. Home office (worksheet) ----------------------------------
        ho = await get_company_facts_service().home_office_summary()
        ho_amount = ho.get("actual_estimate_annual")
        ho_method = "actual"
        if ho_amount is None:
            ho_amount = ho.get("simplified_estimate")
            ho_method = "simplified"
        ho_amount = round(float(ho_amount or 0.0), 2)
        ho_note = (
            "Includes rent/utilities/electricity/insurance/internet allocation."
            if ho_method == "actual"
            else "$5/sqft simplified method; business internet is broken out separately below."
        )
        line_items.append({
            "key": "home_office",
            "label": "Home office (annual)",
            "amount": ho_amount,
            "source": f"home-office worksheet ({ho_method})",
            "note": ho_note,
            "missing_fields": ho.get("missing_fields", []),
        })

        # ---- 2b. Internet, standalone under the simplified method --------
        # The actual method already allocates internet inside the home-office
        # line (company_facts_service.home_office_summary); under simplified
        # the $5/sqft rate covers home costs but NOT the business share of
        # internet, which stays separately deductible (Schedule C line 25).
        if ho_method == "simplified":
            inputs = ho.get("inputs") or {}
            internet_monthly = _to_float(inputs.get("internet_monthly"), 0.0)
            internet_pct = _to_float(inputs.get("internet_business_pct"), 0.0)
            if internet_monthly > 0 and internet_pct > 0:
                line_items.append({
                    "key": "internet",
                    "label": "Internet (business %, annual)",
                    "amount": round(internet_monthly * 12 * (internet_pct / 100.0), 2),
                    "source": "home-office worksheet (standalone; simplified method)",
                    "note": "Not covered by the $5/sqft simplified rate; no double count.",
                })

        # ---- 3. Cell phone + vehicle (mixed-use worksheets) --------------
        deds = await get_company_facts_service().deductions_summary()
        cell_amount = round(float(deds["cell_phone"].get("annual_deductible") or 0.0), 2)
        vehicle_amount = round(float(deds["vehicle"].get("annual_deductible") or 0.0), 2)
        line_items.append({
            "key": "cell_phone",
            "label": "Cell phone (business %, annual)",
            "amount": cell_amount,
            "source": "cell-phone worksheet",
        })
        line_items.append({
            "key": "vehicle",
            "label": "Vehicle mileage (annual)",
            "amount": vehicle_amount,
            "source": "vehicle worksheet (standard mileage)",
            "note": deds["vehicle"].get("rate_note"),
        })

        # ---- 4. Hardware / equipment (asset register) -------------------
        hardware_amount = await get_asset_service().total_current_year_deduction(year=year)
        line_items.append({
            "key": "hardware",
            "label": f"Hardware / equipment ({year})",
            "amount": hardware_amount,
            "source": "asset register (§179/depreciation est.)",
        })

        # ---- Schedule C annotation + rollup ------------------------------
        sc_entries: list[dict[str, Any]] = []
        for li in line_items:
            if li["key"] == "ledger":
                for category, amount in (li.get("detail") or {}).items():
                    if not amount:
                        continue
                    mapped = map_category(category)
                    sc_entries.append({**mapped, "amount": amount, "category": category})
                li["schedule_c"] = {"line": "various", "label": "Mapped per category (see schedule_c_rollup)"}
            else:
                mapped = map_worksheet(li["key"])
                li["schedule_c"] = mapped
                if li["amount"]:
                    sc_entries.append({**mapped, "amount": li["amount"], "category": li["key"]})
        schedule_c_rollup = build_rollup(sc_entries)

        # ---- Totals + estimated tax saved -------------------------------
        total_deductible = round(sum(li["amount"] for li in line_items), 2)

        marginal_pct = _to_float(await _fact_value("tax.marginal_federal_pct"), DEFAULT_MARGINAL_FEDERAL_PCT)
        include_se = _to_bool(await _fact_value("tax.include_se"), True)

        est_income_tax_saved = round(total_deductible * (marginal_pct / 100.0), 2)
        est_se_tax_saved = round(total_deductible * _SE_BASE * _SE_RATE, 2) if include_se else 0.0
        est_total_tax_saved = round(est_income_tax_saved + est_se_tax_saved, 2)

        return {
            "year": year,
            "entity": snapshot.entity,
            "line_items": line_items,
            "schedule_c_rollup": schedule_c_rollup,
            "total_deductible": total_deductible,
            "marginal_federal_pct": marginal_pct,
            "include_se": include_se,
            "est_income_tax_saved": est_income_tax_saved,
            "est_se_tax_saved": est_se_tax_saved,
            "est_total_tax_saved": est_total_tax_saved,
            "se_note": (
                "SE tax estimated at 15.3% x 92.35% of the deduction; only applies while "
                "net self-employment income is positive (Social Security portion caps at the "
                "annual wage base). Half of SE tax is itself deductible — a second-order effect "
                "not modeled here."
            ),
            "disclaimer": (
                "Estimate only — not tax advice. ADA AI LLC is a disregarded-entity SMLLC, so "
                "these deductions flow to your Schedule C and reduce both income and SE tax. "
                "Your CPA confirms categories, methods, and amounts at filing."
            ),
        }


    async def tax_package(self, *, year: int | None = None, fmt: str = "md") -> tuple[str, str, str]:
        """CPA handoff package: (content, media_type, filename).

        Markdown is the human/CPA-readable narrative; CSV is the flat
        Schedule-C rollup for spreadsheet import.
        """
        year = year or date.today().year
        summary = await self.summary(year=year)
        assets = await get_asset_service().list_assets(year=year)
        ho = await get_company_facts_service().home_office_summary()
        deds = await get_company_facts_service().deductions_summary()

        if fmt == "csv":
            lines = ["schedule_c_line,label,amount,categories"]
            for row in summary["schedule_c_rollup"]:
                cats = ";".join(row["categories"])
                label = row["label"].replace('"', "'")
                lines.append(f'{row["line"]},"{label}",{row["amount"]:.2f},"{cats}"')
            lines.append(f',TOTAL,{summary["total_deductible"]:.2f},')
            return "\n".join(lines) + "\n", "text/csv", f"ada-ai-tax-package-{year}.csv"

        contributed = [a for a in assets if a.acquisition_type == "contributed"]
        owner_contrib_total = round(
            sum(float(a.fmv_at_contribution or a.cost or 0.0) for a in contributed), 2
        )

        md: list[str] = [
            f"# {summary['entity']} — Tax Package {year}",
            "",
            f"_Generated {date.today().isoformat()} by Zero's bookkeeper. Estimates only — not tax advice; "
            "the CPA confirms categories, methods, and amounts at filing. Disregarded-entity SMLLC → Schedule C._",
            "",
            "## Schedule C rollup (Part II)",
            "",
            "| Line | Label | Amount | Source categories |",
            "|---|---|---:|---|",
        ]
        for row in summary["schedule_c_rollup"]:
            md.append(
                f"| {row['line']} | {row['label']} | ${row['amount']:,.2f} | {', '.join(row['categories'])} |"
            )
        md += [
            f"| | **Total deductible** | **${summary['total_deductible']:,.2f}** | |",
            "",
            "## Estimated tax impact",
            "",
            f"- Marginal federal rate used: {summary['marginal_federal_pct']}%",
            f"- Est. income tax saved: ${summary['est_income_tax_saved']:,.2f}",
            f"- Est. SE tax saved: ${summary['est_se_tax_saved']:,.2f}"
            + ("" if summary["include_se"] else " (SE excluded)"),
            f"- **Est. total tax saved: ${summary['est_total_tax_saved']:,.2f}**",
            "",
            "## Asset register",
            "",
        ]
        if assets:
            md += [
                "| Asset | Acquired | Basis inputs | Biz % | Method | Placed in service | {yr} deduction |".replace("{yr}", str(year)),
                "|---|---|---|---:|---|---|---:|",
            ]
            for a in assets:
                if a.acquisition_type == "contributed":
                    basis = (
                        f"FMV ${a.fmv_at_contribution or 0:,.2f}"
                        + (f" / orig ${a.original_cost:,.2f}" if a.original_cost else " / orig n/a")
                        + " (lesser-of)"
                    )
                else:
                    basis = f"cost ${a.cost:,.2f}"
                md.append(
                    f"| {a.name} | {a.acquisition_type} | {basis} | {a.business_use_pct:g}% | "
                    f"{a.method} | {a.placed_in_service or '—'} | ${a.current_year_deduction or 0:,.2f} |"
                )
        else:
            md.append("_No assets registered._")
        md += [
            "",
            "## Owner capital contributions (personal property → LLC)",
            "",
            f"- Items: {len(contributed)} — total FMV ${owner_contrib_total:,.2f}",
            "- Journal: Assets:Equipment / Equity:Owner:Contributions (see ledger.beancount)",
            "",
            "## Worksheets",
            "",
            f"- **Home office** — method elected: {ho.get('method')}; business-use {ho.get('business_use_pct') or '—'}%; "
            f"simplified ${ho.get('simplified_estimate') or 0:,.2f}/yr; actual ${ho.get('actual_estimate_annual') or 0:,.2f}/yr; "
            f"missing fields: {', '.join(ho.get('missing_fields') or []) or 'none'}",
            f"- **Cell phone** — ${deds['cell_phone'].get('monthly') or 0:,.2f}/mo × {deds['cell_phone'].get('business_pct') or 0:g}% biz "
            f"= ${deds['cell_phone'].get('annual_deductible') or 0:,.2f}/yr",
            f"- **Vehicle** — {deds['vehicle'].get('business_miles_ytd') or 0:g} business miles × "
            f"${deds['vehicle'].get('mileage_rate'):,.3f}/mi = ${deds['vehicle'].get('annual_deductible') or 0:,.2f}",
            "",
            "---",
            summary["disclaimer"],
        ]
        return "\n".join(md) + "\n", "text/markdown", f"ada-ai-tax-package-{year}.md"


@lru_cache(maxsize=1)
def get_tax_summary_service() -> TaxSummaryService:
    return TaxSummaryService()
