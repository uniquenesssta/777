# P06 Rust领域核心与存储/服务适配

状态：执行中。用户2026-10-13 20:25:31（Asia/Shanghai）“收尾P05-04开始P06-01”授权，从P05收尾77101320deda2f624a215ade67c8ea5306d1c0a4建立唯一stage/p06-rust-core。[P05范围交接](../verification/P05-acceptance.json)保留真实部署/历史切换待办。P06-01已实现待Windows验证/用户验收；02至04未启动。

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
