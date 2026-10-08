/**
 * Incremental parser for a `text/event-stream` body (the WHATWG format: `event:`, `data:`,
 * `id:` fields, events separated by a blank line). `EventSource` cannot send a POST with an
 * Authorization header, so the stream is read with `fetch` and parsed here.
 */

export interface SseMessage {
  event: string;
  data: string;
  id: string | null;
}

export class SseParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | null = null;

  constructor(private readonly onMessage: (message: SseMessage) => void) {}

  /** Feed the next decoded chunk; complete events are dispatched immediately. */
  push(chunk: string): void {
    this.buffer += chunk;
    let newline = this.nextLineBreak();
    while (newline !== -1) {
      const line = this.buffer.slice(0, newline);
      const width = this.buffer[newline] === "\r" && this.buffer[newline + 1] === "\n" ? 2 : 1;
      this.buffer = this.buffer.slice(newline + width);
      this.line(line);
      newline = this.nextLineBreak();
    }
  }

  /** End of stream: a final event without its trailing blank line is still dispatched. */
  end(): void {
    if (this.buffer) {
      this.line(this.buffer);
      this.buffer = "";
    }
    this.dispatch();
  }

  private nextLineBreak(): number {
    const match = /\r\n|\r|\n/.exec(this.buffer);
    // A lone "\r" at the very end may be the first half of "\r\n": wait for more input.
    if (match && match[0] === "\r" && match.index === this.buffer.length - 1) return -1;
    return match ? match.index : -1;
  }

  private line(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) return; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id") this.id = value;
  }

  private dispatch(): void {
    if (this.data.length > 0) {
      this.onMessage({ event: this.event || "message", data: this.data.join("\n"), id: this.id });
    }
    this.event = "";
    this.data = [];
  }
}
