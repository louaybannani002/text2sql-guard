"use client";

import { LogOut, ShieldCheck } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { SignInCard } from "@/components/auth/sign-in-card";
import { QuestionForm } from "@/components/ask/question-form";
import { RequestError } from "@/components/ask/request-error";
import { StageProgress } from "@/components/ask/stage-progress";
import { AnswerView } from "@/components/results/answer-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAsk } from "@/hooks/use-ask";

export function AskApp() {
  const { client, session, signOut } = useAuth();
  const { state, ask, cancel } = useAsk(client);
  const running = state.phase === "running";

  return (
    <div className="mx-auto grid w-full max-w-5xl grid-cols-1 gap-8 px-4 py-6 sm:py-10">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid grid-cols-1 gap-1">
          <h1 className="flex items-center gap-2 text-xl font-semibold sm:text-2xl">
            <ShieldCheck className="size-6 text-primary" aria-hidden /> text2sql-guard
          </h1>
          <p className="text-sm text-muted-foreground">
            Ask questions about the shop&apos;s data in plain language. Every query is checked
            and runs read-only.
          </p>
        </div>
        {session ? (
          <Button variant="ghost" size="sm" onClick={signOut}>
            <LogOut aria-hidden /> Sign out
          </Button>
        ) : null}
      </header>

      <main className="grid grid-cols-1 gap-8">
        {session ? (
          <QuestionForm running={running} onAsk={ask} onCancel={cancel} />
        ) : (
          <SignInCard />
        )}

        {state.phase !== "idle" ? (
          <div className="grid grid-cols-1 gap-6">
            <div className="grid grid-cols-1 gap-1">
              <p className="text-xs tracking-wide text-muted-foreground uppercase">Question</p>
              <p className="font-medium break-words">{state.question}</p>
            </div>
            <StageProgress steps={state.steps} running={running} startedAt={state.startedAt} />
            {running ? <ResultSkeleton /> : null}
            {state.phase === "error" && state.error ? (
              <RequestError error={state.error} onRetry={() => void ask(state.question)} />
            ) : null}
            {state.phase === "done" && state.answer ? (
              <AnswerView answer={state.answer} client={client} />
            ) : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}

function ResultSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-3" aria-hidden>
      <Skeleton className="h-5 w-2/3" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-28 w-full" />
    </div>
  );
}
