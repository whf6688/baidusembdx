import { expect, test } from "@playwright/test";

test("account batch schedule uses a 7 by 24 draggable selector", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/jfsem?page=account-list", { waitUntil: "networkidle" });
  await page.getByRole("checkbox", { name: /选择账户 / }).first().check();
  await page.getByRole("button", { name: "批量时段" }).click();

  const dialog = page.getByRole("dialog", { name: /批量设置计划时段/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("周一", { exact: true })).toBeVisible();
  await expect(dialog.getByText("周日", { exact: true })).toBeVisible();
  await expect(dialog.locator(".weekly-schedule-hours span")).toHaveCount(24);
  await expect(dialog.locator("button.rgdp__grid-cell")).toHaveCount(168);
  const legend = dialog.locator(".weekly-schedule-legend");
  await expect(legend.getByText("启用时段", { exact: true })).toBeVisible();
  await expect(legend.getByText("暂停时段", { exact: true })).toBeVisible();

  await dialog.getByRole("button", { name: "清空" }).click();
  await expect(dialog.getByText("未选择时段", { exact: true })).toBeVisible();

  const start = await dialog.locator('[data-weekday="1"][data-hour="8"]').boundingBox();
  const end = await dialog.locator('[data-weekday="3"][data-hour="10"]').boundingBox();
  expect(start).not.toBeNull();
  expect(end).not.toBeNull();
  await page.mouse.move(start!.x + start!.width / 2, start!.y + start!.height / 2);
  await page.mouse.down();
  await page.mouse.move(end!.x + end!.width / 2, end!.y + end!.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect(dialog.getByText(/周一 08:00–11:00/)).toBeVisible();
  await expect(dialog.getByText(/周三 08:00–11:00/)).toBeVisible();
  await page.screenshot({
    path: "artifacts/ui-audit/latest/dialogs/account-weekly-schedule.png",
  });
});

test("auto launch plan schedule reuses the weekly selector", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/jfsem?page=delivery", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "设置计划时段" }).click();

  const dialog = page.getByRole("dialog", { name: /设置计划时段/ });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS("width", "960px");
  await expect(dialog.locator("button.rgdp__grid-cell")).toHaveCount(168);
  await expect(dialog.getByText("启用时段", { exact: true })).toBeVisible();
  await expect(dialog.getByText("暂停时段", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "清空" }).click();
  await expect(dialog.getByRole("button", { name: "确定" })).toBeDisabled();

  await dialog.locator('[data-weekday="1"][data-hour="8"]').click();
  await expect(dialog.getByText("周一 08:00–09:00", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "确定" })).toBeEnabled();
  await page.screenshot({
    path: "artifacts/ui-audit/latest/dialogs/auto-launch-weekly-schedule.png",
  });
});
