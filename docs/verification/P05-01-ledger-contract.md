# P05-01 本地主机结构化账本与备份契约

状态：首次Windows隔离检查失败，已修复备份DACL与测试连接关闭，待第二次复验，尚未用户验收。唯一分支`stage/p05-data-service`，基线`31c8784`；用户确认停电并授权先P05的[依赖例外](P04-04-deferral.json)保留P04共享复验，不伪造整阶段通过。

实现：`quote_ledger`＋Python标准库sqlite3，要求Python3.12和SQLite≥3.37。复用已有business-v1/numeric-v1及53例黄金集，不另算财务公式。全程只在显式本机普通路径创建新库，拒绝UNC/映射盘/链接/重解析、现有文件及占用的WAL/SHM；已有库以schema_version、application_id和实际schema指纹核对，不自动修复/覆盖未知或不兼容库。现有窗口、价格/Excel写链未切换，没有服务或生产数据库部署。

## schema与跨语言表示

[实际DDL](P05-01-schema.sql)由运行时DDL生成，仅作结构说明，不是自动迁移脚本；权威定义在[quote_ledger/schema.py](../../quote_ledger/schema.py)。schema_version=1、application_id=0x3737374C、SQLite STRICT类型、外键与索引。schema_hash将sqlite_master中非sqlite内部对象按type/name排序，取type/name/tbl_name/sql四列数组，紧凑UTF-8 JSON序列化后SHA256；不使用Python repr，Rust可重现。Rust执行与兼容检查尚未实施。

| 实体 | 持久化与约束 |
| --- | --- |
| Order | owner/price/rule/numeric版本、输入/身份快照、整数分收入/成本/利润、active/void、revision、request_id；不可改金额/快照/归属，不物理删 |
| Line | UUID、order/sequence唯一、normal/discount、原输入JSON、规范十进制参数、该行价快照、整数分金额/折前小计；不更新/删除 |
| Note | 原文、作者、order/request、时间；只追加，订单revision冲突拒绝 |
| PriceVersion | 全份校验的商品JSON、内容哈希、rule/numeric版本、发布主体/时间；不可改；当前价格指针外键与发布CAS |
| ImportBatch | source_sha256/adapter_version唯一、格式、staged/committed/rejected、逐行映射JSON与报告；实际导入在P05-03 |
| AuditEvent | 每个成功请求一条不可变事件；actor/operation/order/before/after；包含状态操作原因 |
| Request | request_id唯一、actor/operation/规范负载指纹、原回执、全局revision；不可改；同键不同主体/负载冲突 |
| LedgerMeta | 唯一ledger_id、schema版本/哈希、全局revision和当前价格版本；外键禁止无效价格指针 |

金额SQL INTEGER分，检查利润=收入－成本且差额不是浮点；容量沿用核心i64约束。JSON回执的分用字符串避免JS精度丢失。q/h/w/sale/cost/k/percent保留原文与核心规范十进制字符串；恢复核对会重新调用同一核心对照每单/每行、规则与价格快照。汇总在Python整数中累加，避免SQLite SUM溢出。未增加额外舍入规则。

## 事务和内部接口

存储侧`Principal(subject,role)`是可信服务传入的内部主体，不是认证证据，**禁止接收客户端自报role直接构造它**。网络认证、主体注册/失效、TLS与销售DTO字段过滤在P05-02实现；当前存储内部回执可含成本，不能直接当销售响应。

| 内部操作 | 边界与结果 |
| --- | --- |
| publish_prices | admin；整份价格经现有配置校验；expected_price_version_id CAS，初次为None，旧管理员视图拒绝；版本ID不可重用 |
| submit_order | 输入仅QuoteSnapshot/DraftDetails；当前账本发布价重算，未知/旧版本与任何无效行阻断整单；原冻结价、顺序折扣/整数分完整入库 |
| append_note | 本人订单或admin；expected_revision、非空原文；追加一次并更新订单revision |
| set_state | admin、expected_revision和非空原因；作废/恢复只变状态/revision并审计，历史明细金额保持 |
| query_request | 本人请求或admin；查原回执，未知ID为None；不能通过请求ID读到别人的结果 |

手动`BEGIN IMMEDIATE`＋WAL＋synchronous=FULL；先查请求回执，再在一个事务内写完整订单/明细、回执、审计与revision。读写连接各自所属线程且及时关闭，SQLite忙锁显式失败，不自动重复业务请求。失败回滚不留半单；COMMIT阶段或已提交后回复异常抛UnknownCommit，保留request_id供查询，原回执在重复请求时恢复。重复原单在价格更新后仍重放原结果，不再校验为新成交。业务状态不等于传输成功；绝不把发送失败改写为订单未提交。

## 一致性备份与独立恢复

