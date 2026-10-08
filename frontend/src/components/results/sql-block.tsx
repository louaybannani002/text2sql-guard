"use client";

import hljs from "highlight.js/lib/core";
import pgsql from "highlight.js/lib/languages/pgsql";
import { Check, Copy } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

hljs.registerLanguage("pgsql", pgsql);

export function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  // highlight.js escapes the input: the HTML holds only its own <span class="hljs-*"> tags.
  const html = useMemo(() => hljs.highlight(sql, { language: "pgsql" }).value, [sql]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      toast.success("SQL copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy: the browser blocked clipboard access.");
    }
  }

  return (
    <div className="relative rounded-lg border bg-muted/40">
      <Button
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-2"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy SQL"}
      >
        {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      </Button>
      <pre className="overflow-x-auto p-4 pr-12 text-[13px] leading-relaxed">
        <code className="hljs font-mono" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}
