import type { Cell, ResultColumn } from "./api/types";
import { MAX_BARS, detectChart, toNumber } from "./chart";

const col = (name: string, type: string): ResultColumn => ({ name, type });

describe("detectChart", () => {
  it("draws a line for a date column and numeric columns, sorted by date", () => {
    const spec = detectChart(
      [col("month", "timestamptz"), col("revenue", "numeric"), col("orders", "int8")],
      [
        ["2017-02-01T00:00:00+00:00", 2500.5, 20],
        ["2017-01-01T00:00:00+00:00", "1234.50", 10],
      ],
    );
    expect(spec?.kind).toBe("line");
    expect(spec?.ys).toEqual([1]); // orders (~20) would be flattened next to revenue (~2,500)
    expect(spec?.points[0]).toEqual({ month__0: "2017-01-01T00:00:00+00:00", revenue__1: 1234.5 });
  });

  it("only plots extra series of a comparable magnitude", () => {
    const spec = detectChart(
      [col("payment_type", "text"), col("payments", "int8"), col("share_pct", "numeric"), col("value", "numeric")],
      [
        ["credit_card", 76795, 73.9, 120000],
        ["boleto", 19784, 19, 30000],
      ],
    );
    expect(spec?.ys).toEqual([1, 3]);
  });

  it("recognises ISO dates in text columns (e.g. to_char months)", () => {
    expect(detectChart([col("month", "text"), col("n", "int8")], [["2017-01", 1], ["2017-02", 2]])?.kind).toBe(
      "line",
    );
  });

  it("uses an integer year/month first column as the time axis", () => {
    const spec = detectChart([col("order_year", "int4"), col("orders", "int8")], [[2017, 5], [2018, 7]]);
    expect(spec).toMatchObject({ kind: "line", x: 0, ys: [1] });
  });

  it("draws bars for a category and a number, capped", () => {
    const rows: Cell[][] = Array.from({ length: 30 }, (_, i) => [`cat ${i}`, i]);
    const spec = detectChart([col("category", "text"), col("revenue", "numeric")], rows);
    expect(spec?.kind).toBe("bar");
    expect(spec?.points).toHaveLength(MAX_BARS);
  });

  it.each([
    ["a single row", [col("status", "text"), col("n", "int8")], [["delivered", 1]]],
    ["no numeric column", [col("a", "text"), col("b", "text")], [["x", "y"], ["z", "w"]]],
    ["only numbers", [col("price", "numeric"), col("freight", "numeric")], [[1, 2], [3, 4]]],
    ["one column", [col("n", "int8")], [[1], [2]]],
    ["too many categories", [col("id", "text"), col("n", "int8")], Array.from({ length: 60 }, (_, i) => [`id${i}`, i])],
  ] as [string, ResultColumn[], Cell[][]][])("draws nothing for %s", (_name, columns, rows) => {
    expect(detectChart(columns, rows)).toBeNull();
  });

  it("ignores nulls when classifying columns", () => {
    const spec = detectChart([col("state", "text"), col("days", "numeric")], [["SP", 8.3], ["RJ", null], [null, 4]]);
    expect(spec?.kind).toBe("bar");
    expect(spec?.points[2]).toEqual({ state__0: "(empty)", days__1: 4 });
  });
});

describe("toNumber", () => {
  it.each([
    [3, 3],
    ["12.50", 12.5],
    ["-7", -7],
    ["1e5", null],
    ["abc", null],
    [null, null],
    [true, null],
  ] as [Cell, number | null][])("%j -> %j", (input, expected) => {
    expect(toNumber(input)).toBe(expected);
  });
});
