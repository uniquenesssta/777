// Actual DetailPage HTML/CSS/assets in Chromium; not Windows WebView2 acceptance.
import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import { detailMarkup } from './fixtures/detail-page';
import { inspectPresentation } from '../native-presentation.mjs';
import { inspectIcons } from '../presentation-icons.mjs';

async function openDetail(page: Page, delivery: string) {
  const body = detailMarkup(false, delivery === 'manager' ? 'admin' : 'sales');
  await page.route('**/submitted-order-fixture', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><link rel="stylesheet" href="/src/tokens.css"><link rel="stylesheet" href="/src/app.css"></head><body>${body}</body></html>`,
  }));
  await page.goto('/submitted-order-fixture');
}

for (const damage of ['removed', 'broken', 'placeholder', 'stretched']) {
  test(`manager detail rejects a ${damage} financial icon`, async ({page}) => {
    await openDetail(page, 'manager');
    await inspectIcons(page, 'manager', 'detail');
    if (damage === 'broken') await page.route('**/missing-icon.svg', route => route.abort());
    await page.locator('.finance img.icon').evaluate((node, damage) => {
      if (damage === 'removed') node.remove();
      if (damage === 'broken') node.setAttribute('src', '/missing-icon.svg');
      if (damage === 'placeholder') node.outerHTML = '<span class="icon" aria-hidden="true"></span>';
      if (damage === 'stretched') (node as HTMLElement).style.width = '30px';
    }, damage);
    await expect(inspectIcons(page, 'manager', 'detail', 200)).rejects.toThrow();
  });
}

test('sales detail cannot pass with the administrator finance panel', async ({page}) => {
  await openDetail(page, 'manager');
  await expect(inspectIcons(page, 'sales', 'detail', 200)).rejects.toThrow();
});

for (const delivery of ['manager', 'sales']) {
  test(`${delivery} submitted order passes the native presentation check at all four scales`, async ({page}, info) => {
    await openDetail(page, delivery);
    const output = info.outputPath('presentation');
    fs.mkdirSync(output, {recursive: true});
    const report = await inspectPresentation(page, output, delivery, 'detail');
    expect(report.samples).toHaveLength(4);
    for (const sample of report.samples) {
      expect(sample.icons).toHaveLength(delivery === 'manager' ? 1 : 0);
    }
  });
}
