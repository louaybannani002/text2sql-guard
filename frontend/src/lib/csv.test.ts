import { csvCell, downloadCsv, toCsv } from "./csv";

describe("csvCell", () => {
  it.each([
    [null, ""],
    [42, "42"],
    [-3.5, "-3.5"],
    [true, "true"],
    ["plain", "plain"],
    ['say "hi"', '"say ""hi"""'],
    ["a,b", '"a,b"'],
    ["line\nbreak", '"line\nbreak"'],
    [{ a: 1 }, '"{""a"":1}"'],
  ])("%j -> %s", (input, expected) => {
    expect(csvCell(input)).toBe(expected);
  });

  it.each(["=1+1", "+cmd", "-2+3", "@SUM(A1)"])("neutralises formula-like text %s", (text) => {
    expect(csvCell(text).startsWith("'") || csvCell(text).startsWith("\"'")).toBe(true);
  });
});

describe("toCsv", () => {
  it("writes a header and CRLF-separated rows", () => {
    const csv = toCsv(
      [
        { name: "status", type: "text" },
        { name: "n", type: "int8" },
      ],
      [
        ["delivered", 2],
        [null, 1],
      ],
    );
    expect(csv).toBe("status,n\r\ndelivered,2\r\n,1\r\n");
  });
});

describe("downloadCsv", () => {
  it("downloads a UTF-8 blob with a BOM", async () => {
    const createObjectURL = vi.fn((blob: Blob) => {
      void blob;
      return "blob:x";
    });
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    downloadCsv("out.csv", "a\r\n");

    expect(click).toHaveBeenCalledOnce();
    const blob = createObjectURL.mock.calls[0]?.[0];
    expect(blob?.type).toBe("text/csv;charset=utf-8");
    const bytes = new Uint8Array(await blob!.arrayBuffer());
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:x");
  });
});
