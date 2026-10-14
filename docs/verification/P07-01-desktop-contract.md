# P07-01 桌面交互与真实服务接入

本项从P06收尾`7a243d5`建立唯一`stage/p07-tauri-desktop`，按用户2026-10-14“开始P07”实施。[当前任务书](../now/P07-tauri-desktop.md)保留01验收及02至04门槛。设计来自本仓库`Figma@c517d8b`的当前批准稿，[映射及差异](../design/P07-component-map.md)记录了节点、原资源和尚待视觉确认的管理页。未修改Figma文件或生产主机/共享盘。

## 当前行为与角色

| 页面/流程 | 管理员 | 销售 |
| --- | --- | --- |
| 登录、报价/反馈 | 显式HTTPS/PEM/pin、真实账号；面积/单件、K只读价格、顺序折扣、逐行错误、冻结总额/成本/利润 | 同一编辑链，服务DTO及页面不含成本/利润 |
| 确认提交 | 本次计算的相同snapshot/revision；确认取消不写，价格已变服务拒绝 | 同一规则，不信任前端role |
| 订单/详情 | 全量q/state搜索、20行分页、返回页/筛选/滚动；冻结历史价及金额 | 本人范围、其他账号订单不可读 |
| 备注/状态 | 追加备注、原因必填作废/恢复，订单revision检查 | 只追加本人备注，无作废/恢复能力 |
| 价格/利润 | 商品增删改、价格版本CAS发布；原订单不改价，当前草稿过期；范围统计取服务权威 | 无相关路由/命令授权/私有字段 |
| 输出任务 | 报价Excel/完整报价PNG/私有财务Excel，进度、失败原任务重试 | 仅获授权的报价Excel/PNG，不接收私有报表路径 |
| 存储与备份 | 查看服务地址、发布导出/图片完整UNC目录；查看备份路径/状态、执行维护备份 | 显性查看并自动继承目录，只读不可改；只保存自身连接 |

UI反馈采用页内提示及逐行错误，不另造与当前Figma相冲突的反馈Tab。管理员账号配置、宿主部署/备份策略变更仍使用已交付维护入口；历史导入与生产迁移留P08，不把维护命令伪装成桌面已支持的功能。设计中的静态时间/创建人筛选没有对应服务接口，本项只展示实际支持的搜索/状态。

## 状态、写入与恢复

- React仅持有原文草稿及服务投影；金额显示为整数分十进制字符串加BigInt格式化，无JS浮点金额运算。revision使用字符串，验证含大于2^53值。财务计算/成本和提交重验归quote-core/quote-host/quote-ledger所有，ledger-v1及既有服务API不变。
- 编辑/删行/折扣/身份/价格刷新立即失效。迟到计算不能覆盖新revision；Rust也比较本进程冻结snapshot/revision，服务再次检查当前价格版本。不可用/未计算/无效/过期时不可提交。
- 确认保存后才清理相同原请求草稿。提交期间新增编辑保留且失效；核查原回执仅匹配原snapshot/details后清理，避免抹掉新草稿。原始输入草稿本机保存；token/密码/成本价格/权威计算不写入草稿。
- Rust会话只在内存；连接及待核查请求在固定AppLocalData profile使用Windows DPAPI。发送前独占写入原request_id/body/主体/URL/pin并sync。未知/超时/5xx保留该原请求，重新登录只能同账号/服务核查；先查回执，再按原请求重试，不生成第二个request_id。
- 已确认写成功而随后详情/列表刷新失败时显示“已保存，但视图刷新失败”；草稿/资格按原成功结论处理，刷新不重发写入。备注拒绝保留输入；原备注不可覆盖。输出任务和财务提交分离，失败只重试原job，不重复入账。
- 列表使用真实签名view，筛选/当前账本变化导致旧页拒绝时明确重新读取；不把失败解释为空账本。任务页轮询服务状态，IPC async且Rust串行保护会话；关闭正在执行的请求时提示等待，未知记录独立保留。

## 桌面与安全边界

