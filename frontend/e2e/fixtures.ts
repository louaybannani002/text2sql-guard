/**
 * Every test gets a page that records CSP violations and console errors (both fail the test)
 * and helpers to sign in, ask a question and check accessibility.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DEMO_USERNAME } from "./env";

declare global {
  interface Window {
    __cspViolations: string[];
  }
}

interface AppFixtures {
  app: App;
}

export class App {
  constructor(readonly page: Page) {}

  async signIn(): Promise<void> {
    await this.page.goto("/");
    await this.page.getByLabel("Username").fill(DEMO_USERNAME);
    await this.page.getByLabel("Password").fill(DEMO_PASSWORD);
    await this.page.getByRole("button", { name: "Sign in" }).click();
    await expect(this.page.getByLabel("Your question")).toBeVisible();
  }

  async ask(question: string): Promise<void> {
    await this.page.getByLabel("Your question").fill(question);
    await this.page.getByRole("button", { name: "Ask" }).click();
  }

  /** WCAG 2.1 A/AA checks with axe on what is currently rendered. */
  async expectAccessible(): Promise<void> {
    const results = await new AxeBuilder({ page: this.page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    const summary = results.violations.map(
      (v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`,
    );
    expect(summary).toEqual([]);
  }
}

export const test = base.extend<AppFixtures>({
  app: async ({ page }, use) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));
    await page.addInitScript(() => {
      window.__cspViolations = [];
      document.addEventListener("securitypolicyviolation", (event) => {
        window.__cspViolations.push(`${event.violatedDirective}: ${event.blockedURI || "inline"}`);
      });
    });

    await use(new App(page));

    const violations = await page.evaluate(() => window.__cspViolations).catch(() => []);
    expect(violations, "Content-Security-Policy violations").toEqual([]);
    expect(consoleErrors, "browser console errors").toEqual([]);
  },
});

export { expect };
