/** Base URL of the API, inlined at build time (see .env.example). */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

/** The input guard rejects longer questions, so the UI stops there too. */
export const MAX_QUESTION_CHARS = 500;

/** Questions the demo dataset (Olist e-commerce) answers well. */
export const EXAMPLE_QUESTIONS = [
  "How many orders are there per order status?",
  "What was the total revenue per month in 2017?",
  "Which 10 product categories have the highest revenue?",
  "What is the average delivery time in days per customer state?",
  "Which payment types are used most often?",
] as const;
