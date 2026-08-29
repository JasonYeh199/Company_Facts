export type Scale = "raw" | "thousand" | "million" | "billion";

const divisors: Record<Scale, number> = {
  raw: 1,
  thousand: 1_000,
  million: 1_000_000,
  billion: 1_000_000_000,
};

export function formatValue(
  value: string,
  unit: string,
  scale: Scale = "million",
): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (unit === "percent") {
    return `${number.toLocaleString("zh-TW", { maximumFractionDigits: 1 })}%`;
  }
  if (unit === "ratio") {
    return `${number.toLocaleString("zh-TW", { maximumFractionDigits: 2 })}×`;
  }
  if (unit.toLowerCase().includes("/shares")) {
    return number.toLocaleString("zh-TW", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  return (number / divisors[scale]).toLocaleString("zh-TW", {
    maximumFractionDigits: 2,
  });
}

export function unitLabel(unit: string, scale: Scale): string {
  if (
    unit === "percent" ||
    unit === "ratio" ||
    unit.toLowerCase().includes("/shares")
  ) {
    return unit;
  }
  const suffix = {
    raw: "",
    thousand: "千",
    million: "百萬",
    billion: "十億",
  }[scale];
  return suffix ? `${unit} ${suffix}` : unit;
}

export function tickerOf(company: { tickers: { ticker: string }[] }): string {
  return company.tickers[0]?.ticker ?? "—";
}
