# P06-04 独立 Rust HTTPS 宿主

用户2026-10-14 02:38:15（Asia/Shanghai）“收尾03 开始04”，按[03验收](P06-03-acceptance.json)接续[04启动](P06-04-start.json)，复用唯一stage/p06-rust-core，从89f7138执行。03原Windows/辅助/比较资料保持，不重跑已通过入口；P07/P08未启动。

当前核对：[Windows本机原报告与证据](P06-04-windows-evidence-01.json)已通过，同提交Windows CI成功；212专项/43 Rust/561对照及原母子GUI、DPAPI/ACL、系统CJK图片、v4恢复和资源资料完整。已按用户“收尾04”[验收](P06-04-acceptance.json)，[P06阶段](P06-acceptance.json)全部收尾；无需重跑下方入口，此前失败段落保留为历史，P07/P08未启动。

## 接替范围

新增crates/quote-host与quote-host.exe。它直接链接quote-core、quote-ledger、quote-excel，承担HTTPS、兼容账户/会话、业务授权、查询、输出队列/PNG及完整备份恢复；监听期间不启动Python/ASGI或财务worker子进程。初始化/明确离线资源选择会只读探测保留的旧工具worker，运行服务不依赖该子进程。

| 边界 | 本轮实现与保留 |
| --- | --- |
| API与金额 | 777-service/query/output-v1保持；角色从当前已认证会话恢复，客户端不能提供权威金额/价格/actor；金额和大整数总额仍是十进制字符串 |
| 账本 | 原ledger-v1 DDL、身份、请求指纹/原回执、单写事务/revision/价格CAS保持；未知库拒绝，不新建第二账本 |
| 鉴权 | 原auth-v1和scrypt N32768/r8/p1/32字节兼容；token只存SHA，8小时会话、epoch撤销、最后管理员及原限流保持 |
| 查询 | 有界页/原签名游标语义、账户/角色/筛选/limit与版本绑定、字面Unicode15全文casefold、审计增量和32份摘要LRU；复用核心Unicode数字映射保留查询整数语义 |
| 输出 | 原output-store-v1和冻结payload/回执；母版目录继承、销售成本隔离；慢文件IO不持服务派发锁；重试/崩溃不重新成交 |
| 旧工具 | Python原客户端、独立读取器、历史源字段/日期/来源复核保留为验证和离线迁移工具；其apply仍持同一owner锁；运行Rust宿主没有Python格式回调 |

业务/数值规则不变，核心只公开已有Unicode15数字映射供查询复用，没有另一份计算实现。完整依赖、锁定checksum/许可和原通知见[178包登记](P06-04-dependencies.json)及[完整许可](../../THIRD_PARTY_NOTICES.md)；4个本地crate依赖单向，未引入Tauri/UI依赖。

## 网络、目录和图片

仅TLS1.2/1.3与HTTP1.1，不开明文或浏览器CORS入口，不信任代理身份。TLS前至HTTP结束持连接额度16，业务派发8；JSON1MiB、头部缓冲32KiB、握手/请求头/正文10秒门槛，重复敏感头/JSON键及坏Unicode拒绝。HTTP库使用明确计时器和非阻塞监听套接字，停止后等待真实输出工作结束再释放owner。

Excel继续原生新四表、完整文本/整数分/前导零/字面公式及样式，独立读取器核对；不编辑历史源。PNG由fontdue/png原生生成，保留1200宽、40字符换行、原payload/job/format元数据。实际Windows引用msyh.ttc/simhei.ttf，不分发系统字体；缺字体/字形明确失败，订单与回执保持。CI显式用固定SHA的OFL Noto临时字体，不安装系统字体、不修改WINDIR，不替代本机系统字体/GUI验收。

输出使用临时文件刷盘及排他原子发布。Rust的fs::rename也会在Windows覆盖目标，因此最终新文件使用MoveFileEx WRITE_THROUGH且不启用REPLACE_EXISTING；异内容/重解析目标保留并拒绝。同一成本任务的重试回执在账户降级后也不可读取，Rust与保留的Python读取边界一致。

私有目录/备份仍在明确本机固定磁盘，Windows设置并读回Hidden/System、保护DACL和当前身份/SYSTEM/Administrators的精确继承名单。母版发布的导出/图片位置要求UNC，子版只读继承；验证时直接注入自有临时目录作为夹具，不冒充真实共享路径验收。

## 宿主选择、备份与恢复

host-v1增加可选service_backend/rust_host_sha256，旧配置默认Python。受登记的rust-service-host.exe和rust-host-notices.txt与原worker/许可保持独立。明确select-host持原.service-owner.777.lock、鉴权管理员、完整维护备份及库存/资源校验；已登记不同版本需要--upgrade-resources，不自动覆盖未知文件；失败恢复原资源/配置。旧Python入口按已选宿主执行原生程序，直接启动Python监听或业务派发到已选Rust主机被拒绝，无隐式回退。

新完整包为777-service-bundle-v4，保留账本/auth/输出/TLS/worker/许可及冻结blob，再携带宿主资源。原v1/v2/v3仍可独立核对/恢复；不改旧包。恢复只写新目录，保留账本/订单/原回执/TLS身份，删除旧会话、重置指定管理员密码、禁用其他旧账户并默认维护。显式activate-restored要求确认旧主机已停写；隔离复验也先停止原实例再激活副本。旧资源保留至明确升级，恢复不会偷偷选取当前开发程序。

