"use client";

import { ArrowUp, Loader2, Square } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { EXAMPLE_QUESTIONS, MAX_QUESTION_CHARS } from "@/lib/config";
import { cn } from "@/lib/utils";

interface Props {
  running: boolean;
  onAsk: (question: string) => void;
  onCancel: () => void;
}

export function QuestionForm({ running, onAsk, onCancel }: Props) {
  const [question, setQuestion] = useState("");
  const trimmed = question.trim();
  const tooLong = question.length > MAX_QUESTION_CHARS;
  const canAsk = trimmed.length > 0 && !tooLong && !running;

  function submit(text: string) {
    const value = text.trim();
    if (!value || value.length > MAX_QUESTION_CHARS || running) return;
    onAsk(value);
  }

  return (
    <section aria-label="Ask a question" className="grid grid-cols-1 gap-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="relative"
      >
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <Textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit(question);
            }
          }}
          placeholder="Ask about orders, products, sellers, payments, deliveries…"
          rows={3}
          className="min-h-24 resize-none pr-14 pb-8 text-base md:text-base"
          aria-invalid={tooLong}
          aria-describedby="question-hint"
        />
        <p
          id="question-hint"
          className={cn(
            "pointer-events-none absolute bottom-2 left-3 text-xs text-muted-foreground",
            tooLong && "text-destructive",
          )}
        >
          {question.length}/{MAX_QUESTION_CHARS}
          <span className="hidden sm:inline"> · Enter to ask, Shift+Enter for a new line</span>
        </p>
        {running ? (
          <Button
            type="button"
            size="icon"
            variant="secondary"
            className="absolute right-2 bottom-2"
            onClick={onCancel}
            aria-label="Stop"
          >
            <Square className="fill-current" aria-hidden />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            className="absolute right-2 bottom-2"
            disabled={!canAsk}
            aria-label="Ask"
          >
            {running ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowUp aria-hidden />}
          </Button>
        )}
      </form>
      <div className="flex flex-wrap gap-2" aria-label="Example questions">
        {EXAMPLE_QUESTIONS.map((example) => (
          <Button
            key={example}
            type="button"
            variant="outline"
            size="sm"
            className="h-auto max-w-full rounded-full py-1 text-left whitespace-normal"
            disabled={running}
            onClick={() => {
              setQuestion(example);
              submit(example);
            }}
          >
            {example}
          </Button>
        ))}
      </div>
    </section>
  );
}
