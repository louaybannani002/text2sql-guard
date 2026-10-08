/**
 * Picks a chart for a result, or none: a line chart for a date column + numeric columns,
 * a bar chart for a category column + a numeric column. Never guesses beyond that.
 */
import type { Cell, ResultColumn } from "./api/types";

export type ChartSpec =
  | { kind: "line"; x: number; ys: number[]; points: ChartPoint[] }
  | { kind: "bar"; x: number; ys: number[]; points: ChartPoint[] };

export type ChartPoint = Record<string, string | number | null>;

const NUMERIC_TYPES = new Set([
  "int2", "int4", "int8", "numeric", "float4", "float8", "money", "oid",
]);
const DATE_TYPES = new Set(["date", "timestamp", "timestamptz"]);
const TEXT_TYPES = new Set(["text", "varchar", "bpchar", "char", "name", "bool", "uuid"]);
// '2017-01', '2017-01-15', '2017-01-15T10:00:00', '2017-01-15 10:00:00+00'
const ISO_DATE = /^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}(:?\d{2})?|Z)?)?$/;
const TIME_NAME = /(^|_)(year|month|week|day|date|quarter|hour)s?(_|$)/i;

export const MAX_BARS = 20;
const MAX_SERIES = 3;
const MAX_CATEGORIES = 50;
const SCALE_RATIO = 10;

export function toNumber(value: Cell): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "" && /^-?\d+(\.\d+)?$/.test(value.trim())) {
    return Number(value);
  }
  return null;
}

function values(rows: Cell[][], index: number): Cell[] {
  return rows.map((row) => row[index] ?? null).filter((v) => v !== null);
}

function isNumeric(column: ResultColumn, rows: Cell[][], index: number): boolean {
  const present = values(rows, index);
  if (present.length === 0) return false;
  if (NUMERIC_TYPES.has(column.type)) return present.every((v) => toNumber(v) !== null);
  return present.every((v) => typeof v === "number");
}

function isDate(column: ResultColumn, rows: Cell[][], index: number): boolean {
  const present = values(rows, index);
  if (present.length === 0) return false;
  if (DATE_TYPES.has(column.type)) return true;
  return present.every((v) => typeof v === "string" && ISO_DATE.test(v));
}

function isCategory(column: ResultColumn, rows: Cell[][], index: number): boolean {
  const present = values(rows, index);
  if (present.length === 0 || !TEXT_TYPES.has(column.type)) return false;
  return new Set(present.map(String)).size <= MAX_CATEGORIES;
}

export function detectChart(columns: ResultColumn[], rows: Cell[][]): ChartSpec | null {
  if (rows.length < 2 || columns.length < 2) return null;
  const numeric = columns.map((c, i) => isNumeric(c, rows, i));
  const date = columns.findIndex((c, i) => !numeric[i] && isDate(c, rows, i));
  // An integer "year"/"month" column is a time axis too, when it is the first column.
  const first = columns[0];
  const timeLike = first && numeric[0] && TIME_NAME.test(first.name) ? 0 : -1;
  const x = date !== -1 ? date : timeLike;

  if (x !== -1) {
    const ys = sameScale(rows, numericIndexes(numeric, x)).slice(0, MAX_SERIES);
    if (ys.length === 0) return null;
    const points = rows
      .map((row) => point(columns, row, x, ys))
      .sort((a, b) => String(a[key(columns, x)]).localeCompare(String(b[key(columns, x)])));
    return { kind: "line", x, ys, points };
  }

  const category = columns.findIndex((c, i) => !numeric[i] && isCategory(c, rows, i));
  if (category === -1) return null;
  const ys = sameScale(rows, numericIndexes(numeric, category)).slice(0, 2);
  if (ys.length === 0) return null;
  const points = rows.slice(0, MAX_BARS).map((row) => point(columns, row, category, ys));
  return { kind: "bar", x: category, ys, points };
}

/**
 * The first numeric column, plus the others of a comparable magnitude: on one axis, orders
 * (~76,000) would flatten a percentage (~74) into an invisible line.
 */
function sameScale(rows: Cell[][], indexes: number[]): number[] {
  const [first, ...rest] = indexes;
  if (first === undefined) return [];
  const peak = (i: number) => Math.max(...rows.map((row) => Math.abs(toNumber(row[i] ?? null) ?? 0)));
  const base = peak(first);
  return [first, ...rest.filter((i) => {
    const other = peak(i);
    return base === 0 || other === 0 ? base === other : Math.max(base, other) / Math.min(base, other) <= SCALE_RATIO;
  })];
}

function numericIndexes(numeric: boolean[], except: number): number[] {
  return numeric.flatMap((isNum, i) => (isNum && i !== except ? [i] : []));
}

/** Recharts data keys: column names, made unique by position. */
export function key(columns: ResultColumn[], index: number): string {
  return `${columns[index]?.name ?? "col"}__${index}`;
}

function point(columns: ResultColumn[], row: Cell[], x: number, ys: number[]): ChartPoint {
  const xValue = row[x] ?? null;
  const result: ChartPoint = {
    [key(columns, x)]: xValue === null ? "(empty)" : typeof xValue === "number" ? xValue : String(xValue),
  };
  for (const y of ys) result[key(columns, y)] = toNumber(row[y] ?? null);
  return result;
}
