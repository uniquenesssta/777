# P06 Rust领域核心与存储/服务适配

状态：执行中。用户2026-10-13 20:25:31（Asia/Shanghai）“收尾P05-04开始P06-01”授权，从P05收尾77101320deda2f624a215ade67c8ea5306d1c0a4建立唯一stage/p06-rust-core。[P05范围交接](../verification/P05-acceptance.json)保留真实部署/历史切换待办。P06-01已按[用户接续](../verification/P06-01-acceptance.json)验收收尾，无需重跑。P06-02已按[用户接续](../verification/P06-02-acceptance.json)验收，原Windows证据保持；P06-03已按[用户接续](../verification/P06-03-acceptance.json)验收；P06-04从89f7138按[启动记录](../verification/P06-04-start.json)执行，独立Rust宿主已实现，656完整辅助/42 Rust通过，本机Windows及用户验收待回传。

P01共用验证材料：[53例静态黄金集](../baseline/p01-04-golden.json)、[数值参数历史源](../baseline/p01-04-numeric-profile.json)及[格式/性能/Windows验收方案](../baseline/P01-04-validation.md)。P01已按[批准记录](../baseline/p01-acceptance.json)采纳numeric-v1/performance-v1，历史候选/黄金元数据保留并映射；实施时读取同一黄金JSON，不复制期望。当前01按同一资产开展影子核对。

