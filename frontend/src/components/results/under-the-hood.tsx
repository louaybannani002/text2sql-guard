"use client";

import { ChevronDown, Cpu } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Answer } from "@/lib/api/types";
import { formatCost, formatMs, formatNumber } from "@/lib/format";
import { STAGE_LABELS } from "@/lib/stages";
import { cn } from "@/lib/utils";

/** Stage timings, tokens and cost of one answer: what the pipeline actually did. */
export function UnderTheHood({ answer }: { answer: Answer }) {
  const [open, setOpen] = useState(false);
  const { timings } = answer;
  const longest = Math.max(1, ...timings.stages.map((s) => s.latency_ms));

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-xl border">
      <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-medium hover:bg-muted/50">
        <span className="flex items-center gap-2">
          <Cpu className="size-4" aria-hidden /> Under the hood
        </span>
        <span className="flex items-center gap-3 text-xs font-normal text-muted-foreground">
          <span className="hidden sm:inline">
            {formatMs(timings.total_ms)} · {formatNumber(answer.tokens)} tokens · {formatCost(answer.cost_usd)}
          </span>
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} aria-hidden />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="grid grid-cols-1 gap-4 border-t px-4 py-4">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          <Stat label="Total time" value={formatMs(timings.total_ms)} />
          <Stat label="Tokens" value={formatNumber(answer.tokens)} />
          <Stat label="Cost" value={formatCost(answer.cost_usd)} />
          <Stat label="SQL attempts" value={String(answer.attempts)} />
          <Stat
            label="Cache"
            value={answer.cache === "exact" ? "exact hit" : answer.cache === "semantic" ? "similar question" : "miss"}
          />
        </dl>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm">
            <caption className="sr-only">Time, tokens and cost per stage</caption>
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-3 font-medium">Stage</th>
                <th className="w-2/5 py-1 pr-3 font-medium">Time</th>
                <th className="py-1 pr-3 text-right font-medium">Tokens</th>
                <th className="py-1 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {timings.stages.map((stage, index) => (
                <tr key={`${stage.stage}-${stage.attempt}-${index}`} className="border-t">
                  <td className="py-1.5 pr-3">
                    {STAGE_LABELS[stage.stage]}
                    {stage.attempt === 0 ? (
                      <span className="text-muted-foreground"> (cached)</span>
                    ) : stage.attempt > 1 ? (
                      <span className="text-muted-foreground"> #{stage.attempt}</span>
                    ) : null}
                    {stage.status === "error" ? (
                      <Badge variant="destructive" className="ml-2">
                        error
                      </Badge>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-3">
                    <span className="flex items-center gap-2">
                      <span
                        className={cn(
                          "h-2 rounded-full",
                          stage.status === "error" ? "bg-destructive/60" : "bg-primary/60",
                        )}
                        style={{ width: `${Math.max(2, (stage.latency_ms / longest) * 100)}%` }}
                        aria-hidden
                      />
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                        {formatMs(stage.latency_ms)}
                      </span>
                    </span>
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">
                    {stage.tokens ? formatNumber(stage.tokens) : "–"}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {stage.tokens ? formatCost(stage.cost_usd) : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          Query ID <code className="font-mono">{answer.query_id}</code>
        </p>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-muted/50 px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}
