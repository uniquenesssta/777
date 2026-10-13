# P06-01 Rust领域核心与核对入口

用户授权“收尾P05-04开始P06-01”；唯一分支`stage/p06-rust-core`基于P05收尾`7710132`。P05原Windows52/52及原报告保持，P05归档old、P06移入now。01仅独立领域影子交付；02至04未启动，Python应用/服务/账本仍使用现有实现。

## 数值、配置与草稿

`crates/quote-core`无Tk/Tauri/UI、文件、网络或数据库依赖。BigInt系数/刻度保留精确十进制，加减乘不舍入，表达式每次除法精确HALF_UP到12位，余数采用floor语义。field≤1e9/12有效小数位，中间≤1e45/60位，原文本256字符、规范表达式80字符、AST64节点/16层、10000行；每行收入/成本结算整数分，利润相减，顺序折扣取前序已结算小计。对称i64容量同时检查收入/成本/利润与每个中间小计，错误不保留部分权威金额。margin使用整数比率，不取显示文本或浮点。

有界配置JSON解析保留数字原token、商品顺序及原UTF-8/BOM/CRLF文本；重复键/未知字段/坏商品整份拒绝。新格式`single/qty_only`只收布尔值；旧字典需显式单件名单，可为空；重复、折扣保留名及目录类型检查与Python一致。一次坏刷新不替换上个有效配置。目录这里只是文本元数据，显式继承/角色访问继续归应用和服务管理。

草稿使用稳定规范draft_id及字符串u64 revision；私有请求generation阻断同ID不同会话的旧完成，worker只运行不可变请求。输入/客户身份/价格/来源变化立即失效，值变回仍需新计算；观察新版本不会静默绑定。换价需显式刷新、重算、匹配revision确认。三种输出共享冻结金额，dispatch重新检查且被阻断零回调，writer异常交给调用者处理。此门槛不认证、不提交订单，不把成本结构直接发给销售。

共享[JSON契约](P06-01-protocol.json)通过本地`quote-shadow`标准输入输出进行核对：严格命令/动作字段，有界16MiB单消息。金额分、金额显示及revision使用字符串，未使用f64链路。源配置NaN/Infinity、字节/深度/数字长度/商品数量及UTF-8错误有明确诊断。Rust私有Completion不能由外部JSON伪造；稳定身份并非服务主体，后续服务仍须恢复真实认证身份。

## 依赖与验证

固定Rust **1.97.1**，minimal加rustfmt/Clippy，MSVC目标由实际Windows核验；Cargo.toml精确直接版本、Cargo.lock锁定全部15包校验和。[依赖/许可证](P06-01-dependencies.json)记录直接/传递许可，根THIRD_PARTY_NOTICES保留所选MIT及Unicode全文，原项目Apache-2.0 LICENSE不变。BigInt系数/刻度满足现有1e45/60位中间要求，固定96位/28刻度decimal不能直接覆盖它。未引入Excel、HTTP或Tauri库，包体/性能留对应任务实测。

检查器直接读取原[53例黄金](../baseline/p01-04-golden.json)，历史候选标签按[P01批准](../baseline/p01-acceptance.json)映射；原期望、资产及Python参考不改。逐例核对全行/总额/规范值/原快照/字符串分/显示/错误字段行号/警告，200组确定性金额另与原独立有理数oracle核对。配置与状态动作检查原始token、失败保留、三种输出零调用/同载荷、晚到/跨草稿/ABA及换价确认；原Python核心/配置/状态和检查器回归一起运行。Rust测试另覆盖精度/溢出/坏结果门槛/同ID不同会话/原子失败，fmt与Clippy全部警告作为失败。

首次开发对照556组中的4处错误原因不一致（布尔常量中e误作指数）已修正，原差异列在[检查证据](P06-01-checks.json)。辅助环境通过不记成Windows通过；报告绑定实际提交、工作区状态、LF源码指纹、工具链、完整命令日志、依赖表、逐例请求/双方结果SHA及差异路径。任一差异阻断替换。

## Windows运行

先有Rustup（[官方安装入口](https://www.rust-lang.org/tools/install)）及Visual Studio C++ Build Tools的MSVC/Windows SDK。已有环境无需重复安装；本阶段尚不需要WebView2或Tauri。现有Python依赖沿用已验证环境。

在仓库PowerShell中切换**唯一P06分支**：

```powershell
git remote set-branches --add origin stage/p06-rust-core
git fetch origin
if ($LASTEXITCODE -ne 0) { throw '下载失败，先停止' }
git switch --track -c stage/p06-rust-core origin/stage/p06-rust-core
if ($LASTEXITCODE -ne 0) { throw '切换失败，先停止' }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
rustup toolchain install 1.97.1 --profile minimal --component rustfmt --component clippy
if ($LASTEXITCODE -ne 0) { throw 'Rust工具链准备失败，先停止' }
py -3 tools/p06_core_check.py --windows-smoke --output reports/p06-01-windows-01
```

若本机已有同名P06分支，切换用`git switch stage/p06-rust-core`，其余步骤相同。Rustup须默认Windows AMD64 MSVC host；检查器拒绝Linux或交叉目标冒充原生验证。输出须为新reports子目录；再次运行换02等新目录，不覆盖旧报告。首次下载/编译可能较慢，失败摘要和完整`report.json`会保留；Rust工具链/MSVC缺失给出明确失败，不继续真实I/O。

通过后回传新目录中的`report.json`与`comparisons.json`供完整指纹/清单核对。只验证本地构建和纯核心，无窗口需观察，不访问UNC、真实E盘、原件或生产账本。P06-01 Windows通过及用户验收前不启动02。

回退：退出影子程序，继续现有Python；无schema/数据库/客户端切换，无需恢复真实数据。真实主机安装/身份、E盘权限与首次历史迁移继续按P05交接和P07/P08门槛处理。
