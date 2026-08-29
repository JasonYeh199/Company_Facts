import { describe, expect, it } from "vitest";

import { formatValue, unitLabel } from "./format";

describe("financial formatting", () => {
  it("formats currency-scaled values without losing the source unit", () => {
    expect(formatValue("391035000000", "USD", "billion")).toBe("391.04");
    expect(unitLabel("USD", "billion")).toBe("USD 十億");
  });

  it("formats percentages, ratios and per-share values explicitly", () => {
    expect(formatValue("27.419", "percent")).toBe("27.4%");
    expect(formatValue("1.852", "ratio")).toBe("1.85×");
    expect(formatValue("6.08", "USD/shares")).toBe("6.08");
  });
});

