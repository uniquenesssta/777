# P06-02 Rust账本与兼容服务适配

用户2026-10-13 21:26:19（Asia/Shanghai）“收尾01开始02”，[01验收](P06-01-acceptance.json)绑定原Windows32指纹/21项Rust/58项Python/561对照；原报告保持。唯一`stage/p06-rust-core`，02真实基线`c8ad540`。已实现，辅助通过，待本轮Windows原生验证/用户验收；03/04未启动。

## 当前交付

`crates/quote-ledger`通过固定Rust1.97.1、rusqlite0.37.0的内嵌SQLite3.50.2实现同一ledger-v1。复用已冻结DDL并独立重算sqlite_master签名，schema hash仍为`96619d105269c85fa0d0354050ca97af0af290ba6485913867ed070962aff003`，没有财务表迁移或原件覆盖。应用ID/版本/hash/完整性/外键不兼容即拒绝。更高/未知版本没有登记的迁移路径，原件保留；本轮“迁移”是同一v1账本的离线后端交接，不虚构v2财务schema。

每次写使用BEGIN IMMEDIATE、WAL、synchronous=FULL，订单/全明细/原始与规范价格/回执/审计/ledger revision原子落库。原请求先按与Python完全相同的排序紧凑UTF-8 JSON指纹核查，再检查当前价格或订单revision；改主体/负载拒绝，换价后的原请求仍返回原回执。备注只追加；作废/恢复只改状态/revision，不改历史金额。Rust调用P06-01核心重算，收入/成本/利润及小计先校验容量；账本有效汇总用BigInt，不能让多个合法大单在SQL SUM时溢出。

Windows路径在Rust再次核验绝对本机固定磁盘、父目录与文件类型，拒绝UNC、映射盘、链接/重解析与不兼容附属文件；创建只使用独占新文件。worker为私有标准输入/输出单请求进程，金融内容和主体不放命令参数，不打开监听端口。父进程超时会终止并等待该进程；无响应/退出的写返回COMMIT_UNKNOWN，客户端按同request_id查询/重试；无Python自动回退。

`quote_service/rust_ledger.py`只由已认证的服务恢复Principal后调用；客户端actor/role/财务总额依旧由旧协议拒绝。现有Uvicorn HTTPS/TLS、Auth账户/会话/目录与备份计划、销售允许字段投影及母子客户端协议保持。Rust后端的计算/价格校验/真实财务事务归Rust；Python查询与角色投影仅只读访问，直接Python写连接被阻断。不存在两个活跃财务账本。完整Rust HTTP宿主与实机窗口/资源演练留P06-04，Tauri留P07。

## 导入和备份

旧格式适配器继续重新读取原字节并生成内存SQLite预演；所有Python导入SQL只作用于`:memory:`。原来源/归属/复核SHA/隔离认可与稳定映射政策保持。Rust仅接受固定7表追加delta，在预计ledger revision下原子应用，重新解析每个价格并重算所有订单/逐行/总额，核对来源字节SHA、回执/审计链和最终inventory才COMMIT。未知SQL/字段类型或不一致金额拒绝；中途退出无半批，提交后退出查原回执；相同来源不会再入账。源格式的Rust读取/生成库选型仍在P06-03，当前Python格式桥接有明确退出任务，不建立第二个权威金额核心。

Rust使用SQLite在线backup创建独占新目标，刷盘、核对schema/金额/行数及独立原生重开后才返回；P05备份清单与第二个Python读取器独立恢复继续核对。完整主机包v3增加固定私有`rust-ledger-worker.exe`及`rust-notices.txt`，同时保存原账户/TLS/维护配置与输出队列/原缓存文件；旧v1/v2保持兼容。恢复仅新目录，选中的后端/worker pin保留，旧会话撤销，默认维护状态，不自动启动第二写端。包内原生程序来自管理员已登记的执行文件；恢复包视为主机私有可信材料，销售端不接收它。

## 离线后端选择与恢复

