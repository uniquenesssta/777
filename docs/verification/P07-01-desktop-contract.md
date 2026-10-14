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
py -3 tools/p07_desktop_check.py --windows-smoke --jobs 1 --output reports/p07-01-windows-05
```

已在P07分支时只需`git pull --ff-only`，不要重复创建本地分支。工具先查已安装的Node/npm/固定Rust工具链、MSVC/SDK/WebView2与Python模块；缺失时给出补齐步骤并停止，不静默下载编译器。然后显式安装前端锁定依赖、`cargo fetch --locked`下载Rust crate，再构建所需release；最后创建临时Rust宿主/账户/订单/DPAPI profile；实际Tauri WebView2登录→报价→提交→销售隔离→退出并清理。本机窗口模式复用CI完整检查，不重复Clippy/debug测试构建或浏览器；CI/辅助完整模式仍执行全部原门槛。测试字体仅供完整模式的浏览器辅助，按已有固定hash下载，不安装系统字体。报告及原生截图保存在指定新目录；勿重用已存在目录。失败时保留report.json，不需从旧阶段重新跑。

实际人工预览使用`npm --prefix desktop run tauri dev`并填写获授权服务的HTTPS地址/证书/pin和本人账号；该入口可提交真实订单，应使用隔离宿主。当前自动工具只用临时数据，不安装服务、不访问实际E盘/共享盘。安装包/升级与多DPI验收不在本项。

## 当前证据与恢复

[检查证据](P07-01-checks.json)与原始辅助报告记录最终源码指纹、成功检查及修复前失败；辅助浏览器PNG不是原生Windows验收。Windows原生构建结果、DPAPI实测和用户视觉/交互待回传，不预记通过。01未收尾，02至04/P08未启动。

回退使用P06既有Python客户端与相同服务API；没有切换生产客户端或账本schema。代码回退不删除用户profile/未知请求记录，不以还原旧数据库覆盖新增订单。


## 本机资源和中断修复

用户第一次窗口运行在原静默`subprocess.run`中出现KeyboardInterrupt；具体子命令未被原工具落盘，不能从该堆栈推断Rust依赖缺失或编译报错。[回传](P07-01-windows-interruption-01.json)保持未完成结论；原实现的[Windows CI成功](P07-01-ci-evidence-01.json)仍有效。

Rust依赖已在Cargo.toml/Cargo.lock中声明，源码仓库不携带整个Cargo缓存；首次Cargo下载到用户缓存并编译属于开发验证。新入口先执行显式预检/下载阶段，按步骤实时打印并保存`command-NN.log`，report.json在开始/阶段切换/命令退出即保存。默认`--jobs 1`覆盖Cargo与测试线程的高并发环境；CI显式`--jobs 2`。Windows子进程低于正常优先级。此设置限制任务数、改善响应，不冒充CPU使用率的百分比硬上限。

本机`--windows-smoke`保留release构建、10项真实协议及实际Tauri WebView2窗口验证，完整fmt/严格Clippy/Rust及前端单元/浏览器验证继续由`--ci-checks`执行；本次工具修复同时把实际原生窗口链路加入Windows CI，避免只测构建/浏览器而漏掉退出问题。运行时Ctrl+C记录interrupted/退出码130并停止所属PID进程树，日志和partial报告保留；超时同样保留当前步骤。不会按进程名称终止机器上其他cargo/rustc或其他项目。

原本机01/03/04目录不覆盖，当前临时目录清理修复后使用上方新的05目录；无需删除Cargo缓存，之前成功编译的依赖可以复用。工具的Windows原生行为需CI/本机分别核对，辅助结果不能替代Windows实测。[本机入口修复证据](P07-01-runner-checks.json)保持。


Node兼容纠正：用户现有Node为22大版本。当前锁定Vite 8.3.4/Rolldown 1.2.13的实际`engines.node`及[Vite 8官方说明](https://v8.vite.dev/guide/)要求22.12+，其他锁定运行/开发依赖没有24下限。项目自身先前的`>=24.0.0`是过严限制，现将package.json、lock根元数据和预检统一为`>=22.12.0`，不改任何依赖版本/integrity。预检会显示真实完整版本；22.12及更新的22版本无需改用24，低于22.12时明确提示在22系列内补齐兼容版本。辅助实际使用官方SHA256核对的Node 22.12.0/npm 10.9.0运行完整流程；新CI采用从官方index核实的22.23.3/npm 10.9.9。此前Node 24的成功报告保留为原环境证据。


## release页面来源修复

用户观察release exe加载`http://127.0.0.1:1420/`且本机没有Vite。锁定Tauri 2.12.3的`is_dev()`由custom-protocol决定，tauri-macros 2.7.2在开发模式且有devUrl时不打入前端资源；`--release`优化不负责切换该模式。原手工Cargo命令和空default特性因此构成完整根因，不能靠启动Vite把生产验证变成开发验证。

