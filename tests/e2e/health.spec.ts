import { expect, test } from "@playwright/test";

test("home reports API health and keeps the CLI guide usable", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByTestId("hero-title")).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText("API conectada");
  await page.getByTestId("install-tab-linux").click();
  await expect(page.getByTestId("install-commands")).toContainText("sudo apt install git python3 python3-venv");
});

test("home remains available when the health endpoint is unreachable", async ({ page }) => {
  await page.route("**/api/health", (route) => route.abort());
  await page.goto("/");

  await expect(page.getByTestId("hero-title")).toBeVisible();
  await expect(page.getByTestId("api-status")).toHaveText("API indisponível");
  await expect(page.getByTestId("install-section")).toBeVisible();
});
