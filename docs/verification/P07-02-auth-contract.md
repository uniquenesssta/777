# P07-02 自动连接与设备授权

依据：[当前任务书](../now/P07-tauri-desktop.md)、[交付契约6.4](../MIGRATION_CONTRACT.md#64-已确认的开发版与母子版交付方式待实现)。用户2026-10-14 23:39收尾01并启动02，唯一分支仍为`stage/p07-tauri-desktop`，基线1043853。[01验收](P07-01-acceptance.json)保留原Windows证据；新增认证不追认为01已测。

## 固定开发入口

按用户2026-10-15要求，桌面开发页固定为`http://127.0.0.1:29346`。Tauri devUrl、Vite、开发启动器及浏览器测试/CORS使用同一端口。Rust服务首次编译完成后才启动开发页，编译期间出现Waiting for your frontend dev server属于启动等待。

`npm --prefix desktop run tauri dev`自动准备并运行本机Rust HTTPS开发服务，再启动Vite和Tauri。服务固定为`https://127.0.0.1:18477`，账号`admin`、密码`123456`，桌面端原生层自动读取并登录，无需复制地址/PEM/pin。首次单任务增量构建host/ledger；之后复用缓存。已有Node 22.12+与P07工具链即可，不变更依赖版本。

Windows开发状态固定在`%LOCALAPPDATA%\Quote777Development`，不随仓库盘符/工作目录变化，不把SQLite放在共享盘；辅助环境使用忽略目录`reports/p07-development`。其中`777-development.json`标识开发根，host保存证书/私钥和合成账本，desktop保存本机开发bootstrap。每次复用同一证书/端口/数据，首次发布三项演示价格，之后不覆盖自己修改的价格。服务程序随代码更新时走既有owner锁/维护备份/资源校验再切换，不重新生成证书或清空开发账本。只绑定127.0.0.1；拒绝未知目录、重解析路径、端口占用及与标记不符的主机配置。终止开发服务不删除开发数据。不要把整个开发profile导出为正式部署配置。

短密码只在已标记开发库首次初始化时设置，普通主机初始化、创建/修改正式账号仍保留原12～128字密码策略。维护CLI验证既有密码不再套用新密码创建限制，仍须通过原账户verifier；创建/恢复设置新密码继续严格校验。正式母子模式不读取这份开发目录或使用该密码；真实主机没有被修改。开发服务仍执行TLS pin和服务端角色过滤。

开发模式在“存储与备份 → 开发连接设置”保留显式连接能力，可切换到获授权的其他服务用于调试；人工常规启动已走自动连接。原01自动检查仍创建随机账号/临时服务，不因为开发便利改写历史样本或降低生产认证。

## 原生产品与会话边界

- Rust构建特性`manager`和`sales`互斥，类型由本机编译决定，不接受JS/localStorage/环境变量指定。普通release缺失类型拒绝编译；`verification`仅允许隔离验证，正式包排除此特性。Windows安装产物和前端开发页从正式包剔除仍由P07-04交付，本项不冒充安装包验收。
- 原生profile为AppLocalData固定manager/sales子目录；常规debug开发入口使用上述本机开发profile。隔离验证仍仅接受标记的系统临时目录，原生API端口/UDF机制保持。
- 类型化IPC新增`bootstrap`，返回delivery和已过滤的session显示信息，不返回登记材料、凭证、token。正式类型直接invoke `connect`也拒绝；无凭证时只有连接/待维护状态与重试，没有技术配置或账号密码页。母版业务目录/备份设置保留，子版只读继承。
- 部署人员提供固定profile中的`bootstrap.json`，严格字段为schema=`777-desktop-bootstrap-v1`、delivery、connection和一次性ticket；正式配置拒绝username/password。已登记后以Windows DPAPI保存device.bin，发送登记请求前先独占持久化独立device_id/随机secret，成功后删除明文bootstrap。相同登记响应丢失后可按同一device_id/secret安全重试，不生成第二个设备。部署人员提供新的登记文件时仅替换设备凭证，不删除pending；跨身份/服务的旧未知请求仍拒绝重放。
- 凭证绑定原profile/服务/类型，复制到另一profile拒绝；DPAPI是Windows用户保护，不是硬件不可克隆证明。存储层检查所有祖先重解析点，在创建profile前拒绝junction越界；损坏pending明确失败，不误报“没有待核查”。
- 原生层在会话临近到期时自动续取；服务拒绝身份时进入待维护/重连状态，不显示技术登录。写请求不因认证错误盲目重发，未知提交继续保留原服务/主体/request_id，经自动恢复会话后先核查原回执。草稿及原待核查记录不因撤销授权删除。

## 服务设备协议与兼容

旧`777-service-v1`账号、8小时会话、ledger-v1和金额规则不改，新增可选`777-device-auth-v1`。离线维护命令`quote-host enable-devices --root <host> --admin <账号>`验证管理员、取得owner锁并启用；密码不放命令行。既有主机不自动启用，不会因本项开发去触碰真实主机。部署前应完成发布价格。

启用后service.json增加`device_auth`标记，要求完整有效devices.sqlite3；文件丢失/坏schema不自动重建。身份数据在独立sidecar，原auth-v1及其DDL未修改。每次认证检查原users的enabled/epoch/role，订单仍绑定原actor_id；同一人员多设备可明确绑定同一主体，其他主体订单不可读。更换包类型不授予权限；撤销单设备实时使其已发会话无效，其他设备保留。

| 接口 | 条件及结果 |
| --- | --- |
| POST /v1/device-grants | 认证管理员；指定既有subject/delivery/ttl_seconds，服务核对主体角色；一次性限30～3600秒材料，仅返回此时的ticket |
| POST /v1/device/enroll | ticket/device_id/device_secret/delivery；事务消费，只允许同设备和同secret重放，过期/跨设备/伪造字段/错类型拒绝 |
| POST /v1/device/session | 独立设备凭证换短期内存token；用户epoch/设备撤销/类型不符均拒绝；新会话替换本设备旧会话 |
| GET /v1/devices | 仅管理员，返回设备ID/主体/类型/启用/时间，不含secret/ticket/token |
| POST /v1/devices/{device_id} | 仅管理员，空对象，撤销该设备及会话并审计 |

grant、device、session只存秘密摘要；审计只存操作/主体/目标/时间。包类型和字段不是凭证，原请求鉴权、销售字段允许列表、同主体幂等及价格CAS继续执行。维护工具`tools/p07_provision_device.py`以getpass登录管理员，通过上述接口生成单个一次性文件；受控发放，不能当公共通用安装包配置。具体安装器集成留04。

启用设备认证的完整备份为`777-service-bundle-v5`，包含devices.sqlite3快照和哈希、原auth/财务/输出及运行资源。独立恢复保持账本/actor映射，同时撤销全部设备、会话、登记材料，旧凭证不能复活；默认维护，再由部署人员重新授权。新宿主仍读旧v1～v4包，未启用设备认证仍产原v4；旧宿主/旧Python恢复器不能接受v5，禁止降级为Python宿主绕开设备认证，恢复及版本切换必须使用兼容的新宿主。没有静默升级生产身份库或覆盖旧账本。

合并了同时到达的用户导航调整`d8d9481`：管理入口位于顶部导航，退出仍在原账户菜单；02未改回旧布局。合并后8项真实桥接浏览器检查和12项设备协议重新通过，118项当前源码指纹见[合并报告](P07-02-nav-integration-report.json)，原合并前证据保留。

## 验证与Windows入口

辅助结果与历史失败见[P07-02检查证据](P07-02-checks.json)。辅助原生dispatcher通过真实Rustls HTTPS检查两种模式、同主体多设备、销售过滤/他人订单拒绝、过期会话恢复、单设备撤销、跨profile复制拒绝、未知提交恢复及v5完整独立恢复。开发主机重复启动实际验证固定端口/证书和指定账号，并保留合成数据。辅助证据不替代实际Windows DPAPI/WebView2。

CI保留原01完整构建/协议/浏览器及实际窗口回归，追加02母子验证构建、真实设备协议及两种实际WebView2无登录启动/提交/直接invoke拒绝、自然关闭与临时目录清理。正式安装器、多DPI与真实主机部署仍属03/04/P08。

本机更新前先关闭旧记账器和临时服务。在当前P07分支执行：

```powershell
& {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
    py -3 tools/p07_device_check.py --windows-smoke --jobs 1 --output reports/p07-02-windows-01
    if ($LASTEXITCODE -ne 0) { throw 'P07-02验证未通过，请保留报告' }
}
```

人工常规开发体验：

```powershell
$env:CARGO_BUILD_JOBS = '1'
npm --prefix desktop run tauri dev
```

无需另开终端启动随机fixture或填写登录页。此入口的配置固定于本机开发目录；服务证书过期、目录损坏或端口已被其他程序使用应明确报错，不能随意覆盖或把未核验服务当作已连接。P07-02已按用户明确指令[验收](P07-02-acceptance.json)，03已接续；04/P08未启动。开发退出生命周期修复及03 Windows入口见[03契约](P07-03-presentation-contract.md)。