`desktop/src-tauri`仅main窗口`desktop_action`类型化Action；serde拒绝未知字段，没有任意HTTP路径、SQL、shell或文件写命令。最小capability只含该命令及必要事件listen/unlisten，CSP仅本地资源和IPC，无远程UI。客户端通过Rustls HTTPS访问既有服务，不直接打开SQLite/Excel/共享目录。

连接要求HTTPS根URL、单一PEM证书及64位小写SHA256。固定pin在登录前和握手中核对，另验证有效期、SAN、原自签名和TLS1.2/1.3握手签名。原宿主自签名CA=true证书会被通用WebPKI叶证书路径拒绝，已用精确pin验证器兼容，不关闭身份/有效期/签名校验；错误pin/过期/错误SAN均拒绝。请求不跟重定向/代理，限制大小和超时。

上述为01所需最小实现，P07-02继续直接invoke/未知窗口/路径/事件泄漏及完整威胁边界专项审计，不能据此登记02已验收。

## 依赖与成本

| 选择 | 必要性与替代 | 锁定/许可/成本 |
| --- | --- | --- |
| Tauri 2.12.3 / build 2.7.2 | Windows宿主及类型化IPC，复用系统WebView2；Electron会额外分发独立浏览器 | Cargo.lock；MIT/Apache-2.0；Windows原生包体/内存待04实测 |
| React 19.3.0、TS 5.9.3、Vite 8.3.4 | 多页状态/组件及可复现本地打包；无额外路由/全局状态框架；普通DOM方案需自管同等状态 | package-lock；MIT/Apache-2.0；当前前端体积见依赖manifest实测 |
| Radix Dialog 1.3.1 | 模态焦点/键盘/可访问性，避免自写焦点陷阱；项目组件/CSS直接复用Figma token | MIT；仅Dialog，不引入整套组件库或Tailwind |
| reqwest 0.13.5 / rustls 0.23.45 / x509-parser 0.18.1 | Rust会话内HTTP、精确证书身份与旧CA证书兼容；WebView fetch会暴露token且需额外网络能力 | 默认reqwest功能关闭，ring复用既有栈；MIT/Apache-2.0；不引入HTTP插件/系统代理 |
| Playwright 1.64.0 / tsx 4.21.0 | 开发验证真实页面状态与金额字符串，非生产依赖 | CI用已安装Edge；辅助环境浏览器单独记录，不加入产品锁 |

[完整Windows依赖图/npm锁及源许可](P07-01-dependencies.json)记录290个Rust可达依赖、118个npm锁条目（包括条件平台构建包）。已有P06版本未移除/升级，Cargo.lock只扩展及消歧；Linux/GTK仅可能存在于跨平台锁元数据中，不增加Linux产品。MPL-2.0库按未修改源使用，源地址/许可保留在[desktop notices](../../desktop/THIRD_PARTY_NOTICES.md)。原矢量许可与字体授权见[资产许可](../design/figma-asset-licenses.md)；生产尚未分发字体文件。最终Windows安装内容、许可与实际资源开销留P07-04核验。

## Windows隔离验证

Windows CI先构建MSVC/Tauri并跑严格fmt/Clippy、Rust测试、前端类型/构建/状态测试、真实Rust HTTPS协议及Edge页面交互；其结果与本机原生WebView2验收分列。CI开始后不持续轮询。

本机前置：Node.js 22.12.0及以上、Rust 1.97.1（MSVC与Windows SDK/build tools）、Python 3.12、WebView2 Runtime。已有P06工具链/依赖可复用；新增Node前端环境。首次切到唯一P07分支：

```powershell
git remote set-branches --add origin stage/p07-tauri-desktop
git fetch origin
if ($LASTEXITCODE -ne 0) { throw '下载失败' }
git switch --track -c stage/p07-tauri-desktop origin/stage/p07-tauri-desktop
if ($LASTEXITCODE -ne 0) { throw '切换失败，先停止' }
py -3 -m pip install -r requirements-baseline.txt -r requirements-service.txt
if ($LASTEXITCODE -ne 0) { throw '验证依赖失败' }
py -3 tools/p07_desktop_check.py --preflight --output reports/p07-01-preflight-01
if ($LASTEXITCODE -ne 0) { throw '环境预检未通过，按报告补齐环境后再运行' }
py -3 tools/p07_desktop_check.py --windows-smoke --jobs 1 --output reports/p07-01-windows-02
```

