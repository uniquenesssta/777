// Development-only interaction shared by the real IPC browser and WebView2 checks.
export async function connectDevelopment(page, fixture, username = "manager") {
  await page.getByLabel("服务地址", { exact: true }).fill(fixture.connection.url);
  const certificate = page.getByRole("textbox", { name: /^服务证书（PEM）/ });
  if (!(await certificate.isVisible())) {
    await page.getByText("证书与指纹（高级）", { exact: true }).click();
  }
  await certificate.fill(fixture.connection.certificate_pem);
  await page.getByLabel("证书 SHA-256 指纹", { exact: true })
    .fill(fixture.connection.certificate_sha256);
  await page.getByLabel("账号", { exact: true }).fill(username);
  await page.getByLabel("密码", { exact: true }).fill(fixture.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
}
