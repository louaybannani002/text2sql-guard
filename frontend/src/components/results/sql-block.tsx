"use client";

import hljs from "highlight.js/lib/core";
import pgsql from "highlight.js/lib/languages/pgsql";
import { Check, Copy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";

hljs.registerLanguage("pgsql", pgsql);

type CopyState = "idle" | "copied" | "failed";

export function SqlBlock({ sql }: { sql: string }) {
  const [copy, setCopy] = useState<CopyState>("idle");
  // highlight.js escapes the input: the HTML holds only its own <span class="hljs-*"> tags.
  const html = useMemo(() => hljs.highlight(sql, { language: "pgsql" }).value, [sql]);

  useEffect(() => {
    if (copy === "idle") return undefined;
    const timer = setTimeout(() => setCopy("idle"), 2000);
    return () => clearTimeout(timer);
  }, [copy]);

  async function copySql() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  return (
    <div className="relative rounded-lg border bg-muted/40">
      <div className="absolute top-2 right-2 flex items-center gap-2">
        <span role="status" className="text-xs text-muted-foreground">
          {copy === "copied" ? "Copied" : copy === "failed" ? "Couldn't copy" : ""}
        </span>
        <Button variant="ghost" size="icon-sm" onClick={copySql} aria-label="Copy SQL">
          {copy === "copied" ? <Check aria-hidden /> : <Copy aria-hidden />}
        </Button>
      </div>
      {/* Long lines scroll sideways: focusable so keyboard users can scroll too. */}
      <pre
        className="overflow-x-auto rounded-lg p-4 pr-12 text-[13px] leading-relaxed focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        tabIndex={0}
        role="region"
        aria-label="SQL query"
      >
        <code className="hljs font-mono" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}