`select-backend`持有同一service-owner锁，需要管理员认证及完整维护备份。先复制新私有执行文件/许可、核对SHA与两端inventory，再原子发布配置；发布前失败保留旧选择并清理本次新文件，发布后回执丢失按配置读回，重复同版本选择不重做迁移。未知同名文件不采纳；执行文件损坏即停用，不能自动启用Python。选择python同样离线/备份/核对，使用包含全部最新订单的同一账本，Rust资源继续登记，避免恢复过期库丢增量。

当前只在临时副本测试；不要求对192.168.4.38、真实E盘或现有主机执行下列切换。本机明确启用时步骤如下，运行服务前须先停旧进程以释放owner锁：

```powershell
py -3 tools/quote_service_host.py select-backend --root '明确的本机独立主机目录' --admin manager --backend rust --binary (Resolve-Path -LiteralPath '.\target\release\quote-ledger.exe').Path --notices (Resolve-Path -LiteralPath '.\THIRD_PARTY_NOTICES.md').Path
```

CLI要求绝对本机路径，实际使用将root换为已明确的主机绝对路径，示例已解析binary/notices；密码交互输入，不写命令行。恢复选择使用同一命令的`--backend python`，省略binary/notices。这不是本轮需要用户执行的验证命令。

## Windows隔离检查

65项专项涵盖Native进程并发/回滚/提交后丢回执、双方向Python请求重放、价格与订单CAS、明确后端切换中断/重启/owner锁、真实TCP HTTPS原客户端/鉴权/成本过滤、搜索与输出/完整v3恢复；原完整辅助594项通过。25项Rust测试、fmt/Clippy/release构建及同一561组影子对照通过（含原黄金53/53），[依赖许可证](P06-02-dependencies.json)锁定全部48外部包并保存许可全文。完整日志及初期夹具/辅助执行权限问题在[02证据](P06-02-checks.json)保留，不改01/P05原报告。

第二轮已核对通过，以下保留已执行入口供复现；当前无需重跑：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 tools/p06_ledger_check.py --windows-smoke --output reports/p06-02-windows-02
```

沿用01已验证Rustup/MSVC与现有服务Python依赖，首次SQLite C源码编译会比缓存构建慢。入口核验真正Windows AMD64 MSVC和固定工具链，执行全部65项与561对照，并额外验证真实DPAPI、Rust提交后退出/原回执、原HTTPS客户端、v3原生恢复、Windows私有目录属性/ACL和临时清理。不启动GUI，不访问真实共享/E盘、安装服务或切换生产。辅助`--checks-only`不记录Windows通过。输出必须新reports子目录，后续若有相关变更复查须换新编号，保留已有文件。

第二轮`report.json`与`comparisons.json`已回传并核对通过，具备收尾条件待用户验收；03/04未启动，原01/P05入口无需重跑。


首轮7338d7a的[原报告](P06-02-windows-report-01.json)/[比较文件](P06-02-windows-comparisons-01.json)保留。83项LF指纹、Rust25项、65个完整测试ID与561对照已独立核对；专项63通过/2错误，均为验证代码：SQLite连接未关闭导致Windows清理失败、模拟os.name导致Path类型错误。[修复证据](P06-02-windows-evidence-01.json)及[65项辅助回归](P06-02-windows-fix-checks.json)登记。首轮当时尚未执行的Windows原生DPAPI/ACL/备份恢复现已由第二轮补齐；首轮失败与修复记录保持，P06-01和P05已通过入口无需重跑。


[第二轮原报告](P06-02-windows-report-02.json)/[原比较文件](P06-02-windows-comparisons-02.json)按原始字节归档。[独立核对](P06-02-windows-evidence-02.json)确认bf18f45的83项LF指纹、65/65专项完整日志、25项Rust测试/fmt/Clippy/release、48个外部依赖及561/561精确比较匹配；Python参考结果已逐项重算，首轮两处错误消失。实际Windows原生Rust/DPAPI未知提交核查、旧HTTPS协议与角色/文本身份、v3原生恢复/原回执/旧会话撤销、Hidden/System/保护DACL及清理通过。02具备收尾条件待用户验收；当前无需重跑，03/04未启动。范围仍为临时主机，不包括GUI、安装服务或真实数据切换。
