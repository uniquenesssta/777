# P08-02-2 Windows CI 修复

2026-10-19，分支 `stage/p08-cutover`。用户报告 CI 未通过；母/子安装包专项验证继续跳过，其他功能检查保留。

## 根因和修正

[CI #69](https://github.com/uniquenesssta/777/actions/runs/39189439198) 的 host-sync 与 desktop-contracts 均被同一条 Windows 编译错误阻断：`automatic_checks/upgrade.rs` 在模块作用域导入 `quote_ledger::store`，使用它的测试却是 `cfg(not(windows))`；Windows 下导入未使用，被 `-D warnings` 拒绝。后续同步、业务、备份恢复和窗口检查均没有执行，不能计为通过。

修复提交 `16348f9e317c387c83929f05fb00e0fcbc2ddbef` 将导入移入实际使用的测试函数。保留原平台范围、严格警告规则、测试断言和 CI 功能任务；没有修改产品代码或关闭验证项。

本地 fmt、Host/Security 严格 clippy、3 项升级相关回归及 diff 检查通过。本地结果不替代 Windows；[修复后 CI #70](https://github.com/uniquenesssta/777/actions/runs/39190050854) 的实际结果以[结构化记录](P08-02-2-ci-repair.json)为准，初次失败及本地输出见[日志](P08-02-2-ci-repair.log)。

Windows runner 使用临时数据和隔离服务，不连接用户 4.23/4.38，不能代替现场部署、交互 UAC 或真实开机重启验收。母子安装包任务保持 skipped。

## 补充夹具修正与后续执行规则

本地浏览器检查发现 `presentation.spec.ts` 的成功备份样本缺少 `delivery_complete: true`，与现有“只有完整确认才显示备份正常”契约不符。已补齐成功样本，保留成功断言及未完成/失败/未确认不显示的负向检查；产品逻辑不改。首次 21 项中 20 通过、1 失败；修正后连同 6 项备份展示用例共 **27 项通过**。这是本地模拟 UI 检查，不替代 Windows 或现场结果。

用户随后要求：**以后提交 CI 后不轮询、不等待结束**。因此不再查询 #70 或新提交的运行结果；#70 的运行中状态仅为此前观察，不是当前状态或通过结论。此次补充修复正常触发功能 CI，结果未核实；母子包专项验证继续默认跳过。[工作流入口](https://github.com/uniquenesssta/777/actions/workflows/p07-windows.yml)。

## CI #72：真实业务浏览器入口修正

用户再次报告失败后读取 [CI #72](https://github.com/uniquenesssta/777/actions/runs/39193288945)（`ca15420`）：**host-sync 成功，desktop-contracts 失败，installers 跳过**。桌面严格构建、Rust 测试、release 程序和此前 33 项浏览器检查已通过；随后 `workbench.spec.ts` 的业务用例逐一超时，最终浏览器步骤超过 600 秒，后续窗口及部署检查未执行。

根因是共用登录辅助函数直接填写默认折叠的“证书与指纹（高级）”字段。当前表单将该内容放在 `details` 内，测试未展开，Playwright 等待隐藏控件直至超时。仅在测试填写前点击已有折叠标题；不修改产品界面、正式端权限或逻辑，不延长超时、不跳过断言，也不重做 Figma。

本地辅助构建完成后，使用真实 Rust HTTPS Host、真实桌面桥接、Chromium 和固定字体运行同一 `workbench.spec.ts`：**15 项全部通过，41.5 秒**，包含价格计算、销售隔离、未知回执与去重、客户归集/连续编辑、财务报表及输出。最初本地构建遇到旧 h2 缓存损坏，清理该包生成物后重建成功；未改依赖。运行输出及 CI 失败节选保存在同名 log，结构化边界保存在 JSON。

这是本地辅助回归，不冒充 Windows 或现场验收；此次正常提交触发功能 CI，按用户规则不轮询、不等待，结果未核实。母/子安装包专项验证继续默认跳过，Host 与正常功能检查保留。

## CI #73：真实窗口共用连接流程

用户再次报告失败后读取 [CI #73](https://github.com/uniquenesssta/777/actions/runs/39197378072)（`1f62409`）：**host-sync 成功，48 项浏览器检查全部通过，installers 跳过**。真实 Tauri 窗口已启动、WebView2 CDP 已连接且生产页面来源核对通过；但 `windows-smoke.mjs:67` 仍直接填写折叠区内的证书，报 `element is not visible`。该真实窗口脚本未同步采用上轮浏览器修正，是本次失败根因；自然退出和下游检查不记通过。

新增按职责独立的 `desktop/tests/development-connection.mjs`，由浏览器工作台与真实 Windows 窗口脚本共同调用：证书区域未展开时先打开，再填写并提交。保留来源检查、真实原生 IPC、销售隔离及关闭清理门槛，不改产品、正式端 UI、授权或流水线，不延长超时或跳过检查。扫描其他证书填写入口，独立连接弹窗用例已有显式展开；正式端自动进入检查继续断言没有登录控件。

补充真实后台回归场景：管理员保存订单后退出，核对保存的连接仍在，再以销售身份登录并验证管理员订单/财务入口不可见。新场景最初核对已初始化 textarea 时采用精确包裹标签定位而失败；改为展开后按文本框名称前缀读取，再折回后登录，保持原生脚本的操作路径。此调整只涉及测试定位。

本地两个 MJS 语法检查及 diff 检查通过；使用真实 Rust HTTPS Host 和桌面桥接运行工作台套件，**16 项全部通过，52.8 秒**。这覆盖与 Windows 脚本共用的连接代码及后续业务，但不替代实际 Windows WebView2 验证。修复正常提交后不轮询、不等待新 CI，结果未核实；母/子安装包专项验证继续默认跳过。
