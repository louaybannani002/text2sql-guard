/**
 * The demo credentials and URLs the tests use: from the environment (CI) or, locally, from
 * backend/.env (the same file docker compose reads). Values are never printed.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function backendEnv(): Record<string, string> {
  const path = resolve(__dirname, "../../backend/.env");
  if (!existsSync(path)) return {};
  const entries = readFileSync(path, "utf8")
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith("#") && line.includes("="))
    .map((line) => {
      const at = line.indexOf("=");
      return [line.slice(0, at).trim(), line.slice(at + 1).trim().replace(/^["']|["']$/g, "")];
    });
  return Object.fromEntries(entries);
}

const fileEnv = backendEnv();

function setting(name: string, fallback?: string): string {
  const value = process.env[name] ?? fileEnv[name] ?? fallback;
  if (!value) throw new Error(`${name} is not set (environment or backend/.env)`);
  return value;
}

export const DEMO_USERNAME = setting("DEMO_USERNAME");
export const DEMO_PASSWORD = setting("DEMO_PASSWORD");
export const API_URL = process.env.E2E_API_URL ?? `http://127.0.0.1:${setting("API_PORT", "8000")}`;
