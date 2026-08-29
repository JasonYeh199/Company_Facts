from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .metrics import ADDITIVE_FLOW_METRICS, BASE_METRICS, MAPPING_VERSION

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTER_FORMS = {"10-Q", "10-Q/A", "6-K", "6-K/A"}


@dataclass(frozen=True)
class RawFact:
    id: str | int | None
    taxonomy: str
    concept: str
    unit: str
    value: Decimal
    period_start: date | None
    period_end: date
    accession: str
    form: str
    filed: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    frame: str | None = None


@dataclass
class NormalizedPoint:
    metric_code: str
    frequency: str
    period_start: date | None
    period_end: date
    value: Decimal
    unit: str
    accession: str | None
    filed: date | None
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    is_derived: bool = False
    quality: str = "reported"
    lineage: list[dict[str, object]] = field(default_factory=list)
    mapping_version: str = MAPPING_VERSION

    @property
    def accession_key(self) -> str:
        if self.accession:
            start_key = self.period_start.isoformat() if self.period_start else "instant"
            return f"{self.accession}:{start_key}"
        sources = sorted(
            f"{item.get('fact_id')}|{item.get('accession')}|{item.get('unit')}"
            for item in self.lineage
        )
        digest = hashlib.sha256("||".join(sources).encode()).hexdigest()[:16]
        return (
            f"derived:{self.metric_code}:{self.frequency}:"
            f"{self.period_end.isoformat()}:{digest}"
        )


