/** CSV export of a result (RFC 4180), safe to open in a spreadsheet. */
import type { Cell, ResultColumn } from "./api/types";

// A cell starting with one of these is a formula in Excel/Sheets ("CSV injection").
const FORMULA_START = /^[=+\-@\t\r]/;

export function csvCell(value: Cell): string {
  if (value === null) return "";
  let text = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: ResultColumn[], rows: Cell[][]): string {
  const lines = [columns.map((c) => csvCell(c.name)), ...rows.map((row) => row.map(csvCell))];
  return lines.map((line) => line.join(",")).join("\r\n") + "\r\n";
}

/** Trigger a download in the browser (BOM so Excel reads UTF-8 correctly). */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