Cargo默认现在启用`custom-protocol = ["tauri/custom-protocol"]`；验证release命令也显式启用。Windows build.rs按实际`tauri_build::is_dev()`拒绝release仍处于开发模式，`frontendDist`继续指向本地dist。Tauri CLI 2.12.2的[锁定源码](https://github.com/tauri-apps/tauri/blob/tauri-cli-v2.12.2/crates/tauri-cli/src/interface/rust.rs)会在常规dev时排除生产默认特性并传`--no-default-features`，在build时启用生产特性，现有`npm --prefix desktop run tauri dev`默认入口保留。

新CI/本机在release构建后执行`quote-desktop.exe --verification-build-info`：直接从该exe的Tauri Context读取模式及内嵌index/引用JS/CSS，任一缺失立即失败；只检查生成资源，不启动窗口、不读取用户配置或业务目录。辅助环境不能执行Windows Context，报告明确not_run_actual_Windows_required，不能把Cargo feature图当原生运行通过。

原生WebView2脚本连接后先记录`native-window-origin.json`并要求`http(s)://tauri.localhost`；Vite、浏览器错误页、伪相似域及非标准端口立即拒绝，保存失败截图，再继续等待真实登录控件。域名通过只证明页面来源，其后仍需完成原管理员提交/销售隔离/正常退出。错误内容从合并的实时stdout日志保留，不再丢失到空stderr字段。整体report保留来源诊断；失败不记录native通过。

[release修复证据](P07-01-release-checks.json)、[用户观察](P07-01-native-url-failure-01.json)与[上次CI成功范围](P07-01-ci-evidence-02.json)分列。无新增依赖版本、Cargo.lock/业务规则/数据schema变更，Figma与界面布局未改。无需清空Cargo缓存或启动Vite；release资源检查在[新Windows CI](P07-01-ci-evidence-03.json)与[本机03回传](P07-01-windows-evidence-03.json)中均通过，后者仍在关闭阶段失败。

## 原生窗口关闭工具修复

用户03[完整控制台原文](P07-01-windows-console-03.txt)显示：已拉取d9b4766，release exe内嵌index/JS/CSS并使用生产协议，10项真实Rust HTTPS/DPAPI检查通过，WebView2来源为`http://tauri.localhost/`，Node原生交互命令返回0；之后`communicate(timeout=30)`超时。末尾控制台摘要已另存[报告节选](P07-01-windows-report-03.json)，未取得完整report.json、源码指纹、native-webview.json或截图；原文worktree_dirty=true保持，不能补写干净源码或完整本机验收。

原脚本向该PID下所有顶层窗口发送WM_CLOSE。锁定[tao 0.37.1源文件](https://github.com/tauri-apps/tao/blob/37b7e8bc90a050e93be988df636f322c3ef147b6/src/platform_impl/windows/event_loop.rs)中的`create_event_target_window`创建`Tao Thread Event Target`：它也是顶层窗口，技术上带WS_VISIBLE，初始设置零尺寸/无标题；本机04实际枚举为16×16，所以可见性/面积均不能单独排除它。`thread_event_target_callback`对WM_CLOSE落入DefWindowProc，可能先破坏后续应用事件分发。旧工具没记录枚举/消息投递/父进程状态，因此03超时究竟停在何处不可从日志完整重建。

关闭验证现由`tools/p07_native_window.py`负责：以所属PID、配置中的主窗口标题、可见性和正面积唯一选中主HWND，排除事件辅助类；发送前重验所属/标题/句柄，检查PostMessage返回值，只发送一次。界面交互先等订单刷新按钮恢复可用；应用原有在途请求关闭保护不改。随后只等待桌面父进程自然退出且码0，超时/非零/无窗口/多匹配/消息失败均不通过，绝不靠kill取得通过。

桌面stdout/stderr改为普通日志文件，避免WebView2后代继承管道导致`communicate`等待EOF，混淆“父进程未退”和“输出尚未结束”；此机制有真实子进程回归，但不能反推用户本次一定由管道造成。`native-window-close.json`记录窗口清单、目标、投递与退出；`native-window-process.log`保存宿主输出；`native-window-cleanup.json`单独记录失败后的所属进程树强制清理。交互结果和关闭结果均汇入最终report，后者失败不再抹去前者。

[关闭修复检查](P07-01-close-checks.json)保持；本机04已确认实际Tauri交互/自然退出通过，剩余临时目录清理失败见下节。P07-01留now，不启动02至04/P08。已在该分支的复验命令：

```powershell
& {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw '拉取失败，已停止' }
    py -3 tools/p07_desktop_check.py --windows-smoke --jobs 1 --output reports/p07-01-windows-05
    if ($LASTEXITCODE -ne 0) { throw '桌面验证未通过，保留报告后停止' }
}
```

## WebView2临时目录释放等待

[本机04原文与核对](P07-01-windows-evidence-04.json)显示：生产页面、10项协议、真实Tauri/WebView2交互全部通过；主窗口在0.031秒内自然退出，码0，无强制终止。随后`TemporaryDirectory.cleanup()`删除`desktop/webview2/EBWebView/BrowserMetrics/*.pma`时遇到WinError5。完整report.json/本机源码指纹未附，worktree_dirty=true保留；控制台已有交互与退出分项通过，不能再归为窗口关不掉。

这是临时目录清理时序的问题；[微软用户数据目录文档](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder#delete-user-data-folders)说明宿主关闭后文件仍可能被浏览器进程占用，需要等待资源释放。当前工具在关闭/停止自身临时宿主后，对本轮生成的临时目录限时20秒、每0.2秒重试暂时性占用删除；不改应用关闭行为，不终止机器上其他WebView2/Edge进程。

开始删除前核对TemporaryDirectory对象路径、系统临时父目录/随机前缀、desktop profile和`production:false`标记；错误路径必须位于该临时根内，其他错误立即保留失败。允许前次删除已经移除标记的重试，直到根目录实际不存在才记清理通过。超时保留失败与临时根，不使用ignore_errors。`native-sandbox-cleanup.json`单独记录尝试、错误码/相对路径和耗时，最终报告保留交互、关闭、进程清理和目录清理的独立状态；清理异常不覆盖已经存在的首个流程异常，用户中断保持中断。

[专项证据](P07-01-cleanup-checks.json)包含24项合并回归（22通过、2项Windows专属待CI）；锁定路径处理和夹具时序改进后13项相关回归（11通过、同2项待CI）通过。新CI继续执行真实Win32窗口与文件占用检查，以及完整Tauri/WebView2链路；本机新05复验临时目录完整清理，已通过的交互/自然退出证据保持，01尚未收尾。
