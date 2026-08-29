from dataclasses import dataclass

MAPPING_VERSION = "1.1.0"


@dataclass(frozen=True)
class MetricSpec:
    code: str
    name_en: str
    name_zh: str
    statement: str
    value_kind: str
    unit_kind: str
    concepts: tuple[str, ...] = ()
    description: str = ""
    derived: bool = False


BASE_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "revenue",
        "Revenue",
        "營收",
        "income",
        "duration",
        "currency",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "Revenues",
        ),
        "公司於該期間認列的營業收入。",
    ),
    MetricSpec(
        "gross_profit",
        "Gross Profit",
        "毛利",
        "income",
        "duration",
        "currency",
        ("GrossProfit",),
        "營收減除直接營業成本。金融業通常不適用。",
    ),
    MetricSpec(
        "operating_income",
        "Operating Income",
        "營業利益",
        "income",
        "duration",
        "currency",
        ("OperatingIncomeLoss",),
        "公司本業營運產生的利益或損失。",
    ),
    MetricSpec(
        "net_income",
        "Net Income",
        "淨利",
        "income",
        "duration",
        "currency",
        ("NetIncomeLoss", "ProfitLoss"),
        "歸屬於公司整體的當期淨利或淨損。",
    ),
    MetricSpec(
        "eps_basic",
        "Basic EPS",
        "基本每股盈餘",
        "income",
        "duration",
        "per_share",
        ("EarningsPerShareBasic",),
    ),
    MetricSpec(
        "eps_diluted",
        "Diluted EPS",
        "稀釋每股盈餘",
        "income",
        "duration",
        "per_share",
        ("EarningsPerShareDiluted",),
    ),
    MetricSpec(
        "cash_and_equivalents",
        "Cash & Equivalents",
        "現金及約當現金",
        "balance",
        "instant",
        "currency",
        ("CashAndCashEquivalentsAtCarryingValue", "CashAndDueFromBanks"),
    ),
    MetricSpec(
        "current_assets",
        "Current Assets",
        "流動資產",
        "balance",
        "instant",
        "currency",
        ("AssetsCurrent",),
    ),
    MetricSpec(
        "total_assets",
        "Total Assets",
        "資產總額",
        "balance",
        "instant",
        "currency",
        ("Assets",),
    ),
    MetricSpec(
        "current_liabilities",
        "Current Liabilities",
        "流動負債",
        "balance",
        "instant",
        "currency",
        ("LiabilitiesCurrent",),
    ),
    MetricSpec(
        "total_liabilities",
        "Total Liabilities",
        "負債總額",
        "balance",
        "instant",
        "currency",
        ("Liabilities",),
    ),
    MetricSpec(
        "total_equity",
        "Total Equity",
        "權益總額",
        "balance",
        "instant",
        "currency",
        (
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "StockholdersEquity",
        ),
    ),
    MetricSpec(
        "total_debt",
        "Total Debt",
        "總債務",
        "balance",
        "instant",
        "currency",
        (
            "LongTermDebtAndFinanceLeaseObligations",
            "LongTermDebtAndCapitalLeaseObligations",
            "LongTermDebt",
        ),
        "長短期有息債務合計；依申報 tag 可用性採優先公式。",
    ),
    MetricSpec(
        "operating_cash_flow",
        "Operating Cash Flow",
        "營業現金流",
        "cash_flow",
        "duration",
        "currency",
        ("NetCashProvidedByUsedInOperatingActivities",),
    ),
    MetricSpec(
        "capital_expenditures",
        "Capital Expenditures",
        "資本支出",
        "cash_flow",
        "duration",
        "currency",
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsForAdditionsToPropertyPlantAndEquipment",
        ),
        "購置不動產、廠房及設備的現金支出，以正數表示。",
    ),
)


DERIVED_METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "free_cash_flow",
        "Free Cash Flow",
        "自由現金流",
        "cash_flow",
        "duration",
        "currency",
        derived=True,
    ),
    MetricSpec(
        "revenue_yoy", "Revenue YoY", "營收年增率", "ratios", "duration", "percent", derived=True
    ),
    MetricSpec(
        "net_income_yoy",
        "Net Income YoY",
        "淨利年增率",
        "ratios",
        "duration",
        "percent",
        derived=True,
    ),
    MetricSpec(
        "eps_yoy",
        "Diluted EPS YoY",
        "稀釋 EPS 年增率",
        "ratios",
        "duration",
        "percent",
        derived=True,
    ),
    MetricSpec(
        "gross_margin", "Gross Margin", "毛利率", "ratios", "duration", "percent", derived=True
    ),
    MetricSpec(
        "operating_margin",
        "Operating Margin",
        "營業利益率",
        "ratios",
        "duration",
        "percent",
        derived=True,
    ),
    MetricSpec("net_margin", "Net Margin", "淨利率", "ratios", "duration", "percent", derived=True),
    MetricSpec(
        "fcf_margin", "FCF Margin", "自由現金流率", "ratios", "duration", "percent", derived=True
    ),
    MetricSpec(
        "current_ratio", "Current Ratio", "流動比率", "ratios", "instant", "ratio", derived=True
    ),
    MetricSpec(
        "debt_to_equity", "Debt to Equity", "負債權益比", "ratios", "instant", "ratio", derived=True
    ),
    MetricSpec(
        "roa", "Return on Assets", "資產報酬率", "ratios", "duration", "percent", derived=True
    ),
    MetricSpec(
        "roe", "Return on Equity", "權益報酬率", "ratios", "duration", "percent", derived=True
    ),
)

ALL_METRICS = BASE_METRICS + DERIVED_METRICS
METRICS_BY_CODE = {metric.code: metric for metric in ALL_METRICS}
ADDITIVE_FLOW_METRICS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capital_expenditures",
}
