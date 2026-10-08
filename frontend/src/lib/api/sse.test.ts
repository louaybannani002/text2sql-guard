import { SseParser, type SseMessage } from "./sse";

function parse(chunks: string[], end = true): SseMessage[] {
  const messages: SseMessage[] = [];
  const parser = new SseParser((m) => messages.push(m));
  for (const chunk of chunks) parser.push(chunk);
  if (end) parser.end();
  return messages;
}

describe("SseParser", () => {
  it("parses events, data and ids", () => {
    expect(parse(['event: query\nid: 0\ndata: {"a":1}\n\n'])).toEqual([
      { event: "query", data: '{"a":1}', id: "0" },
    ]);
  });

  it("handles chunks split anywhere, including inside CRLF", () => {
    const text = "event: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2\r\n\r\n";
    const chunks = text.split(""); // one character at a time
    expect(parse(chunks).map((m) => [m.event, m.data])).toEqual([
      ["a", "1"],
      ["b", "2"],
    ]);
  });

  it("joins multi-line data and defaults the event name", () => {
    expect(parse(["data: line 1\ndata: line 2\n\n"])).toEqual([
      { event: "message", data: "line 1\nline 2", id: null },
    ]);
  });

  it("ignores comments and unknown fields, keeps values without a space", () => {
    expect(parse([": keep-alive\nretry: 10\nevent:x\ndata:y\n\n"])).toEqual([
      { event: "x", data: "y", id: null },
    ]);
  });

  it("dispatches nothing until the blank line, then flushes on end", () => {
    expect(parse(["event: a\ndata: 1\n"], false)).toEqual([]);
    expect(parse(["event: a\ndata: 1"])).toEqual([{ event: "a", data: "1", id: null }]);
  });

  it("skips events without data", () => {
    expect(parse(["event: ping\n\n"])).toEqual([]);
  });
});
