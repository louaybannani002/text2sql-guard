import { RotateCw, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api/client";

/** A request that failed before an answer arrived (network, rate limit, server error...). */
export function RequestError({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  const { title, detail } = describe(error);
  return (
    <Alert variant="destructive">
      <TriangleAlert aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="grid grid-cols-1 gap-3">
        <p>{detail}</p>
        {error.requestId ? (
          <p className="text-xs opacity-80">
            Request ID <code className="font-mono">{error.requestId}</code>
          </p>
        ) : null}
        {error.status !== 401 ? (
          <Button variant="outline" size="sm" className="justify-self-start" onClick={onRetry}>
            <RotateCw aria-hidden /> Try again
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function describe(error: ApiError): { title: string; detail: string } {
  switch (error.status) {
    case 0:
      return error.code === "network_error"
        ? { title: "Can't reach the server", detail: error.message }
        : { title: "The answer was interrupted", detail: error.message };
    case 401:
      return { title: "Signed out", detail: "Your session expired. Sign in again to continue." };
    case 413:
    case 422:
      return { title: "The question wasn't accepted", detail: error.message };
    case 429:
      return {
        title: "Too many questions",
        detail: `You've reached the per-minute limit. Try again in ${error.retryAfterS ?? 60} seconds.`,
      };
    default:
      return {
        title: "Something went wrong on our side",
        detail: "The server couldn't finish this question. Please try again in a moment.",
      };
  }
}