已在P07分支时只需`git pull --ff-only`，不要重复创建本地分支。工具先查已安装的Node/npm/固定Rust工具链、MSVC/SDK/WebView2与Python模块；缺失时给出补齐步骤并停止，不静默下载编译器。然后显式安装前端锁定依赖、`cargo fetch --locked`下载Rust crate，再构建所需release；最后创建临时Rust宿主/账户/订单/DPAPI profile；实际Tauri WebView2登录→报价→提交→销售隔离→退出并清理。本机窗口模式复用CI完整检查，不重复Clippy/debug测试构建或浏览器；CI/辅助完整模式仍执行全部原门槛。测试字体仅供完整模式的浏览器辅助，按已有固定hash下载，不安装系统字体。报告及原生截图保存在指定新目录；勿重用已存在目录。失败时保留report.json，不需从旧阶段重新跑。

实际人工预览使用`npm --prefix desktop run tauri dev`并填写获授权服务的HTTPS地址/证书/pin和本人账号；该入口可提交真实订单，应使用隔离宿主。当前自动工具只用临时数据，不安装服务、不访问实际E盘/共享盘。安装包/升级与多DPI验收不在本项。

## 当前证据与恢复

[检查证据](P07-01-checks.json)与原始辅助报告记录最终源码指纹、成功检查及修复前失败；辅助浏览器PNG不是原生Windows验收。Windows原生构建结果、DPAPI实测和用户视觉/交互待回传，不预记通过。01未收尾，02至04/P08未启动。

回退使用P06既有Python客户端与相同服务API；没有切换生产客户端或账本schema。代码回退不删除用户profile/未知请求记录，不以还原旧数据库覆盖新增订单。


## 本机资源和中断修复

用户第一次窗口运行在原静默`subprocess.run`中出现KeyboardInterrupt；具体子命令未被原工具落盘，不能从该堆栈推断Rust依赖缺失或编译报错。[回传](P07-01-windows-interruption-01.json)保持未完成结论；原实现的[Windows CI成功](P07-01-ci-evidence-01.json)仍有效。

Rust依赖已在Cargo.toml/Cargo.lock中声明，源码仓库不携带整个Cargo缓存；首次Cargo下载到用户缓存并编译属于开发验证。新入口先执行显式预检/下载阶段，按步骤实时打印并保存`command-NN.log`，report.json在开始/阶段切换/命令退出即保存。默认`--jobs 1`覆盖Cargo与测试线程的高并发环境；CI显式`--jobs 2`。Windows子进程低于正常优先级。此设置限制任务数、改善响应，不冒充CPU使用率的百分比硬上限。

本机`--windows-smoke`保留release构建、10项真实协议及实际Tauri WebView2窗口验证，完整fmt/严格Clippy/Rust及前端单元/浏览器验证继续由`--ci-checks`执行。运行时Ctrl+C记录interrupted/退出码130并停止所属PID进程树，日志和partial报告保留；超时同样保留当前步骤。不会按进程名称终止机器上其他cargo/rustc或其他项目。

原本机01目录不覆盖，修复后使用上方新的02目录；无需删除Cargo缓存，之前成功编译的依赖可以复用。新工具的Windows进程清理与原生预检仍由新CI/本机验证，辅助10项不能替代Windows实测。[修复证据](P07-01-runner-checks.json)保存相应边界。


Node兼容纠正：用户现有Node为22大版本。当前锁定Vite 8.3.4/Rolldown 1.2.13的实际`engines.node`及[Vite 8官方说明](https://v8.vite.dev/guide/)要求22.12+，其他锁定运行/开发依赖没有24下限。项目自身先前的`>=24.0.0`是过严限制，现将package.json、lock根元数据和预检统一为`>=22.12.0`，不改任何依赖版本/integrity。预检会显示真实完整版本；22.12及更新的22版本无需改用24，低于22.12时明确提示在22系列内补齐兼容版本。辅助实际使用官方SHA256核对的Node 22.12.0/npm 10.9.0运行完整流程；新CI采用从官方index核实的22.23.3/npm 10.9.9。此前Node 24的成功报告保留为原环境证据。
