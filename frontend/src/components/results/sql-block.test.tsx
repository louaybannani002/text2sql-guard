import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SqlBlock } from "@/components/results/sql-block";

const SQL = "SELECT o.order_status FROM shop.orders AS o WHERE o.note = '<b>x</b>'";

describe("SqlBlock", () => {
  it("highlights SQL without injecting markup from it", () => {
    const { container } = render(<SqlBlock sql={SQL} />);
    expect(container.querySelector(".hljs-keyword")).toHaveTextContent("SELECT");
    expect(container.querySelector("b")).toBeNull(); // the string literal stays text
    expect(container.querySelector("code")).toHaveTextContent(SQL);
  });

  it("copies the SQL and says so", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<SqlBlock sql={SQL} />);
    await user.click(screen.getByRole("button", { name: "Copy SQL" }));
    expect(writeText).toHaveBeenCalledWith(SQL);
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
  });

  it("reports a blocked clipboard", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    render(<SqlBlock sql={SQL} />);
    await user.click(screen.getByRole("button", { name: "Copy SQL" }));
    expect(screen.getByRole("status")).toHaveTextContent("Couldn't copy");
  });
});
