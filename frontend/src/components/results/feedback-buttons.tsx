"use client";

import { Loader2, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, type ApiClient } from "@/lib/api/client";
import { cn } from "@/lib/utils";

const UP = 5;
const DOWN = 1;
const MAX_COMMENT = 2000;

/** Thumbs up/down (rating 5/1), then an optional comment; the API keeps one per user+query. */
export function FeedbackButtons({ client, queryId }: { client: ApiClient; queryId: string }) {
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [commentSent, setCommentSent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(nextRating: number, text: string | null): Promise<boolean> {
    setPending(true);
    setError(null);
    try {
      await client.sendFeedback({ query_id: queryId, rating: nextRating, comment: text });
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't send feedback. Please retry.");
      return false;
    } finally {
      setPending(false);
    }
  }

  async function vote(value: number) {
    const previous = rating;
    setRating(value);
    setCommentSent(false);
    if (!(await send(value, comment.trim() || null))) setRating(previous);
  }

  async function submitComment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rating === null || !comment.trim()) return;
    if (await send(rating, comment.trim())) setCommentSent(true);
  }

  return (
    <div className="grid grid-cols-1 gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Was this answer helpful?</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => vote(UP)}
          disabled={pending}
          aria-pressed={rating === UP}
          className={cn(rating === UP && "border-emerald-600 text-emerald-700 dark:text-emerald-400")}
        >
          <ThumbsUp aria-hidden /> Yes
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => vote(DOWN)}
          disabled={pending}
          aria-pressed={rating === DOWN}
          className={cn(rating === DOWN && "border-destructive text-destructive")}
        >
          <ThumbsDown aria-hidden /> No
        </Button>
        {pending ? <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Sending" /> : null}
        {rating !== null && !pending && !error ? (
          <span className="text-sm text-muted-foreground" role="status">
            Thanks for the feedback!
          </span>
        ) : null}
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {rating !== null && !commentSent ? (
        <form onSubmit={submitComment} className="grid grid-cols-1 gap-2 sm:max-w-xl">
          <label htmlFor="feedback-comment" className="text-sm">
            {rating === DOWN ? "What was wrong? (optional)" : "Anything to add? (optional)"}
          </label>
          <Textarea
            id="feedback-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={MAX_COMMENT}
            rows={2}
          />
          <Button type="submit" size="sm" variant="secondary" className="justify-self-start" disabled={pending || !comment.trim()}>
            Send comment
          </Button>
        </form>
      ) : null}
      {commentSent ? (
        <p className="text-sm text-muted-foreground" role="status">
          Comment sent.
        </p>
      ) : null}
    </div>
  );
}
