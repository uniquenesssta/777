// Icon expectations for the full-permission quote/detail fixtures used by CI.
import { expect } from '@playwright/test';

export async function inspectIcons(page, delivery, view, timeout = 5000) {
  expect(['manager', 'sales']).toContain(delivery);
  expect(['quote', 'detail']).toContain(view);
  const icons = page.locator('img.icon');
  await expect(page.locator('.icon-fallback, .icon:not(img)')).toHaveCount(0, {timeout});
  if (view === 'detail') {
    const count = delivery === 'manager' ? 1 : 0;
    await expect(page.locator('.settlement')).toHaveAttribute('data-admin', String(count === 1), {timeout});
    await expect(page.locator('.settlement .finance')).toHaveCount(count, {timeout});
    await expect(page.locator('.finance img.icon[src="/icons/7bfb4.svg"]')).toHaveCount(count, {timeout});
    await expect(icons).toHaveCount(count, {timeout});
  } else {
    await expect(icons.first()).toBeVisible({timeout});
  }
  const read = () => icons.evaluateAll(nodes => nodes.map(n => ({
    source: n.getAttribute('src'), natural: n.naturalWidth,
    width: n.getBoundingClientRect().width, complete: n.complete,
  })));
  await expect.poll(async () => (await read()).every(i =>
    i.complete && i.natural > 0 && Math.abs(i.width - i.natural) < 1
  ), {timeout}).toBe(true);
  return read();
}
