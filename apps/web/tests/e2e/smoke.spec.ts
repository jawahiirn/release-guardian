import { expect, test } from "@playwright/test";

test("web shell loads the sign-in screen", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Release Guardian");
  await expect(page.getByRole("heading", { name: "Sign in to your instance." })).toBeVisible();
  await expect(page.getByLabel("Email")).toBeVisible();
});

test("API liveness endpoint responds", async ({ request }) => {
  const response = await request.get(
    `${process.env.API_BASE_URL ?? "http://127.0.0.1:8000"}/health/live`,
  );
  expect(response.ok()).toBeTruthy();
  await expect(response.json()).resolves.toEqual({ status: "ok" });
});
