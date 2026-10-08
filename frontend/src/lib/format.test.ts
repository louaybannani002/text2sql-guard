import { formatCell, formatCost, formatMs, formatNumber } from "./format";

describe("format", () => {
  it.each([
    [4, "4 ms"],
    [999.6, "1000 ms"],
    [1530, "1.53 s"],
    [12_345, "12.3 s"],
  ])("formatMs(%d)", (ms, text) => {
    expect(formatMs(ms)).toBe(text);
  });

  it.each([
    [null, "unknown"],
    [0, "$0"],
    [0.00001, "<$0.0001"],
    [0.0097, "$0.0097"],
  ])("formatCost(%j)", (usd, text) => {
    expect(formatCost(usd)).toBe(text);
  });

  it("formats numbers and cells", () => {
    expect(formatNumber(96478)).toBe("96,478");
    expect(formatNumber(8.3333)).toBe("8.33");
    expect(formatCell(null)).toBe("");
    expect(formatCell(false)).toBe("false");
    expect(formatCell([1, "a"])).toBe('[1,"a"]');
    expect(formatCell("2017-01-01")).toBe("2017-01-01");
  });
});
