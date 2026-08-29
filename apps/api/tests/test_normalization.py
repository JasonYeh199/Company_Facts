from datetime import date
from decimal import Decimal

from company_facts.normalization import RawFact, normalize_all, normalize_direct


def fact(
    concept: str,
    value: int | str,
    *,
    start: str | None = "2024-01-01",
    end: str = "2024-12-31",
    accession: str = "0000000001-25-000001",
    form: str = "10-K",
    filed: str = "2025-02-01",
    unit: str = "USD",
    fact_id: int = 1,
) -> RawFact:
    return RawFact(
        id=fact_id,
        taxonomy="us-gaap",
        concept=concept,
        unit=unit,
        value=Decimal(value),
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end),
        accession=accession,
        form=form,
        filed=date.fromisoformat(filed),
        fiscal_year=2024,
        fiscal_period="FY",
    )


def test_mapping_priority_and_ambiguity() -> None:
    points = normalize_direct(
        [
            fact("Revenues", 90, fact_id=1),
            fact("RevenueFromContractWithCustomerExcludingAssessedTax", 100, fact_id=2),
            fact(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                101,
                fact_id=3,
            ),
        ]
    )
    revenue = [point for point in points if point.metric_code == "revenue"]
    assert len(revenue) == 1
    assert revenue[0].value == 100
    assert revenue[0].quality == "ambiguous"
    assert len(revenue[0].lineage) == 2


def test_q4_ttm_free_cash_flow_and_ratios() -> None:
    facts = [
        fact("RevenueFromContractWithCustomerExcludingAssessedTax", 100),
        fact("GrossProfit", 40),
        fact("OperatingIncomeLoss", 25),
        fact("NetIncomeLoss", 20),
        fact("NetCashProvidedByUsedInOperatingActivities", 30),
        fact("PaymentsToAcquirePropertyPlantAndEquipment", 10),
    ]
    for index, (start, end, revenue) in enumerate(
        [
            ("2024-01-01", "2024-03-31", 20),
            ("2024-04-01", "2024-06-30", 25),
            ("2024-07-01", "2024-09-30", 25),
        ],
        start=10,
    ):
        facts.append(
            fact(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                revenue,
                start=start,
                end=end,
                accession=f"0000000001-24-0000{index}",
                form="10-Q",
                filed=end,
                fact_id=index,
            )
        )
    points = normalize_all(facts)
    q4 = next(
        point
        for point in points
        if point.metric_code == "revenue"
        and point.frequency == "quarterly"
        and point.period_end == date(2024, 12, 31)
    )
    assert q4.value == 30
    assert q4.is_derived
    ttm = next(
        point for point in points if point.metric_code == "revenue" and point.frequency == "ttm"
    )
    assert ttm.value == 100
    fcf = next(
        point
        for point in points
        if point.metric_code == "free_cash_flow" and point.frequency == "annual"
    )
    assert fcf.value == 20
    gross_margin = next(
        point
        for point in points
        if point.metric_code == "gross_margin" and point.frequency == "annual"
    )
    assert gross_margin.value == 40


def test_total_debt_sums_short_term_borrowings() -> None:
    points = normalize_direct(
        [
            fact("LongTermDebt", 80, start=None),
            fact("ShortTermBorrowings", 20, start=None, fact_id=2),
        ]
    )
    debt = next(point for point in points if point.metric_code == "total_debt")
    assert debt.value == 100
    assert debt.is_derived


def test_cumulative_cash_flows_become_discrete_quarters_without_exposing_ytd() -> None:
    facts = [
        fact(
            "NetCashProvidedByUsedInOperatingActivities",
            10,
            start="2024-01-01",
            end="2024-03-31",
            form="10-Q",
            filed="2024-05-01",
            fact_id=1,
        ),
        fact(
            "NetCashProvidedByUsedInOperatingActivities",
            25,
            start="2024-01-01",
            end="2024-06-30",
            form="10-Q",
            filed="2024-08-01",
            fact_id=2,
        ),
        fact(
            "NetCashProvidedByUsedInOperatingActivities",
            45,
            start="2024-01-01",
            end="2024-09-30",
            form="10-Q",
            filed="2024-11-01",
            fact_id=3,
        ),
    ]

    points = normalize_all(facts)
    quarters = sorted(
        (
            point
            for point in points
            if point.metric_code == "operating_cash_flow" and point.frequency == "quarterly"
        ),
        key=lambda point: point.period_end,
    )

    assert [point.value for point in quarters] == [Decimal(10), Decimal(15), Decimal(20)]
    assert [point.is_derived for point in quarters] == [False, True, True]
    assert all(point.frequency != "ytd" for point in points)


def test_multi_currency_derived_revisions_have_distinct_lineage_keys() -> None:
    facts = []
    fact_id = 1
    for unit, previous, current in (("USD", 100, 120), ("EUR", 80, 100)):
        facts.extend(
            [
                fact(
                    "Revenues",
                    previous,
                    start="2023-01-01",
                    end="2023-12-31",
                    accession=f"0000000001-24-00000{fact_id}",
                    filed="2024-02-01",
                    unit=unit,
                    fact_id=fact_id,
                ),
                fact(
                    "Revenues",
                    current,
                    start="2024-01-01",
                    end="2024-12-31",
                    accession=f"0000000001-25-00000{fact_id + 1}",
                    filed="2025-02-01",
                    unit=unit,
                    fact_id=fact_id + 1,
                ),
            ]
        )
        fact_id += 2

    points = normalize_all(facts)
    yoy = [
        point
        for point in points
        if point.metric_code == "revenue_yoy" and point.period_end == date(2024, 12, 31)
    ]

    assert len(yoy) == 2
    assert len({point.accession_key for point in yoy}) == 2