P02-02已实现[配置候选契约](../MIGRATION_CONTRACT.md#9-p02-02已实现的配置候选校验)与[18项配置回归](../../tests/test_price_configuration.py)。P06-01同时移植JSON数字原始token、旧格式显式单件名单、严格single/qty_only、重复/未知项整份拒绝、失败保留有效快照及固定line_kind；不能用浮点JSON解码重新引入精度丢失，也不能静默跳过坏配置。服务发布身份/协议仍以P05冻结版本为准，本段是01配置移植的核对依据。

P02-03已实现[草稿revision与输出门槛契约](../MIGRATION_CONTRACT.md#10-p02-03已实现的草稿状态与正式输出门槛)及[18项状态/输出回归](../../tests/test_quote_session.py)。P06-01同时对照输入/价格/来源变化失效、晚到计算丢弃、显式换价重算确认、三种正式输出零回调及同一整数分载荷；P05冻结协议后用稳定草稿身份/revision落实这些语义，不把Python进程内owner对象复制为IPC身份。当前01使用稳定draft_id和字符串revision落实这些语义。

目标：把已确认业务行为迁移至Rust，用独立核对证明正确性；此阶段不实施完整Tauri界面，也不迁移生产账本。

| ID | 实施与交付 | 可执行验收 | 恢复方式 |
| --- | --- | --- | --- |
| P06-01 | 锁定Rust工具链、依赖与许可证；领域crate实现十进制表达式、单位、行序折扣、金额/状态；共享JSON契约 | Python修正版与Rust对同一黄金样本行/总额/错误码精确一致；大整数跨JSON不丢精度；溢出/除零/负值规则符合契约；领域不依赖Tauri或UI | Rust影子运行，不承担真实写；任一差异保留旧核心并阻断替换 |
| P06-02 | 实现同一schema的存储、事务、幂等、revision、备份和schema迁移；替换服务领域适配，保持已确认协议 | 同request_id、并发改备注/作废、价格发布、迁移中断和重启恢复通过；旧Python客户端协议兼容；服务端角色过滤无退化 | 对副本试迁移；协议兼容开关只保留一个权威写端，不能双写两个账本 |
| P06-03 | Excel读取/生成候选库技术验证，选定适配；按字段映射、保留文本/精度与样式；导入错误可追溯 | 全部旧样本和新报表用独立读取器核对；中文/前导零/公式缓存/未知schema/大文件；未知格式拒写；不能把生成支持当无损编辑支持 | 若需要Python报表桥接，记录临时范围、依赖和退出门槛后再采用；不静默留下第二计算核心 |
| P06-04 | Rust接替Python服务的隔离演练；针对本次改动建立Windows CI构建/核心与合成格式检查；记录资源对比 | 黄金样本100%一致（已确认缺陷修正例按新值）；真实Windows客户端服务链路通过；性能与内存有可复现记录，不能只cargo build | 保留上一版服务及可读备份；恢复演练验证账本无丢失；不创建无关平台测试 |

退出门槛：所有跨语言差异已解释且符合确认规则，事务/权限/格式适配验证通过，未确认crate能力不作承诺。Rust并非必然减少SMB时间或安装包体积，按测量决定后续优化。源码、schema和协议变更记录清楚，进入P07还需对应授权。

P02-04补充输入资产：[窗口适配契约第11节](../MIGRATION_CONTRACT.md#11-p02-04已实现的窗口与输出适配)与[04辅助证据](../verification/P02-04-checks.json)。Rust复用业务核心/配置/状态样本，不迁移Tktrace实现；兼容新导出两位金额文本及扩展行类型normal/discount/order_total，无标签旧文件仍按P03的歧义政策处理。P02-04已按用户确认验收；当前P06-01复用其领域资产，窗口与报表Rust接入留后续。

04新增兼容目录字段screenshot_dir和相对共享配置根路径发布/解析，Rust配置样本须与Python共用语义；继承/不可修改属于应用角色投影，不能代替服务ACL。见[最新目录契约](../MIGRATION_CONTRACT.md#p02-04目录继承与关闭修复)；P02-04 Windows复查已验收；当前01保留目录文本语义，角色继承/ACL继续由服务与应用边界负责。

## P06-01当前交付与验证

领域crate位于`crates/quote-core`，固定Rust1.97.1与Cargo.lock；十进制采用BigInt系数/刻度，表达式每次除法精确HALF_UP至12位，普通行金额逐行结算整数分，折扣按已结算前序小计。全单错误无部分权威结果，中间值与每个小计均先检查容量。配置解析保留数字token、原UTF-8/BOM/CRLF及目录元数据，严格标志/重复/未知字段整份拒绝；失败刷新保留上个有效快照。

草稿输入/身份/价格/来源变化失效，迟到、跨草稿与同值变回结果丢弃；显式换价重算和revision确认。JSON金额/revision为字符串，稳定draft_id加私有请求generation绑定完成结果，既不是进程对象指针，也不是认证凭证。三种输出共用冻结载荷，dispatch再次检查门槛；被阻断不调用writer，writer错误保持上层可见。

[领域/运行契约](../verification/P06-01-core-contract.md)、[JSON契约](../verification/P06-01-protocol.json)、[精确依赖/许可](../verification/P06-01-dependencies.json)与根THIRD_PARTY_NOTICES完整交付。`quote-shadow`仅通过本地标准输入/输出验证；现有Python应用/服务/账本DDL和原黄金/报告不变，不承担真实写入。原服务角色过滤保持，领域结构包含成本不等于可直接发给销售。

检查入口：`py -3 tools/p06_core_check.py --windows-smoke --output reports/p06-01-windows-01`；辅助模式显式`--checks-only`。实际Windows AMD64/MSVC、固定工具链、fmt/Clippy/test/release构建与完整逐例比较通过后才登记Windows结果。当前Rust21项/Python58项与561/561逐例辅助核对（含原黄金53/53）通过，见[检查证据](../verification/P06-01-checks.json)，不能替代Windows验收；无需重跑P05已通过入口。

回退：关闭影子程序即可继续当前Python核心/服务；没有数据库/schema/客户端切换。任一跨语言差异阻断后续替换，不移动P06到old，不提前开始02。

## P06-01 Windows完整核对通过

用户本轮回传[原报告](../verification/P06-01-windows-report-01.json)29958字节和[原比较文件](../verification/P06-01-windows-comparisons-01.json)220370字节，均按原CRLF字节归档。[核对记录](../verification/P06-01-windows-evidence-01.json)确认ebf1a2c干净工作区的32项LF源码指纹与当前及辅助记录一致；实际Windows AMD64/MSVC、Rust1.97.1，fmt/Clippy/21项Rust测试/release构建全通过。58项Python测试清单、源码AST和成功日志逐项相同，零失败/错误/跳过。

561个有序case ID/请求SHA及Python参考结果独立重算，与上传Rust结果SHA全相同，原比较行还与辅助结果全相等；原报告的比较文件SHA匹配。含原黄金53/53、200有理数对照、数值/容量、配置原token/格式/失败保留以及17组草稿动作。全部15个外部依赖及本crate版本/许可证与锁定清单一致。

本轮验证纯领域与本地JSON影子，没有GUI、真实共享/E盘访问、已安装服务或生产写端切换。P06-01已具备收尾条件待用户验收；本阶段仍留now，02至04未启动，无需重跑已通过入口。原辅助与开发差异、P05原报告保持。


## P06-02当前交付

02从c8ad540按[启动记录](../verification/P06-02-start.json)复用本分支。`crates/quote-ledger`交付ledger-v1事务、原请求幂等、revision/价格CAS、完整性重算与原生在线备份；原DDL/hash不变，未知版本拒绝。私有进程适配替换已认证服务的计算/价格/真实财务写入；现有HTTPS/Auth/查询投影/输出渲染保留，Rust后端拒绝Python真实账本写连接。旧导入仅在内存预演，Rust固定表delta重验全账本后原子提交。明确离线后端选择持owner锁/管理员/完整维护备份，失败不隐式启用另一后端；v3主机包保存执行文件、许可与输出，独立恢复保持后端并维护，旧v1/v2兼容。

[完整契约与Windows入口](../verification/P06-02-storage-contract.md)、[私有JSON/兼容契约](../verification/P06-02-protocol.json)、[固定依赖/许可](../verification/P06-02-dependencies.json)及[检查证据](../verification/P06-02-checks.json)交付。65专项/594完整辅助、25 Rust测试/Clippy/release与同一561对照通过，原01报告不改；Windows首轮63通过/2处验证代码错误已修复；第二轮83指纹/65专项/25 Rust/561对照及临时主机原生DPAPI/HTTPS/恢复/ACL核对通过，具备收尾条件待用户验收，03/04未启动。没有真实主机或账本切换。格式Rust选型留03，完整Rust HTTP宿主与实机窗口演练留04。


## P06-02 Windows首轮验证代码修复

[原报告](../verification/P06-02-windows-report-01.json)与[原比较文件](../verification/P06-02-windows-comparisons-01.json)按原始字节保存。[独立核对](../verification/P06-02-windows-evidence-01.json)确认7338d7a的83项LF指纹、完整65个测试ID、25项Rust测试/构建、48个固定依赖及561项比较（逐项重算Python期望）匹配。Windows专项63通过、0断言失败、2错误；DPAPI/ACL/原生恢复额外检查尚未执行，不能登记整体验收通过。

错误分别是未知schema夹具保留SQLite连接导致WinError 32，以及模拟平台改变共享os.name导致Windows Path重建为PosixPath。前者用closing显式关闭原连接并保留事务与拒写/哈希检查，后者改为模拟platform.system，入口同时要求原生nt和Windows。[修复后65项辅助回归](../verification/P06-02-windows-fix-checks.json)全部通过；原594项完整辅助及原Rust/比较证据不改，本轮未重跑594项。继续同一分支，以[第二轮入口](../verification/P06-02-storage-contract.md#windows隔离检查)完成Windows复查；02不收尾，03/04未启动。


## P06-02 Windows第二轮完整核对通过

用户2026-10-13 23:00:02（Asia/Shanghai）回传[原报告](../verification/P06-02-windows-report-02.json)40217字节及[原比较文件](../verification/P06-02-windows-comparisons-02.json)220370字节，按原始字节归档。[独立核对](../verification/P06-02-windows-evidence-02.json)确认bf18f45干净工作区的83项LF源码指纹与当前源码、修复辅助证据一致；65个完整测试ID与源码加载器及成功日志逐项相同，零失败/错误/跳过，首轮两处错误均消失。实际Windows AMD64/MSVC Rust1.97.1的fmt/Clippy/25项Rust测试/release构建通过，48个外部包版本与许可及原服务4个固定依赖匹配。

561个有序case ID/请求SHA与Python参考结果逐项独立重算，全部等于上传Rust结果SHA，含原黄金53/53；比较文件原SHA匹配且解析结果等于01原辅助资产。Windows原生Rust提交后退出→DPAPI加密待核查→原request_id恢复回执、旧HTTPS客户端/销售成本过滤/前导零、v3新目录原生恢复账本与原回执及旧会话撤销均通过。库存独立核对为revision2、1单/1行、2回执/2审计，收入4000分/成本1600分/利润2400分；私有目录Hidden/System、保护DACL及明确SID名单通过，临时服务停止与清理正常。

本轮范围为Windows临时主机、原生Rust进程及HTTPS/DPAPI/备份恢复，没有GUI、已安装服务、真实E盘/共享路径或生产切换。02已具备收尾条件待用户验收，已通过检查无需重跑；首轮失败、修复辅助与原594项完整辅助证据保持。P06继续留now，03/04未启动。


## P06-02已收尾、P06-03当前交付

用户2026-10-13 23:07:55“收尾02开始03”按[02验收](../verification/P06-02-acceptance.json)收尾，原83指纹/65专项/25 Rust/561对照及Windows原生DPAPI/恢复/ACL材料不改，无需重跑。03按[启动记录](../verification/P06-03-start.json)复用唯一分支，P06继续留now。

[Excel契约与Windows入口](../verification/P06-03-excel-contract.md)、[私有格式契约](../verification/P06-03-protocol.json)、[候选验证](../verification/P06-03-candidates.json)、[74个外部依赖/许可](../verification/P06-03-dependencies.json)已交付。crates/quote-excel负责受限OOXML原始数字读取和新四表报表生成，财务仍由原Rust账本单写。正常旧源保持完整Plan/review SHA及原批次身份；数字精度有损明确复核并定位，公式缓存一律拒绝。旧v3财务版worker明确协商python-v1-compatibility格式桥接，不覆盖旧资源或切换财务写端；桥接范围/依赖/退出门槛记录至04。

[检查证据](../verification/P06-03-checks.json)记录165专项、626完整辅助、32项Rust/fmt/Clippy/release和同一561/561对照（原黄金53/53），当前98项LF指纹；最后工具/CLI变动另由7项验证及共同协议链路预演覆盖。真实从223e86e固定源离线编译旧执行文件，验证旧v3完整恢复/输出/账本保持。原辅助165报告及stdin运行器导致3项spawn失败的记录保留；改为有主入口保护的实文件运行器后626项全部通过，未改源测试来掩盖失败。

辅助真实HTTPS临时主机覆盖原生读取/导入重放、原客户端Excel/成本过滤/母版位置、独立读回/样式、未知提交原回执及v3新主机恢复；revision7，3单4明细1备注，有效金额11500/4600/6900分，原源hash/mtime与清理正常。辅助使用内存日志，不冒充Windows DPAPI/ACL。本轮Windows复查已通过，见下方核对记录；03具备收尾条件待用户验收。真实GUI/安装/共享/E盘与生产切换留后续，04未启动，已通过入口无需重跑。


## P06-03 Windows完整核对通过

用户2026-10-14 02:27:36（Asia/Shanghai）回传[原报告](../verification/P06-03-windows-report-01.json)80439字节及[原比较文件](../verification/P06-03-windows-comparisons-01.json)220370字节，按原始CRLF字节归档。[独立核对](../verification/P06-03-windows-evidence-01.json)确认fee8ea3干净工作区的98项LF指纹与提交blob、当前源码及最终辅助登记一致；165个完整测试ID与源码加载器、原辅助清单和成功日志逐项一致，零失败/错误/跳过。实际Windows AMD64/MSVC Rust1.97.1的fmt/Clippy/32项Rust测试/release构建通过，74个外部包版本/许可和原服务4个固定依赖匹配。

561个有序case ID、请求SHA及Python参考结果逐项独立重算，全部等于上传Rust结果SHA，含原黄金53/53；比较原SHA匹配且解析结果等于01原影子资产。旧v3兼容夹具从223e86e固定源按锁定依赖离线构建原财务执行文件成功，旧资源格式桥接及完整包恢复测试通过。

Windows临时主机覆盖Rust原生读取/导入重放/新报表、独立读取器全字段/前导零/文本/样式、原源hash/mtime不变、实际HTTPS客户端与母版位置/销售成本隔离、原生提交后退出→DPAPI加密待核查→原回执恢复、v3新主机账本/Excel文件/回执一致及旧会话撤销。库存独立核对为revision7、3单/4明细/1备注、2价格版本、1导入批次、7回执/7审计，有效金额11500/4600/6900分；Hidden/System、保护DACL及明确SID名单和清理通过。原生执行文件仅报告SHA，未随附件上传，不宣称已独立检查二进制。

本轮范围为Windows临时主机和原生进程/HTTPS/DPAPI/Excel/恢复，没有GUI、已安装服务、真实E盘/共享或生产切换。03具备收尾条件待用户验收，已通过检查无需重跑；原165/626辅助、开发运行器失败及02验收证据保持。P06继续留now，04/07/08未启动。


## P06-03已收尾、P06-04当前交付

用户2026-10-14 02:38:15“收尾03 开始04”按[03验收](../verification/P06-03-acceptance.json)收尾，原98指纹/165 Python/32 Rust/561对照和Windows原生Excel/DPAPI/HTTPS/v3恢复/ACL材料保持，无需重跑；04按[启动记录](../verification/P06-04-start.json)复用同一分支。

新增quote-host独立HTTPS程序直接链接三个既有Rust crate，移植兼容scrypt/会话/角色、增量查询/精确大整数、输出队列/原生PNG及完整v4备份恢复；host-v1可选宿主登记和原owner锁阻断双启动，明确离线选择持管理员/完整备份/库存与资源校验，可恢复原选择。原ledger/auth/output schema与业务/数值规则保持。成本报表所有重试回执在账户降级后也限制读取，保留Python读取边界同步修正。

[完整宿主契约与唯一Windows入口](../verification/P06-04-host-contract.md)、[协议](../verification/P06-04-protocol.json)、[178个外部包/许可](../verification/P06-04-dependencies.json)及[Windows-only CI](../../.github/workflows/p06-windows.yml)交付。[检查证据](../verification/P06-04-checks.json)记录127指纹、195专项/656完整辅助、42 Rust/561对照，无失败/错误/跳过；真实辅助Rust HTTPS/旧客户端/原生CJK图片/导入后v4恢复及200单资源通过。末次两处验证/IO委托变动另由30项原生/入口、42 Rust及共同协议核对覆盖，原完整报告保持。辅助临时字体不冒充Windows系统字体，DPAPI/ACL/GUI仍需实际Windows。

本项不安装服务、不访问真实共享/E盘或切换生产；原Python客户端/独立读取器/离线历史迁移工具保留，监听宿主无Python依赖。P06继续留now，04未验收，P07/P08未启动；只需回传本项新Windows报告，原通过入口无需重跑。
