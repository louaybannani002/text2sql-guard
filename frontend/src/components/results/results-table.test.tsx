import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ResultsTable, compareCells } from "@/components/results/results-table";
import type { Cell } from "@/lib/api/types";

const columns = [
  { name: "state", type: "text" },
  { name: "orders", type: "int8" },
];
const rows: Cell[][] = [
  ["SP", 41746],
  ["RJ", 12852],
  ["AC", 81],
  [null, 5],
];

function firstColumn(): string[] {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]?.textContent ?? "");
}

describe("ResultsTable", () => {
  it("sorts by a column when its header is clicked", async () => {
    const user = userEvent.setup();
    render(<ResultsTable columns={columns} rows={rows} truncated={false} fileName="x.csv" />);
    expect(firstColumn()).toEqual(["SP", "RJ", "AC", "null"]);

    const header = screen.getByRole("button", { name: /orders/ });
    await user.click(header);
    const sortedBy = () => screen.getByRole("columnheader", { name: /orders/ }).getAttribute("aria-sort");
    const first = sortedBy();
    expect(first === "ascending" || first === "descending").toBe(true);
    expect(firstColumn()).toEqual(first === "ascending" ? ["null", "AC", "RJ", "SP"] : ["SP", "RJ", "AC", "null"]);

    await user.click(header);
    expect(sortedBy()).toBe(first === "ascending" ? "descending" : "ascending");
  });

  it("right-aligns numbers and says when the result was capped", () => {
    render(<ResultsTable columns={columns} rows={rows} truncated fileName="x.csv" />);
    expect(screen.getByText("41,746")).toHaveClass("text-right");
    expect(screen.getByText(/the result was capped/)).toBeInTheDocument();
  });
});

describe("compareCells", () => {
  it("orders numbers numerically, text naturally and nulls first", () => {
    const values: Cell[] = ["item 10", 3, null, "item 2", "1000.5", 20];
    expect([...values].sort(compareCells)).toEqual([null, 3, 20, "1000.5", "item 2", "item 10"]);
  });
});
