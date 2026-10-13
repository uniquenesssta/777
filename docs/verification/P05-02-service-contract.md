# P05-02 认证服务、母子版客户端与部署契约

状态：已实现，[完整Windows核对](P05-02-windows-report-verification-01.json)60项源码指纹/42测试ID一致，42/42及原生联测通过，隔离证据已齐；真实部署待验证。唯一分支`stage/p05-data-service`，真实基线`84b881c`。用户“收尾01开始02”已登记[P05-01验收](P05-01-acceptance.json)。P04共享正式复验已获[即刻执行授权](P04-04-resume-06.json)，P05-03/04尚未实施。

## 交付与依赖选择

`quote_service`提供HTTPS业务边界，直接复用已验收`quote_core`和`quote_ledger`，不另写计算公式。过渡服务使用Uvicorn ASGI、标准库SQLite/ssl/hashlib和cryptography证书生成；没有FastAPI/ORM、共享数据库或第二套舍入逻辑。标准库http.server不作为局域网生产服务。新增依赖已按[requirements-service.txt](../../requirements-service.txt)固定：uvicorn0.50.0、h11 0.16.0、click8.5.0、cryptography50.0.1；当前辅助环境真实安装和测试这些版本。

服务单进程、单本机账本，Windows主机运行入口持有原生`service-owner`锁；同一主机目录第二实例拒绝，不按文件年龄夺锁。Uvicorn限制16个并发连接/任务，应用最多8个并行工作任务；I/O在工作线程，客户端窗口通过已验证Jobs队列交付。网络层只接受HTTPS，关闭代理头、WebSocket、访问日志和跨浏览器Origin调用；没有明文HTTP、自动跳转、代理或失败后共享文件fallback。

## 身份、会话与角色

初次管理员只由Windows主机本地`init`创建，密码通过不回显的getpass输入，不放进命令参数、配置或日志。管理员通过认证接口创建admin/sales账号、禁用/启用或重设密码；没有公共注册接口。账户ID是稳定UUID，客户淘宝ID/订单号/微信字段不当登录身份。保留至少一个启用的管理员。

密码12～128字符，存16字节随机salt和scrypt验证值（N32768/r8/p1/32字节输出、64MiB内存上限），不存明文。服务端生成32字节随机bearer令牌；数据库只存SHA256摘要、主体、账户epoch及到期时间，默认8小时。每个请求从持久账户记录恢复角色，不信客户端role/actor/owner字段。退出登录删除对应会话；改密码、角色或启用状态提升epoch并撤销该账户全部会话，服务重启不绕过到期/失效检查。失败登录每用户名/来源5次、每来源跨用户名20次后限制5分钟；错误不区分用户名存在性。

销售只能提交与查询本人订单、本人请求回执、本人订单追加备注；价格目录、计算、订单、明细、回执和汇总只按允许字段投影，不含成本、利润、原始价格JSON、其他订单归属或全局revision。管理员获得完整财务/价格管理、目录、账户和备份权限；销售即使直接调用后台接口也不能发布价格/目录、改账号/备份计划或作废订单。API没有物理删单/删文件入口。

## TLS信任与客户端持久化

主机生成P-256密钥和1年自签证书，SAN来自显式指定的IP/DNS；TLS最低1.2。客户端同时验证证书链、主机名和指定证书DER SHA256，凭证发送前完成握手与指纹核验。只分发`service-cert.pem`和客户端公开配置，禁止把`private`目录、TLS私钥或数据库给销售端。首次导入需与主机可信来源提供的指纹核对；换地址/证书不会静默绕过旧请求来源绑定。证书到期、主机地址变化或密钥轮换属于停写维护与重新分发信任的操作，后续安装/运维交接须记录，当前没有自动换证。

客户端公开配置`777-service-client-v1`只保存url、certificate、certificate_sha256、username；token和密码不落盘。本机连接用原CAS文件协议保存，坏配置保留原件。每客户端配置持有原生实例锁。金融操作在首次发送前持久保存UUID/request路径/原负载和subject/url/证书绑定，Windows用当前用户DPAPI加密；没有磁盘明文fallback。回复丢失、202或服务5xx不改写为未提交，保留原请求；先查回执，再按同一ID和原负载重试。新输入不替换待核查请求，换身份/服务拒绝重放。已确认的同一界面草稿再次点击不重复记账，修改输入并重算才视为新订单；不同合法请求不会按客户订单号或同秒时间合并。

