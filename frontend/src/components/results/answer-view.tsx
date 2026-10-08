"use client";

import { BarChart3, CircleHelp, Database, TriangleAlert, Zap } from "lucide-react";
import { useMemo } from "react";

import { FeedbackButtons } from "@/components/results/feedback-buttons";
import { GuardrailNotice } from "@/components/results/guardrail-notice";
import { ResultsChart } from "@/components/results/results-chart";
import { ResultsTable } from "@/components/results/results-table";
import { SqlBlock } from "@/components/results/sql-block";
import { UnderTheHood } from "@/components/results/under-the-hood";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { ApiClient } from "@/lib/api/client";
import type { Answer } from "@/lib/api/types";
import { detectChart } from "@/lib/chart";

export function AnswerView({ answer, client }: { answer: Answer; client: ApiClient }) {
  return (
    <div className="grid grid-cols-1 gap-6">
      <Body answer={answer} />
      {answer.status === "answered" ? (
        <FeedbackButtons key={answer.query_id} client={client} queryId={answer.query_id} />
      ) : null}
      <UnderTheHood answer={answer} />
    </div>
  );
}

function Body({ answer }: { answer: Answer }) {
  switch (answer.status) {
    case "answered":
      return <Answered answer={answer} />;
    case "blocked":
    case "rejected":
      return <GuardrailNotice guardrail={answer.guardrail} status={answer.status} message={answer.message} />;
    case "cannot_answer":
      return (
        <Alert>
          <CircleHelp aria-hidden />
          <AlertTitle>The data can&apos;t answer this one</AlertTitle>
          <AlertDescription>{answer.message}</AlertDescription>
        </Alert>
      );
    case "failed":
      return (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden />
          <AlertTitle>No answer this time</AlertTitle>
          <AlertDescription>{answer.message}</AlertDescription>
        </Alert>
      );
  }
}

function Answered({ answer }: { answer: Answer }) {
  const chart = useMemo(() => detectChart(answer.columns, answer.rows), [answer.columns, answer.rows]);
  return (
    <div className="grid grid-cols-1 gap-6">
      <section aria-label="Explanation" className="grid grid-cols-1 gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Answer</h2>
          {answer.cache ? (
            <Badge variant="secondary">
              <Zap aria-hidden /> {answer.cache === "exact" ? "From cache" : "Reused a similar question's query"}
            </Badge>
          ) : null}
        </div>
        {answer.explanation ? <p className="leading-relaxed">{answer.explanation}</p> : null}
        {answer.assumptions.length > 0 ? (
          <div className="grid grid-cols-1 gap-1">
            <h3 className="text-sm font-medium text-muted-foreground">Assumptions</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {answer.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {answer.sql ? (
        <section aria-label="SQL" className="grid grid-cols-1 gap-2">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Database className="size-4" aria-hidden /> SQL that ran
          </h3>
          <SqlBlock sql={answer.sql} />
        </section>
      ) : null}

      {chart ? (
        <section aria-label="Chart" className="grid grid-cols-1 gap-2">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <BarChart3 className="size-4" aria-hidden /> Chart
          </h3>
          <ResultsChart spec={chart} columns={answer.columns} />
        </section>
      ) : null}

      <section aria-label="Results" className="grid grid-cols-1 gap-2">
        <h3 className="text-sm font-medium">Results</h3>
        {answer.rows.length === 0 ? (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            The query ran but no rows matched.
          </p>
        ) : (
          <ResultsTable
            columns={answer.columns}
            rows={answer.rows}
            truncated={answer.truncated}
            fileName={`text2sql-${answer.query_id.slice(0, 8)}.csv`}
          />
        )}
      </section>
    </div>
  );
}
