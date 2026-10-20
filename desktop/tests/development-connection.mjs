// Development-only interaction shared by the real IPC browser and WebView2 checks.
export async function selectDevelopmentIdentity(page, fixture, username) {
  // Prepare a real, non-default test identity through native authentication.
  // The product form itself never submits a username or password.
  await page.evaluate(async ({fixture,username}) => {
    await window.__TAURI_INTERNALS__.invoke('desktop_action', {request:{
      action:'connect',connection:fixture.connection,username,password:fixture.password,
    }});
  }, {fixture,username});
}
export async function connectDevelopment(page, fixture, username = "manager") {
  await selectDevelopmentIdentity(page, fixture, username);
  await page.getByLabel("服务地址", { exact: true }).fill(fixture.connection.url);
  const certificate = page.getByRole("textbox", { name: /^服务证书（PEM）/ });
  if (!(await certificate.isVisible())) {
    await page.getByText("证书与指纹（高级）", { exact: true }).click();
  }
  await certificate.fill(fixture.connection.certificate_pem);
  await page.getByLabel("证书 SHA-256 指纹", { exact: true })
    .fill(fixture.connection.certificate_sha256);
  await page.getByRole("button", { name: "连接后台", exact: true }).click();
}
