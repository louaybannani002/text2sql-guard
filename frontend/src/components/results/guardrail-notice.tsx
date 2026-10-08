import { ShieldAlert } from "lucide-react";

import type { Guardrail } from "@/lib/api/types";
import { LAYERS, codeLabel, layerInfo } from "@/lib/guardrails";
import { cn } from "@/lib/utils";

interface Props {
  guardrail: Guardrail | null;
  status: "blocked" | "rejected";
  message: string;
}

/** Why a question was stopped, and where along the chain of guardrails it happened. */
export function GuardrailNotice({ guardrail, status, message }: Props) {
  const info = guardrail ? layerInfo(guardrail.layer) : null;
  const title = info
    ? `${status === "blocked" ? "Blocked" : "Stopped"} by the ${info.name.toLowerCase()}`
    : status === "blocked"
      ? "Blocked by a guardrail"
      : "Stopped by a guardrail";

  return (
    <section
      role="alert"
      aria-labelledby="guardrail-title"
      className="grid grid-cols-1 gap-4 rounded-xl border border-amber-500/40 bg-amber-50 p-4 text-amber-950 sm:p-5 dark:bg-amber-950/30 dark:text-amber-50"
    >
      <div className="flex gap-3">
        <ShieldAlert className="mt-0.5 size-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <div className="grid grid-cols-1 gap-1">
          <h2 id="guardrail-title" className="font-semibold">
            {title}
          </h2>
          <p className="text-sm">{message}</p>
          {guardrail ? (
            <p className="text-sm text-amber-900/80 dark:text-amber-100/80">
              Reason: {codeLabel(guardrail.code)}{" "}
              <code className="rounded bg-amber-500/15 px-1 py-0.5 font-mono text-xs">{guardrail.code}</code>
            </p>
          ) : null}
        </div>
      </div>
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-4" aria-label="Guardrail layers">
        {LAYERS.map((layer, index) => {
          const hit = layer.layer === guardrail?.layer;
          const passed =
            guardrail !== null && index < LAYERS.findIndex((l) => l.layer === guardrail.layer);
          return (
            <li
              key={layer.layer}
              aria-current={hit ? "step" : undefined}
              className={cn(
                "rounded-lg border px-3 py-2 text-xs",
                hit
                  ? "border-amber-600 bg-amber-500/20 font-medium dark:border-amber-400"
                  : "border-amber-500/20 opacity-70",
              )}
              title={layer.description}
            >
              <span className="block text-[11px] uppercase tracking-wide opacity-70">
                {index + 1}. {hit ? "stopped here" : passed ? "passed" : "not reached"}
              </span>
              {layer.name}
            </li>
          );
        })}
      </ol>
      {info ? <p className="text-xs opacity-80">{info.description}</p> : null}
    </section>
  );
}
