import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

const shots = resolve(process.cwd(), "../reports/screenshots");
mkdirSync(shots, { recursive: true });

const routes = [
  ["Dashboard", "/dashboard"],
  ["Patient list", "/patients"],
  ["Patient dashboard", "/patient"],
  ["Patient timeline", "/timeline"],
  ["Patient progress", "/progress"],
  ["OPD consultation", "/notes?tab=consult"],
  ["Clinical alerts", "/safety?tab=alerts"],
  ["Tasks & escalations", "/tasks"],
  ["Inbound reports", "/documents?tab=inbound"],
  ["Discharge", "/discharge"],
  ["Claim review", "/revenue?tab=claim"],
  ["Audit & monitoring logs", "/audit"],
] as const;

test("Dashboard has one priority CTA, compact row actions, and working routes", async ({ page }) => {
  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const apiRequests: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()}`));
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(`${request.method()} ${request.url()}`);
  });

  await page.goto("/dashboard");
  const nav = page.getByRole("navigation", { name: "Main menu" });
  await expect(nav).toBeVisible();
  await expect(nav.locator("a, button")).toHaveCount(7);
  await expect(nav.getByRole("tablist", { name: "Workspace" }).getByRole("tab")).toHaveCount(2);
  await expect(nav.getByRole("tablist", { name: "Sections" }).getByRole("tab")).toHaveCount(2);
  await expect(nav.getByRole("link", { name: "Discharge Summary" })).toBeVisible();
  await expect(nav.getByRole("link", { name: /Emergency.*Alerts/ })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Hospital sections" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Search all modules and patients" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Hospital Dashboard" })).toBeVisible();
  await expect(page.getByRole("table").first().getByText("Patients in care")).toBeVisible();
  const cta = page.locator(".page-header-actions .btn-primary");
  await expect(cta).toBeVisible();
  await expect(cta).toContainText(/Review safety alert|Review overdue task|Review open alerts|Continue pending tasks|Confirm extracted report|Review clinical draft|Review discharge summary|Review claim gaps|View patient summary/);
  await expect(page.locator(".page-header-actions .btn")).toHaveCount(1);
  await expect(page.locator(".his-dash .his-box .table .btn-sm")).toHaveCount(0);
  const patientLink = page.getByRole("button", { name: "Open Ravi Menon" }).first();
  await expect(patientLink).toBeVisible();
  await page.screenshot({ path: resolve(shots, "after-dashboard.png") });

  await patientLink.click();
  await expect(page).toHaveURL(/\/patient$/);
  await expect(page.getByRole("tab", { name: /PATIENT: RAVI MENON/ })).toBeVisible();

  await page.goto("/dashboard");

  const dashboardCta = page.locator(".page-header-actions .btn-primary");
  await dashboardCta.click();
  await expect(page.locator("#main-content")).toBeVisible();
  await expect(page).toHaveURL(/\/(safety|tasks|documents|notes|discharge|revenue|patients)(\?|$)/);

  for (const [label, target] of routes) {
    await page.goto(target);
    await expect(page.locator("#main-content")).toBeVisible();
    await expect(page.locator("#main-content")).not.toContainText(/404|page not found/i);
    if (label === "Dashboard") await expect(page.getByRole("heading", { name: "Hospital Dashboard" })).toBeVisible();
  }

  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(apiRequests).toEqual([]);
});

test("patient navigation keeps contextual alerts and discharge access in the existing menu", async ({ page }) => {
  await page.goto("/patient");
  const nav = page.getByRole("navigation", { name: "Main menu" });
  await expect(nav.getByRole("tab", { name: /PATIENT:/ })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Discharge Summary" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: /Emergency.*Alerts/ })).toHaveCount(0);

  await nav.getByRole("tab", { name: "Clinical care" }).click();
  await expect(nav.getByRole("link", { name: "Discharge", exact: true })).toHaveAttribute("href", "/discharge");
  await expect(nav.locator('a[href="/discharge"]')).toHaveCount(1);

  await nav.getByRole("tab", { name: /Safety & results/ }).click();
  await expect(nav.locator('a[href="/safety?tab=alerts"]')).toHaveCount(1);
  await page.goto("/safety?tab=alerts");
  await expect(page.locator("#main-content")).toContainText("Clinical alerts");
  await expect(page.getByText("0 open", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Loading")).toHaveCount(0);
  await page.screenshot({ path: resolve(shots, "after-patient-safety.png") });
});

test("existing layout remains usable at desktop, tablet, and mobile widths", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("table").first().getByText("Patients in care")).toBeVisible();
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(page.getByRole("navigation", { name: "Main menu" })).toBeVisible();
    const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: window.innerWidth }));
    expect(width.page).toBeLessThanOrEqual(width.viewport);
    if (viewport.width === 390) await page.screenshot({ path: resolve(shots, "after-mobile-dashboard.png") });
  }
});