def decimal_value(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric SEC fact: {value!r}") from exc


def classify_frequency(fact: RawFact, value_kind: str) -> str | None:
    form = fact.form.upper()
    if value_kind == "instant":
        if form in ANNUAL_FORMS:
            return "annual"
        if form in QUARTER_FORMS:
            return "quarterly"
        return None
    if fact.period_start is None:
        return None
    duration_days = (fact.period_end - fact.period_start).days + 1
    if form in ANNUAL_FORMS and 300 <= duration_days <= 430:
        return "annual"
    if form in QUARTER_FORMS and 60 <= duration_days <= 120:
        return "quarterly"
    if form in QUARTER_FORMS and 121 <= duration_days <= 300:
        return "ytd"
    return None


def unit_matches(unit: str, unit_kind: str) -> bool:
    normalized = unit.lower().replace("-per-", "/")
    if unit_kind == "per_share":
        return "/shares" in normalized
    if unit_kind == "currency":
        return "/" not in normalized and unit.lower() not in {"shares", "pure"}
    return True


def _lineage(fact: RawFact) -> dict[str, object]:
    return {
        "fact_id": fact.id,
        "taxonomy": fact.taxonomy,
        "concept": fact.concept,
        "accession": fact.accession,
        "filed": fact.filed.isoformat(),
        "value": str(fact.value),
        "unit": fact.unit,
    }


def normalize_direct(facts: Iterable[RawFact]) -> list[NormalizedPoint]:
    us_gaap = [fact for fact in facts if fact.taxonomy == "us-gaap"]
    results: list[NormalizedPoint] = []
    for spec in BASE_METRICS:
        if spec.code == "total_debt":
            continue
        priorities = {concept: index for index, concept in enumerate(spec.concepts)}
        selected: dict[tuple[object, ...], tuple[int, NormalizedPoint]] = {}
        conflicts: set[tuple[object, ...]] = set()
        for fact in us_gaap:
            if fact.concept not in priorities or not unit_matches(fact.unit, spec.unit_kind):
                continue
            frequency = classify_frequency(fact, spec.value_kind)
            if frequency is None:
                continue
            value = abs(fact.value) if spec.code == "capital_expenditures" else fact.value
            key = (
                frequency,
                fact.period_start,
                fact.period_end,
                fact.accession,
                fact.unit,
            )
            candidate = NormalizedPoint(
                metric_code=spec.code,
                frequency=frequency,
                period_start=fact.period_start,
                period_end=fact.period_end,
                value=value,
                unit=fact.unit,
                accession=fact.accession,
                filed=fact.filed,
                form=fact.form,
                fiscal_year=fact.fiscal_year,
                fiscal_period=fact.fiscal_period,
                lineage=[_lineage(fact)],
            )
            priority = priorities[fact.concept]
            current = selected.get(key)
            if current is None or priority < current[0]:
                selected[key] = (priority, candidate)
                conflicts.discard(key)
            elif priority == current[0] and current[1].value != candidate.value:
                conflicts.add(key)
                current[1].lineage.extend(candidate.lineage)
        for key, (_, point) in selected.items():
            if key in conflicts:
                point.quality = "ambiguous"
            results.append(point)
    results.extend(normalize_total_debt(us_gaap))
    return sorted(
        results, key=lambda point: (point.metric_code, point.period_end, point.filed or date.min)
    )


def normalize_total_debt(facts: Iterable[RawFact]) -> list[NormalizedPoint]:
    relevant = {
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
        "DebtCurrent",
        "LongTermDebtCurrent",
        "LongTermDebtNoncurrent",
        "ShortTermBorrowings",
    }
    grouped: dict[tuple[object, ...], dict[str, RawFact]] = defaultdict(dict)
    for fact in facts:
        if fact.concept not in relevant or not unit_matches(fact.unit, "currency"):
            continue
        frequency = classify_frequency(fact, "instant")
        if frequency:
            grouped[(frequency, fact.period_end, fact.accession, fact.unit)][fact.concept] = fact

    results: list[NormalizedPoint] = []
    direct_tags = (
        "LongTermDebtAndFinanceLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    )
    for (frequency, period_end, accession, unit), available in grouped.items():
        components: list[RawFact] = []
        direct = next((available[tag] for tag in direct_tags if tag in available), None)
        if direct:
            components.append(direct)
            short = available.get("ShortTermBorrowings")
            if short:
                components.append(short)
        else:
            current = available.get("DebtCurrent") or available.get("LongTermDebtCurrent")
            noncurrent = available.get("LongTermDebtNoncurrent")
            if current:
                components.append(current)
            if noncurrent:
                components.append(noncurrent)
            short = available.get("ShortTermBorrowings")
            if short and (not current or short.value != current.value):
                components.append(short)
        if not components:
            continue
        newest = max(components, key=lambda item: item.filed)
        results.append(
            NormalizedPoint(
                metric_code="total_debt",
                frequency=frequency,
                period_start=None,
                period_end=period_end,
                value=sum((item.value for item in components), Decimal(0)),
                unit=unit,
                accession=accession,
                filed=newest.filed,
                form=newest.form,
                fiscal_year=newest.fiscal_year,
                fiscal_period=newest.fiscal_period,
                is_derived=len(components) > 1,
                quality="derived" if len(components) > 1 else "reported",
                lineage=[_lineage(item) for item in components],
            )
        )
    return results


def latest_by_period(
    points: Iterable[NormalizedPoint],
) -> dict[tuple[str, str, date, str], NormalizedPoint]:
    selected: dict[tuple[str, str, date, str], NormalizedPoint] = {}
    for point in points:
        if point.quality == "ambiguous":
            continue
        key = (point.metric_code, point.frequency, point.period_end, point.unit)
        current = selected.get(key)
        ordering = (point.filed or date.min, point.accession or "")
        if current is None or ordering > (current.filed or date.min, current.accession or ""):
            selected[key] = point
    return selected


def derive_q4(points: list[NormalizedPoint]) -> list[NormalizedPoint]:
    latest = latest_by_period(points)
    derived: list[NormalizedPoint] = []
    for metric_code in ADDITIVE_FLOW_METRICS:
        annuals = [
            point
            for (metric, frequency, _, _), point in latest.items()
            if metric == metric_code and frequency == "annual" and point.period_start
        ]
        quarters = [
            point
            for (metric, frequency, _, _), point in latest.items()
            if metric == metric_code and frequency == "quarterly" and point.period_start
        ]
        for annual in annuals:
            within = sorted(
                [
                    point
                    for point in quarters
                    if point.unit == annual.unit
                    and annual.period_start <= point.period_start
                    and point.period_end < annual.period_end
                ],
                key=lambda point: point.period_end,
            )
            unique: dict[date, NormalizedPoint] = {point.period_end: point for point in within}
            selected_quarters = list(sorted(unique.values(), key=lambda point: point.period_end))[
                -3:
            ]
            if len(selected_quarters) != 3:
                continue
            if (selected_quarters[-1].period_end - annual.period_start).days > 310:
                continue
            value = annual.value - sum((point.value for point in selected_quarters), Decimal(0))
            derived.append(
                NormalizedPoint(
                    metric_code=metric_code,
                    frequency="quarterly",
                    period_start=selected_quarters[-1].period_end + timedelta(days=1),
                    period_end=annual.period_end,
                    value=abs(value) if metric_code == "capital_expenditures" else value,
                    unit=annual.unit,
                    accession=None,
                    filed=annual.filed,
                    form=annual.form,
                    fiscal_year=annual.fiscal_year,
                    fiscal_period="Q4",
                    is_derived=True,
                    quality="derived",
                    lineage=annual.lineage
                    + [item for point in selected_quarters for item in point.lineage],
                )
            )
    return derived


def derive_discrete_quarters(points: list[NormalizedPoint]) -> list[NormalizedPoint]:
    """Convert six- and nine-month 10-Q flows into discrete Q2/Q3 values."""
    latest = latest_by_period(points)
    direct_quarters = {
        (metric, end, unit)
        for metric, frequency, end, unit in latest
        if frequency == "quarterly"
    }
    derived: list[NormalizedPoint] = []
    for metric_code in ADDITIVE_FLOW_METRICS:
        by_start_unit: dict[tuple[date, str], list[NormalizedPoint]] = defaultdict(list)
        for (metric, frequency, _, unit), point in latest.items():
            if (
                metric == metric_code
                and frequency in {"quarterly", "ytd"}
                and point.period_start is not None
            ):
                by_start_unit[(point.period_start, unit)].append(point)
        for (_, unit), series in by_start_unit.items():
            series.sort(key=lambda point: point.period_end)
            for index, current in enumerate(series):
                if current.frequency != "ytd" or index == 0:
                    continue
                if (metric_code, current.period_end, unit) in direct_quarters:
                    continue
                previous = series[index - 1]
                if previous.period_end >= current.period_end:
                    continue
                value = current.value - previous.value
                derived.append(
                    NormalizedPoint(
                        metric_code=metric_code,
                        frequency="quarterly",
                        period_start=previous.period_end + timedelta(days=1),
                        period_end=current.period_end,
                        value=abs(value) if metric_code == "capital_expenditures" else value,
                        unit=unit,
                        accession=None,
                        filed=current.filed,
                        form=current.form,
                        fiscal_year=current.fiscal_year,
                        fiscal_period=current.fiscal_period,
                        is_derived=True,
                        quality="derived",
                        lineage=current.lineage + previous.lineage,
                    )
                )
    return derived


def derive_ttm(points: list[NormalizedPoint]) -> list[NormalizedPoint]:
    latest = latest_by_period(points)
    derived: list[NormalizedPoint] = []
    for metric_code in ADDITIVE_FLOW_METRICS:
        by_unit: dict[str, list[NormalizedPoint]] = defaultdict(list)
        for (metric, frequency, _, unit), point in latest.items():
            if metric == metric_code and frequency == "quarterly":
                by_unit[unit].append(point)
        for unit, series in by_unit.items():
            series.sort(key=lambda point: point.period_end)
            for index in range(3, len(series)):
                window = series[index - 3 : index + 1]
                window_start = window[0].period_start
                if window_start is None:
                    continue
                if (window[-1].period_end - window_start).days not in range(300, 431):
                    continue
                derived.append(
                    NormalizedPoint(
                        metric_code=metric_code,
                        frequency="ttm",
                        period_start=window[0].period_start,
                        period_end=window[-1].period_end,
                        value=sum((point.value for point in window), Decimal(0)),
                        unit=unit,
                        accession=None,
                        filed=max((point.filed for point in window if point.filed), default=None),
                        form=None,
                        fiscal_year=window[-1].fiscal_year,
                        fiscal_period="TTM",
                        is_derived=True,
                        quality="derived",
                        lineage=[item for point in window for item in point.lineage],
                    )
                )
    return derived


def _derived_point(
    code: str,
    left: NormalizedPoint,
    value: Decimal,
    unit: str,
    lineage: list[dict[str, object]],
) -> NormalizedPoint:
    return NormalizedPoint(
        metric_code=code,
        frequency=left.frequency,
        period_start=left.period_start,
        period_end=left.period_end,
        value=value,
        unit=unit,
        accession=None,
        filed=left.filed,
        form=None,
        fiscal_year=left.fiscal_year,
        fiscal_period=left.fiscal_period,
        is_derived=True,
        quality="derived",
        lineage=lineage,
    )


def derive_analytics(points: list[NormalizedPoint]) -> list[NormalizedPoint]:
    latest = latest_by_period(points)
    by_key = {(m, f, end, unit): point for (m, f, end, unit), point in latest.items()}
    derived: list[NormalizedPoint] = []

    def pair(numerator: str, denominator: str, output: str, multiplier: Decimal) -> None:
        for (metric, frequency, end, unit), left in list(by_key.items()):
            if metric != numerator:
                continue
            right = by_key.get((denominator, frequency, end, unit))
            if right and right.value != 0:
                derived.append(
                    _derived_point(
                        output,
                        left,
                        left.value / right.value * multiplier,
                        "percent" if multiplier == 100 else "ratio",
                        left.lineage + right.lineage,
                    )
                )

    for (metric, frequency, end, unit), ocf in list(by_key.items()):
        if metric != "operating_cash_flow":
            continue
        capex = by_key.get(("capital_expenditures", frequency, end, unit))
        if capex:
            derived.append(
                _derived_point(
                    "free_cash_flow",
                    ocf,
                    ocf.value - capex.value,
                    unit,
                    ocf.lineage + capex.lineage,
                )
            )

    pair("gross_profit", "revenue", "gross_margin", Decimal(100))
    pair("operating_income", "revenue", "operating_margin", Decimal(100))
    pair("net_income", "revenue", "net_margin", Decimal(100))

    combined = points + derived
    latest_combined = latest_by_period(combined)
    for (metric, frequency, end, unit), fcf in list(latest_combined.items()):
        if metric != "free_cash_flow":
            continue
        revenue = latest_combined.get(("revenue", frequency, end, unit))
        if revenue and revenue.value != 0:
            derived.append(
                _derived_point(
                    "fcf_margin",
                    fcf,
                    fcf.value / revenue.value * 100,
                    "percent",
                    fcf.lineage + revenue.lineage,
                )
            )

    pair("current_assets", "current_liabilities", "current_ratio", Decimal(1))
    pair("total_debt", "total_equity", "debt_to_equity", Decimal(1))

    for source, output in (
        ("revenue", "revenue_yoy"),
        ("net_income", "net_income_yoy"),
        ("eps_diluted", "eps_yoy"),
    ):
        series_by_frequency_unit: dict[tuple[str, str], list[NormalizedPoint]] = defaultdict(list)
        for (metric, frequency, _, unit), point in latest.items():
            if metric == source:
                series_by_frequency_unit[(frequency, unit)].append(point)
        for (frequency, _), series in series_by_frequency_unit.items():
            series.sort(key=lambda point: point.period_end)
            lag = 1 if frequency == "annual" else 4
            for index in range(lag, len(series)):
                current, previous = series[index], series[index - lag]
                if previous.value != 0:
                    derived.append(
                        _derived_point(
                            output,
                            current,
                            (current.value - previous.value) / abs(previous.value) * 100,
                            "percent",
                            current.lineage + previous.lineage,
                        )
                    )

    latest_balances = latest_by_period(points)
    for income_code, balance_code, output in (
        ("net_income", "total_assets", "roa"),
        ("net_income", "total_equity", "roe"),
    ):
        incomes = [
            point
            for (metric, frequency, _, _), point in latest_balances.items()
            if metric == income_code and frequency in {"annual", "ttm"}
        ]
        for income in incomes:
            balances = sorted(
                [
                    point
                    for (metric, _, end, unit), point in latest_balances.items()
                    if metric == balance_code and unit == income.unit and end <= income.period_end
                ],
                key=lambda point: point.period_end,
            )
            if len(balances) < 2:
                continue
            ending = balances[-1]
            beginning = next(
                (
                    point
                    for point in reversed(balances[:-1])
                    if 300 <= (ending.period_end - point.period_end).days <= 430
                ),
                None,
            )
            if beginning:
                average = (beginning.value + ending.value) / 2
                if average != 0:
                    derived.append(
                        _derived_point(
                            output,
                            income,
                            income.value / average * 100,
                            "percent",
                            income.lineage + beginning.lineage + ending.lineage,
                        )
                    )
    return derived


def normalize_all(facts: Iterable[RawFact]) -> list[NormalizedPoint]:
    direct_with_ytd = normalize_direct(facts)
    discrete = derive_discrete_quarters(direct_with_ytd)
    direct = [point for point in direct_with_ytd if point.frequency != "ytd"]
    q4 = derive_q4(direct + discrete)
    with_quarters = direct + discrete + q4
    ttm = derive_ttm(with_quarters)
    analytics = derive_analytics(with_quarters + ttm)
    unique: dict[tuple[str, str, date, str, str, str], NormalizedPoint] = {}
    for point in with_quarters + ttm + analytics:
        key = (
            point.metric_code,
            point.frequency,
            point.period_end,
            point.unit,
            point.accession_key,
            point.mapping_version,
        )
        current = unique.get(key)
        if current is None:
            unique[key] = point
        elif current.value != point.value:
            current.quality = "ambiguous"
            current.lineage.extend(point.lineage)
    return list(unique.values())
