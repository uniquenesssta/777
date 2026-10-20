# P08-02-3 D：Windows CI #84 修复

2026-10-20（Asia/Shanghai）；分支 `stage/p08-cutover`，修复基线 `057e2914e63856b752e0ec5150be4107e967d1ce`。用户反馈“未通过”后，直接读取该 SHA 的已结束 [CI #84](https://github.com/uniquenesssta/777/actions/runs/39366809561)、任务摘要及三个失败任务的完整日志。实际结果和修复检查见 [证据](P08-02-3-D-ci-fix.json)。

## 失败与原因

| 任务 | 已核实结果 |
| --- | --- |
| host-sync | 成功，包括双 TLS 节点复制及 C 的应用/裁定检查 |
| desktop-contracts | 严格分析编译 Windows 原生入口时 E0277；后续业务/UI/恢复步骤未执行 |
| device-presentation | Windows 原生入口构建时同一 E0277，未进入实际展示验证 |
| offline-orders | 严格分析成功；本机测试 36 成功、1 失败，后续原生 TLS 联测未执行 |
| installers | 按既有约定跳过 |

D 把 SQLite 连接加入 Desktop 后，Desktop 可移动但不能共享。新增 `local_settings(&self)` 把共享 Desktop 引用保留到网络 await 之后，使整个调用 future 不满足 Tauri 的 Send 要求；前轮本地 Linux 入口没有编译 Windows Tauri 宏，未拦住该约束。这是源码兼容问题，不是 CI 超时。

另一失败是既有数据源重载测试：断言完成后仍持有 Desktop 内的数据库连接，立即删除其目录。Windows 报文件占用错误 32。开发者 pending 保护测试存在同样的连接生命周期，也一并修正。

## 修改和验证口径

- `local_settings` 改为独占借用，保持现有串行 Desktop 调用及真实设置请求/缓存。SQLite 无需取得 Sync，没有新增不安全线程声明，也没有持业务事务等待网络。
- 新增独立 `client/future_contract.rs`，对真实 execute、directory_context、sync_tick future 做编译期 Send 约束。先保留旧源码验证，实际失败并指向原 local_settings await；修正后同一约束通过。该项属于静态类型检查，不声称执行 Windows UI 或网络业务。
- 两个测试均先释放 Desktop，再执行原有目录删除断言；重载、包目标不变、原 pending 不变及清理断言全部保留。未重试掩盖错误、删除测试或修改工作流门槛。
- 修复后本地运行：静态检查、严格 Clippy、Rust 格式检查通过；manager/sales 运行角色各 36 项、开发者角色 37 项本机自动测试通过。不同角色有重叠，不相加成独立用例数。

本次环境为 Linux，上述属于辅助结果。Windows 编译、文件解锁及完整原生运行须由修复提交的新 CI 核实；未重跑本轮真实 TLS 联测、未改现场或正式 UI，无新增日志，无最终母/子安装包或构建准备专项验证。前轮 Windows 主机通过和局部测试通过不能代替整轮 D 通过。提交后正常触发 CI，不轮询、不等待，用户回报结果后再读取对应已结束任务。