## 业务协议v1

请求/响应JSON，重复字段、NaN、未知字段/版本、布尔替代数字表达式等拒绝。输入body最多1MiB，表达式原文字符串最长256，报价最多1000行；查询页1～200条。参数和高精度价格用字符串，结算分用十进制整数字符串；输入不携带客户端算好的财务总额。权威字段定义在[protocol.py](../../quote_service/protocol.py)，HTTP入口在[app.py](../../quote_service/app.py)。

| 方法/路径 | 角色 | 行为 |
| --- | --- | --- |
| POST /v1/login、/v1/logout；GET /v1/me | 登录/当前主体 | username/password换会话；注销；返回主体/角色/协议 |
| GET /v1/prices | admin/sales | 当前发布版本；销售items只有product_id/sale/k/single |
| POST /v1/prices | admin | request_id、prices、expected_price_version_id；完整校验与价格CAS |
| POST /v1/calculate | admin/sales | snapshot；绑定当前版本，核心重算，按角色投影 |
| POST /v1/orders | admin/sales | request_id、snapshot、details；重验版本、原子整单/回执/审计 |
| GET /v1/orders | admin/本人 | offset/limit/state；本人范围金额和页数，销售无他人统计 |
| GET /v1/orders/{UUID} | admin/本人 | 冻结输入/逐行金额及追加备注历史 |
| POST /v1/notes | admin/本人 | request_id/order_id/body/expected_revision，只追加 |
| POST /v1/state | admin | request_id/order_id/state/reason/expected_revision，作废/恢复不改原金额 |
| GET /v1/requests/{UUID} | admin/本人 | 已提交原回执或null，禁止读别人回执 |
| GET/POST /v1/settings | 读所有登录主体；写admin | 输出目录及revision CAS；Windows发布UNC，子版不能改 |
| GET/POST /v1/accounts；POST /v1/accounts/{UUID} | admin | 创建/列出/禁用/重设密码/角色管理，不返回密码验证值或token |
| GET/POST /v1/backup；POST /v1/backup-plan | admin | 主机目标、财务快照和完整服务状态、维护备份、计划CAS |

snapshot为price_version_id、lines及可选business-v1/numeric-v1版本。normal行含line_kind/product_id/q及可选h/w/name；discount行含line_kind/percent及可选name。details沿用既有DraftDetails的`customer/order_ref/wechat`，不是账户身份。401未认证、403拒绝、404不存在或不可见、409版本/幂等冲突、422格式/业务无效、503不可用；未知提交202带原request_id。错误没有原始凭证、私有路径或财务内容。

## 母子版窗口与目录

[run_quote_client.py](../../tools/run_quote_client.py)是显式服务入口，复用原母/子版Tk布局并优先挂接[服务适配](../../quote_app/service_client.py)。启动没有旧E盘/UNC价格探测，没有成本配置读取或裸写/删Excel；销售没有真实成本缓存。隐藏的旧控件兼容需要的零值不是服务成本价格。计算在服务端；母版编辑价格须发布再计算，价格更新需查看差异/重算/确认，提交再校验当前版本。

原计算页导出按钮在服务入口改为“提交订单”；服务账本页查询订单/明细、追加备注，管理端作废/恢复。目录由母版通过服务发布，子版只读并每30秒观察新值；管理端未保存的目录草稿不被观察覆盖，过期revision保存拒绝。账户管理与主机备份状态/计划/维护备份在母版服务页。提交后的Excel报表/附件任务在P05-04；服务入口当前不生成报表/截图，原入口在切换前保留，不能把两条链同时当权威账本。旧历史导入在03，未迁移或切换生产数据。

## 主机数据、备份与恢复

`init`要求绝对本机固定磁盘的独立新主机/备份目录，不采用旧目录、不改旧账本。主机`private`下保存ledger.sqlite3、auth.sqlite3、TLS私钥/证书和service.json，采用当前Windows执行身份/SYSTEM/管理员的受保护DACL及Hidden+System；备份根同样保护。可见目录配置没有固定E盘fallback，下面E盘名称是部署示例。服务在主机当前Windows账户运行，不自动创建Windows系统服务、修改防火墙或安装到真实机器。

备份计划持久化：默认有变更30分钟滚动、UTC+8每日02:00、48滚动/30日及维护备份保留；主机15秒检查到期，由唯一进程执行。目录不可用不另建权威库，已成交不撤销；主机本地auth库保存最近完整成功与失败状态，即使备份盘不可用管理员仍可查看。目标被替换为其他备份store_id时拒绝。

