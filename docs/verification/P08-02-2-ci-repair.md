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
