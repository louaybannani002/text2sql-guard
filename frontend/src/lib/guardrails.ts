/** Plain-language names for the guardrail layers and the codes they report. */
import type { GuardrailLayer } from "./api/types";

export interface LayerInfo {
  layer: GuardrailLayer;
  name: string;
  description: string;
}

/** In pipeline order: a question meets them one after the other. */
export const LAYERS: LayerInfo[] = [
  {
    layer: "input_rules",
    name: "Input rules",
    description: "Fast pattern checks on the question itself, before any AI is involved.",
  },
  {
    layer: "input_classifier",
    name: "AI classifier",
    description: "A small model decides whether this is a genuine question about the data.",
  },
  {
    layer: "sql_validator",
    name: "SQL validator",
    description: "Every generated query is parsed and checked against a strict read-only policy.",
  },
  {
    layer: "database",
    name: "Database permissions",
    description: "Queries run as a read-only role that cannot see personal data.",
  },
];

const CODE_LABELS: Record<string, string> = {
  // input guard
  prompt_injection: "Looks like an attempt to override the assistant's instructions",
  sql_command: "Contains a database command instead of a question",
  invalid_input: "The text contains characters or a length that is not allowed",
  off_topic: "Not a question about the shop's data",
  harmful: "Potentially harmful request",
  guard_error: "The safety check was unavailable, so the question was blocked to be safe",
  // SQL validator rules
  read_only: "The query tried to change data",
  no_into_lock_copy: "The query used INTO, row locks or COPY",
  tables: "The query used a table it may not read",
  no_star: "The query used SELECT *",
  functions: "The query used a function that is not allowed",
  casts: "The query used a type conversion that is not allowed",
  columns: "The query read a column it may not read",
  parse: "The query could not be parsed",
  single_statement: "The query contained more than one statement",
  // database
  QueryPermissionError: "The database refused: the query needs data you may not read",
  QueryReadOnlyError: "The database refused: the query tried to modify data",
};

export function layerInfo(layer: GuardrailLayer): LayerInfo {
  const info = LAYERS.find((l) => l.layer === layer);
  if (!info) throw new Error(`unknown guardrail layer: ${layer}`);
  return info;
}

export function codeLabel(code: string): string {
  return CODE_LABELS[code] ?? code.replace(/_/g, " ");
}