原ledger-v1一致快照和独立恢复保持。服务额外在`service-bundles`创建完整包：财务快照、Auth账号/设置/计划、TLS材料及主机配置，每文件SHA256、schema/金额/行数与全部actor映射核对；实际独立恢复后才标`full_service_verified=true`和服务健康成功。财务快照成功不自动等于完整服务成功；`service_health.last_success`为完整服务成功记录。包清理仅限单独登记且通过验证的、已按财务保留策略退休的包；未知文件不删除。

`restore`只能创建独立新主机目录，保留账户ID、财务/备注/回执与证书身份，清空旧会话，所有旧凭证失效；指定已有管理员设置新密码，其他账户需重设密码并启用。恢复配置默认maintenance=true，run拒绝，避免无声启动第二个权威写端。正式切换必须停旧写端、维护备份和新旧增量对账，再显式activate-restored确认旧主机已停；当前代码未执行生产恢复或切换。

## Windows隔离验证（首次已通过，无需重跑）

[42专项/427完整辅助证据](P05-02-checks.json)通过真实本机TCP HTTPS/SQLite、认证失效、越权与字段过滤、未知回执和双连接同请求、完整恢复及账户ID/会话处理；主线程控制器用替代控件检查，不冒充真实Tk。此前辅助运行没有Windows显示/DPAPI；现已收到[完整Windows报告](P05-02-windows-report-01.json)并[核对60指纹/42测试ID](P05-02-windows-report-verification-01.json)，42/42、实际TLS1.3、DPAPI、母子Tk、恢复/权限/关闭/清理通过。以下为已执行入口，不要求重跑。

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 -m pip install -r requirements-service.txt
if ($LASTEXITCODE -ne 0) { throw '服务依赖安装失败，先停止' }
py -3 tools/p05_service_check.py --windows-smoke --output reports/p05-02-windows-01
```

预计约1～3分钟。报告保存42项检查与60项源码指纹；原生环回HTTPS、DPAPI待核查请求、实际母子Tk登录/计算/提交/查询/只读目录、关闭/清理及完整备份/独立恢复。临时主机/账户自动清理，不访问真实E盘、共享数据或192.168.4.38。原`reports/p05-02-windows-01/report.json`已以report(10).json回传并按字节归档（22811字节）；源码指纹/测试清单/零跳过及日志核对通过，不要求重跑。返回账本3单5明细、revision4、收入/成本/利润11200/4800/6400分与隔离样例一致；两窗口依次运行，不是物理双机部署。共享Get-Item元数据另见[观察记录](P04-04-shared-directory-observation-01.json)，P04正式性能复验仍保留。

## 真实主机部署入口（尚未执行）

先在192.168.4.38确认实际Windows系统、长期运行账户和本机目录权限；下列是可审阅的示例，当前不要求先部署或给生产客户端切换。root/backup-dir可显式换到其他本机固定磁盘新目录，旧数据保持。需要局域网放行8477时由主机管理员按本机防火墙策略处理，不默认关闭防火墙。

```powershell
py -3 tools/quote_service_host.py init --root 'E:\Quote777Service' --backup-dir 'E:\Quote777Backups' --host '192.168.4.38' --host 'localhost' --host '127.0.0.1' --bind '0.0.0.0' --port 8477 --admin manager
py -3 tools/quote_service_host.py run --root 'E:\Quote777Service'
```

客户端复制公开service-cert.pem，运行`py -3 tools/run_quote_client.py --role manager`或`--role sales`；在服务页设置https://192.168.4.38:8477、选择公开证书并核对指纹后登录。主机先发布价格/创建各操作人员账号，母版发布UNC报表/图片目录，子版自动继承。生产账本导入、安装自启动和切换按03/P07/P08执行；真实主机/E盘账户访问、不同物理机器并发部署验收仍待现场证据。

技术依据：[Uvicorn设置](https://www.uvicorn.org/settings/)、[部署](https://www.uvicorn.org/deployment/)、[Python3.12 ssl](https://docs.python.org/3.12/library/ssl.html)、[hashlib scrypt](https://docs.python.org/3.12/library/hashlib.html)、[cryptography X.509](https://cryptography.io/en/stable/x509/tutorial/)、[Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。
