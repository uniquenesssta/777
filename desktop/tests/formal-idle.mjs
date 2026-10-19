// Shared UI assertion; actual network readiness/close is verified by the native runner.
import { expect } from '@playwright/test';

export async function expectSilentFormalEntry(page, timeout = 20000) {
  const idle = page.locator('main.formal-idle');
  await expect(idle).toBeVisible({timeout});
  await expect(idle).toHaveText('');
  await expect(page.locator('.connection-card')).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('status')).toHaveCount(0);
  for (const name of ['登录', '账户菜单', '退出登录', '重新连接', '选择文件', '登记并进入']) {
    await expect(page.getByRole('button', {name, exact: true})).toHaveCount(0);
  }
  for (const name of ['服务地址', '服务证书（PEM）', '证书 SHA-256 指纹', '账号', '密码']) {
    await expect(page.getByLabel(name, {exact: true})).toHaveCount(0);
  }
  await expect(page.locator('body')).not.toContainText(/正在连接|暂时无法进入|DEPLOYMENT|192\.168\.|联系管理员/);
}
