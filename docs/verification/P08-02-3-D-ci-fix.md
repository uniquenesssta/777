# P08-02-3 D：Windows CI 修复

2026-10-20（Asia/Shanghai）；分支 `stage/p08-cutover`，修复基线 `057e2914e63856b752e0ec5150be4107e967d1ce`。用户反馈“未通过”后，直接读取该 SHA 的已结束 [CI #84](https://github.com/uniquenesssta/777/actions/runs/39366809561)、任务摘要及三个失败任务的完整日志。实际结果和修复检查见 [证据](P08-02-3-D-ci-fix.json)。

最新进度：CI #85 已验证下述原生异步和测试清理修复；余下原生联测在 Python 检查器清理临时目录时失败，修复及验证见文末。新提交的 Windows 结果仍待核实。

## CI #84：失败与原因

| 任务 | 已核实结果 |
| --- | --- |
| host-sync | 成功，包括双 TLS 节点复制及 C 的应用/裁定检查 |
| desktop-contracts | 严格分析编译 Windows 原生入口时 E0277；后续业务/UI/恢复步骤未执行 |
| device-presentation | Windows 原生入口构建时同一 E0277，未进入实际展示验证 |
| offline-orders | 严格分析成功；本机测试 36 成功、1 失败，后续原生 TLS 联测未执行 |
| installers | 按既有约定跳过 |

D 把 SQLite 连接加入 Desktop 后，Desktop 可移动但不能共享。新增 `local_settings(&self)` 把共享 Desktop 引用保留到网络 await 之后，使整个调用 future 不满足 Tauri 的 Send 要求；前轮本地 Linux 入口没有编译 Windows Tauri 宏，未拦住该约束。这是源码兼容问题，不是 CI 超时。

另一失败是既有数据源重载测试：断言完成后仍持有 Desktop 内的数据库连接，立即删除其目录。Windows 报文件占用错误 32。开发者 pending 保护测试存在同样的连接生命周期，也一并修正。

## CI #84：修改和验证口径

- `local_settings` 改为独占借用，保持现有串行 Desktop 调用及真实设置请求/缓存。SQLite 无需取得 Sync，没有新增不安全线程声明，也没有持业务事务等待网络。
- 新增独立 `client/future_contract.rs`，对真实 execute、directory_context、sync_tick future 做编译期 Send 约束。先保留旧源码验证，实际失败并指向原 local_settings await；修正后同一约束通过。该项属于静态类型检查，不声称执行 Windows UI 或网络业务。
- 两个测试均先释放 Desktop，再执行原有目录删除断言；重载、包目标不变、原 pending 不变及清理断言全部保留。未重试掩盖错误、删除测试或修改工作流门槛。
- 修复后本地运行：静态检查、严格 Clippy、Rust 格式检查通过；manager/sales 运行角色各 36 项、开发者角色 37 项本机自动测试通过。不同角色有重叠，不相加成独立用例数。

首轮修复的本地环境为 Linux，上述当时属于辅助结果；其 Windows 编译和原测试随后由 CI #85 核实，见下节。首轮未重跑真实 TLS 联测、未改现场或正式 UI，无新增日志，无最终母/子安装包或构建准备专项验证。提交后正常触发 CI，不轮询、不等待，用户回报结果后再读取对应已结束任务。


## CI #85：联测夹具连接释放

用户再次反馈“未通过”后，核实 `9a0f68e` 对应 [CI #85](https://github.com/uniquenesssta/777/actions/runs/39373611132)：desktop-contracts、device-presentation、host-sync 均成功；offline-orders 的严格分析、37 项 Windows 本机测试及两角色原生程序构建成功，最后的原生联测失败。installers 按约定跳过。

已下载并读取原生联测 artifact `12243041833` 的 failure.txt/report.json，ZIP SHA256 与上传日志一致。失败位于 `f.close()` 清理临时目录，Windows 错误 32 指向 desktop-manager/offline.sqlite3。检查器用 `with sqlite3.connect(...)` 结束读取事务，该上下文不会关闭连接；即使原生程序已退出，Python 检查句柄仍可能阻止 Windows 删除文件。不能把本轮联测登记为通过。

将独立读取连接的生命周期拆到 `tools/p08_local/storage.py`，正常读取及异常退出都明确 close；三个原有读取点共用该入口，订单、回执、历史及销售隔离断言不变。两个真实 SQLite 回归用例验证上下文退出后连接确已关闭，读取异常仍保留；使用原上下文行为时两项均失败，修正后通过。临时目录删除仍须成功，不忽略清理错误，不靠回收时机或增加重试掩盖占用。

同时精简检查器控制台输出为状态、结果及报告位置，完整源码指纹仍保存在 report.json，不再把数百项摘要刷入 CI 控制台。失败退出码及完整 failure.txt 保留。

本轮重新构建运行用 Host/Ledger 和 manager/sales 原生驱动，完整隔离 TLS 断网、重开、独立续传和清理流程已通过，实际结果见同一[证据](P08-02-3-D-ci-fix.json)的 follow_up_ci85。该环境是 Linux，不能代替新 Windows 文件解锁和完整原生联测结果；源码、UI、现场、正式日志和最终封包策略保持原范围，不推进 E。