Rust完整备份使用原生SQLite快照、财务/账户/输出/文件清单及独立新目录恢复核对；不依赖Python来源复核。Python仍作为独立验证读取器和历史离线工具，不承担运行宿主的财务写入。原库存、源件hash/mtime、未知提交原request_id恢复及角色过滤进入本项共同验证链。

## Windows本机入口

当前阶段分支运行一个新入口，原01/02/03/P05通过入口无需重跑：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 tools/p06_host_check.py --windows-smoke --output reports/p06-04-windows-04
```

沿用现有Python/固定服务验证依赖和Rust1.97.1/MSVC，Cargo按锁定文件获取本轮新增包。入口执行fmt/Clippy/Rust测试/release、完整专项与同一561例；以真实Rust临时主机复用原母/子Tk窗口，覆盖登录/清空密码/36元计算/提交/查询/成本过滤/关闭，并验证真实宿主退出、DPAPI原回执、离线合成历史导入、原生Excel/系统CJK PNG、v4恢复后维护/撤会话/旧客户端再连。返回report.json和comparisons.json；输出目录不得覆盖，后续按新编号复查。

不安装服务、不访问真实E盘/共享路径、不切换生产或实施Tauri界面。本项Windows结果及用户验收完成后才收尾P06并进入P07。

## CI与资源对比

[Windows-only CI](../../.github/workflows/p06-windows.yml)固定官方action提交、Rust1.97.1/Python3.12.10和现有验证依赖，只在本阶段分支执行构建/核心/合成格式/实际HTTPS/DPAPI/ACL/原生恢复；不启动GUI、操作真实数据或字体安装。CI字体由[校验下载入口](../../tools/p06_ci_fonts.py)存临时目录并明确来源。CI通过也不代表本机GUI/系统字体/安装验收。

[资源入口](../../tools/p06_resources.py)在两份独立临时主机使用同价目和200单，分别运行保留的Python HTTPS＋Rust worker架构与Rust直接宿主。每端5次计算及3次查询预热，30次计算/20条分页测量，记录每次延迟、median/p95/max及10ms采样主进程resident/private峰值。短命worker/客户端不计入这项主进程内存；二进制字节不是安装包/全部运行库体积。结果用于评估已测路径，不推断真实SMB或所有图片规模更快/更省；P07安装体积另测。

[检查证据](P06-04-checks.json)已归档127指纹、195专项/656完整辅助、42 Rust/561对照、原生HTTPS/Excel/临时CJK PNG/历史导入后v4恢复及资源测量。初期启动/测试夹具及辅助PID采样错误按原日志保留，末次验证/IO委托变动由30项原生/入口、42 Rust和共同协议另行覆盖；未重复656项。实际Windows与用户验收仍待回传；下方记录后续CI失败和修复，不将原辅助通过视作Windows通过。

辅助200单的计算p95由约13.4ms降至5.2ms，采样主进程resident约30.6MB/21.5MB；查询p95约5.8ms/44.8ms，Rust端仍有较高尾延迟。原样保留[测量](P06-04-resources-final-01.json)，不宣称全部性能改善；本机Windows结果用于判断后续查询尾延迟优化。


首次Windows CI已实际执行并在Windows专用目录分支的Clippy needless_return处失败，fmt通过，其余门槛未进入。[原报告及修复核对](P06-04-ci-evidence-01.json)保留127项源码匹配与失败事实；末句改为等价尾表达式，辅助fmt/Clippy通过，严格门槛未改。推送后由同一CI重跑；当前CI结果及本机Windows验收仍待核对，不把旧辅助通过视为新Windows通过。


第二次Windows CI已通过上述Clippy修复、42 Rust/release及561对照，但专项因权限读回和缺固定历史对象而失败；见[原报告及修复](P06-04-ci-evidence-02.json)。两个宿主适配器现在从同一原生描述符的ACE读取完整SID作为授权核对依据，SDDL中的机器相对显示缩写不再用于猜测身份；精确主体、数量、去重、全控制、保护DACL及OI/CI要求保持。CI仅补fetch固定223e86e对象，仍真实离线构建旧工具验证v3兼容。

修复具备16项Python/43项Rust及浅克隆归档辅助证据；权限回归已加入同一入口，128项指纹和207项载入测试由新Windows CI执行，尚不宣称新Windows通过。第一、二次原报告及旧辅助材料保持。本机新输出目录改为windows-03以保留已有结果；实际GUI/系统字体验收与CI分开，P06-04待验收。


第三次CI通过权限初始化、固定旧工具构建、43 Rust及561对照，207专项中205项成功；两项故障退出测试因验证清理代码写已关闭管道报EINVAL（含tearDown共3错误），协议smoke/资源未执行。见[原报告与修复](P06-04-ci-evidence-03.json)。夹具与资源入口采用communicate统一关闭管道并保留退出码/超时门槛；11专项及协议恢复/双宿主小规模清理辅助通过，当前128指纹/212测试由新Windows CI复查。上述本机入口使用新windows-04目录；Windows本机与用户验收仍待完成。


第四次CI的原管道错误已消失，两项原生崩溃恢复均通过；212项中211成功，新增生命周期方法的两个子项因提示行CRLF/LF断言失败。[原报告与修复](P06-04-ci-evidence-04.json)保留。断言现支持精确LF/CRLF提示，真实子进程显式覆盖两种换行及17/18退出码；旧断言可复现失败、修复后5项辅助通过。仅测试变化，新Windows CI及上述本机入口仍待完成；保留windows-04输出目录建议。