`Backups`是服务侧适配；不创建系统服务、不启动常驻计时器。`run_due`按时区明确的时间和可调参数提供30分钟有变更滚动／每日02:00日备份入口，`retain`默认48滚动／30日，维护备份及最后成功包不删除；这些频率/数量仍为建议。真实服务身份、配置持久化/管理员界面在02/P07绑定。

备份目录必须新建且专属，不能采用任意已有目录。Windows设置Hidden+System，用SetNamedSecurityInfoW及DACL|PROTECTED_DACL标志一次替换完整DACL，精确授予当前执行身份、SYSTEM和内置管理员完全控制及OI/CI继承，随后独立读取原生安全描述符/属性核验。允许标准SID别名和等价完全控制掩码，额外/重复主体、缺失主体、继承/仅继承ACE、拒绝条目或其他权限均拒绝；只调用GetSystemDirectoryW确认的系统whoami，不经shell，DACL写入不再使用icacls组合命令。隐藏属性不代替ACL；当前账户的隔离检查不证明真实主机服务身份或真实E盘显示效果已验收。非Windows仅显式辅助模式，不能登记Windows保护通过。

单一备份/计划入口用既有原生持久锁，不能按锁文件年龄夺锁或删除锁文件。使用sqlite3.Connection.backup一致性快照，生成唯一backup_id包，检查完整性、外键、价格/规则/订单逐行金额、回执/审计/revision及行数。包有版本、哈希、核对清单；在独立新文件恢复并再次核对后才记成功。失败保留最近成功包与错误状态，不撤销已提交订单；未列入成功清单的失败包保留供审阅，不当成功备份。附件字段目前为空，因为附件实体/复制尚在P05-04。

恢复只能写入不存在的独立普通文件及干净附属文件位置，校验备份哈希与清单，不覆盖线上账本。运行中不能单独复制主db作为一致快照。过期清理只处理清单中本应用包，先校验候选的ID、内容哈希与完整文件集合；未知目录/文件与维护备份保持。生产恢复和schema升级必须先停写、维护备份及新旧增量对账；本轮只有初始v1，不提供跨未知版本自动迁移。

## 验证证据和剩余门槛

[31专项/374项完整辅助证据](P05-01-checks.json)记录真实本机合成SQLite：同请求两连接只有一单、锁失败无半单、第二条明细失败整单回滚、真实子进程在提交前退出后恢复、已提交回复丢失查询/重放、价格CAS/冻结与备注revision、作废恢复对账、实际并发未提交写入时的一致性备份、独立恢复、坏包/坏库/过期清理/计划锁、全部53黄金入库或拒绝与原资料保护。辅助环境不是目标Windows/真实E盘或真实多客户端服务。[首次Windows报告](P05-01-windows-report-01.json)中31项21通过/10错误，19项源码和测试清单均匹配94f4d89；[核对与修复记录](P05-01-windows-evidence-01.json)保留具体边界。9处备份DACL组合门禁失败，实际SDDL未采集，不能区分保护位和主体数；另1处文件SQLite连接未显式关闭导致WinError32。修复后[40专项/383完整辅助](P05-01-security-fix-checks.json)通过；新增7项精确权限/Win32调用边界及2项控制台失败证据检查，模拟调用不当原生权限证据。Windows入口现运行40项及原生属性/DACL、账本与恢复联测；另外在新建临时目录预置Everyone完全控制，再用实际原生API移除并读回核验。真实认证客户端在P05-02。

P04整阶段尚未验收；用户确认停电原因并授权开发先行，明日共享复验保留为2026-10-14待办。不要把本地SQLite通过当P04共享性能通过，或自动开启生产切换。

## Windows执行入口

当前已在stage/p05-data-service，拉取修复即可。检查只创建临时本机目录及新的reports输出；真实E盘/共享目录不触碰。首次报告保留，使用新输出目录，不覆盖或删除旧报告。

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 tools/p05_ledger_check.py --windows-smoke --output reports/p05-01-windows-02
```

预计约1～3分钟，完成后回传`reports/p05-01-windows-02/report.json`。控制台会显示检查数量、失败测试摘要或原生异常与报告位置；报告保留完整检查日志和原生异常链。核对20项LF源码指纹、40个测试ID、原生属性/DACL（包含额外授权移除）、事务/恢复及清理后再决定01收尾；本阶段留now，02/03/04未实施。

技术依据（实施时复核）：[Python3.12 sqlite3](https://docs.python.org/3.12/library/sqlite3.html)、[SQLite事务](https://www.sqlite.org/lang_transaction.html)、[SQLite在线备份](https://www.sqlite.org/backup.html)、[网络文件数据库限制](https://www.sqlite.org/useovernet.html)、[Microsoft安全描述符](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow)、[SDDL](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-string-format)、[SetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow)、[SDDL转换](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw)、[读取DACL](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getsecuritydescriptordacl)。
