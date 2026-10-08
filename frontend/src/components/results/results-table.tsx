"use client";

import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  tableFeatures,
  useTable,
  type SortFn,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Download } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Cell, ResultColumn } from "@/lib/api/types";
import { toNumber } from "@/lib/chart";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatCell } from "@/lib/format";
import { cn } from "@/lib/utils";

type Row = Cell[];

const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() });
const helper = createColumnHelper<typeof features, Row>();

/** Numbers numerically, everything else as text; empty cells sort first (last when descending). */
export function compareCells(a: Cell, b: Cell): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? -1 : 1;
  const x = toNumber(a);
  const y = toNumber(b);
  if (x !== null && y !== null) return x - y;
  return formatCell(a).localeCompare(formatCell(b), undefined, { numeric: true });
}

const byCell: SortFn<typeof features, Row> = (a, b, id) =>
  compareCells(a.getValue<Cell>(id), b.getValue<Cell>(id));

const NUMERIC = new Set(["int2", "int4", "int8", "numeric", "float4", "float8", "money"]);

interface Props {
  columns: ResultColumn[];
  rows: Row[];
  truncated: boolean;
  fileName: string;
}

export function ResultsTable({ columns, rows, truncated, fileName }: Props) {
  const tableColumns = useMemo(
    () =>
      helper.columns(
        columns.map((column, index) =>
          helper.accessor((row) => row[index] ?? null, {
            id: `c${index}`,
            header: column.name,
            sortFn: byCell,
            meta: { numeric: NUMERIC.has(column.type) },
          }),
        ),
      ),
    [columns],
  );
  const table = useTable({ features, columns: tableColumns, data: rows });

  return (
    <div className="grid grid-cols-1 gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {rows.length.toLocaleString("en-US")} {rows.length === 1 ? "row" : "rows"}
          {truncated ? " (first rows only: the result was capped)" : ""}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => downloadCsv(fileName, toCsv(columns, rows))}
          disabled={rows.length === 0}
        >
          <Download aria-hidden /> Export CSV
        </Button>
      </div>
      <div className="max-h-[28rem] overflow-auto rounded-lg border">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-background">
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  const numeric = isNumeric(header.column.columnDef.meta);
                  return (
                    <TableHead
                      key={header.id}
                      aria-sort={
                        sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                      }
                      className={cn(numeric && "text-right")}
                    >
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={cn(
                          "inline-flex items-center gap-1 font-medium hover:text-foreground",
                          numeric && "flex-row-reverse",
                        )}
                      >
                        <table.FlexRender header={header} />
                        {sorted === "asc" ? (
                          <ArrowUp className="size-3.5" aria-hidden />
                        ) : sorted === "desc" ? (
                          <ArrowDown className="size-3.5" aria-hidden />
                        ) : (
                          <ArrowUpDown className="size-3.5 opacity-40" aria-hidden />
                        )}
                      </button>
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getAllCells().map((cell) => {
                  const value = cell.getValue<Cell>();
                  return (
                    <TableCell
                      key={cell.id}
                      className={cn(
                        "max-w-[24rem] truncate",
                        typeof value === "number" && "text-right tabular-nums",
                        value === null && "text-muted-foreground italic",
                      )}
                      title={formatCell(value)}
                    >
                      {value === null ? "null" : formatCell(value)}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function isNumeric(meta: unknown): boolean {
  return typeof meta === "object" && meta !== null && "numeric" in meta && meta.numeric === true;
}
