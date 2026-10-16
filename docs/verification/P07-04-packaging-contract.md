# P07-04 Windows母子封包与安装

用户2026-10-16“哦 收尾03开始04”，[03用户验收](P07-03-acceptance.json)与[04启动](P07-04-start.json)分别登记。唯一阶段分支保持`stage/p07-tauri-desktop`，基线8481b52。当前为已实现待Windows CI/实机验证，未宣称04验收；P08真实部署/数据切换未启动。

## 构建与公开配置

复用锁定Tauri2.12.2 CLI、Tauri2.12.3与现有NSIS能力，无新增生产依赖。Node标准库校验证书DER SHA256、HTTPS origin和允许字段；开发bootstrap只导出公开connection，不复制账号、密码、登记票据、草稿或整个profile。构建要求工作区干净，输出目录新建，角色只能为manager或sales；生产特性不含verification，Rust构建脚本也会拒绝包混入verification或debug。正式前端使用构建期角色剔除开发连接/登录组件，打包后检查实际JS不含该表单；开发入口仍保留原配置功能。`--package-info`仅输出编译后的公开包元数据，用于核对类型/版本/源码/信任配置摘要，不提供调试IPC。

在仓库根目录的PowerShell中执行，输出放在已有reports父目录下：

```powershell
New-Item -ItemType Directory -Force reports | Out-Null
# 路径指向部署人员选定的原生bootstrap，或已导出的公开配置。
node desktop/tools/deployment.mjs export --from C:\deployment\bootstrap.json --output reports\connection.json
$connection = (Resolve-Path reports\connection.json).Path
$reports = (Resolve-Path reports).Path
npm --prefix desktop run package:desktop -- --delivery manager --connection $connection --output (Join-Path $reports manager-release)
npm --prefix desktop run package:desktop -- --delivery sales --connection $connection --output (Join-Path $reports sales-release)
node desktop/tools/deployment.mjs verify --release reports\manager-release
```

`package:desktop`从desktop启动时，相对路径以该工作目录为准；上例使用已解析的绝对路径。两个输出目录均必须尚不存在；构建失败保留诊断，不把残留文件视作新包。

默认`offlineInstaller`内置WebView2离线安装器；可用`--webview downloadBootstrapper`生成需要联网取得运行时的较小版本。模式来自锁定CLI的配置schema及[Tauri官方安装说明](https://v2.tauri.app/distribute/windows-installer/)。离线安装器增大包体；实际文件大小与SHA256写入release.json。Evergreen运行时由构建时Tauri工具下载，不承诺跨日期下载结果逐字节一致；整包哈希、Cargo/npm锁与字体清单用于本次构建溯源，不把普通哈希称为发行者签名。

## 产物与身份

| 类型 | 安装标识 | exe / 快捷方式 | 原生数据目录 |
| --- | --- | --- | --- |
| 母版 | cn.uniqueness.quote777.manager | quote777-manager.exe / 记账器母版 | %LOCALAPPDATA%\cn.uniqueness.quote777\manager |
| 子版 | cn.uniqueness.quote777.sales | quote777-sales.exe / 记账器子版 | %LOCALAPPDATA%\cn.uniqueness.quote777\sales |

每份release目录含真实NSIS安装器、对应exe、connection.json、enroll.ps1、依赖许可和release.json。清单记录版本、源码提交、业务/设备协议、profile兼容epoch、公开连接摘要、全部交付文件哈希/大小及锁定输入；实际exe元数据必须与生成清单相符。安装包不包含grant或通用秘密。CI包固定到临时合成服务，仅用于验证，不是已接真实主机的生产发行；P08才确定真实部署地址及人员授权。

两包均为currentUser安装，有独立标识和快捷方式。NSIS预安装hook拒绝已有另一角色exe或角色标记的同一安装目录；不会通过覆盖目录把子版替换成母版。原生凭证目录继续使用已有稳定位置，独立于安装目录/版本/新bundle标识；WebView2草稿存储位于其`webview2`子目录。开发profile保持独立，不自动迁移/复制开发账号或数据。服务器角色检查仍决定真实权限。

## 一次性登记

部署人员沿用`tools/p07_provision_device.py`在服务上为一个既有主体生成限时、限角色grant。真实客户端不需要Node/Python：验证包来源后，由部署人员在目标Windows用户下运行内置PowerShell脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\release\manager\enroll.ps1 -ReleaseDirectory C:\release\manager -GrantFile C:\private\one-device.json
```

该执行策略只作用于本进程，不修改系统策略。脚本校验交付文件哈希、角色、公开连接与grant，拒绝额外私密字段、重解析目录和覆盖已有bootstrap；保留device.bin、pending.bin及草稿。Node的`deployment enroll`提供部署机等价入口。正式exe再次把配置与编译进包的公开服务信任信息比对，跨服务/证书配置在原生登记前拒绝；服务继续校验限时票据、主体、设备和角色。成功后票据由原生层消费，凭证用Windows DPAPI保护；首次及后续启动直接进入业务。

## 升级、卸载和回退

同角色升级保持identifier、原生profile和草稿目录不变。服务端账本/备份不在客户端安装目录，卸载不会删除。未审阅的直接降级由NSIS拒绝；需要回退时先检查两份可信release清单：

```powershell
node desktop/tools/deployment.mjs check-rollback --current C:\release\current --previous C:\release\previous
```

只允许同角色、identifier、公开服务信任、业务/设备协议和profile兼容epoch相同的包。此命令只核对；由部署人员先确认/保留待核查请求与兼容包，正常卸载当前应用后安装已核对旧包。原生profile不删除；禁止以回滚服务身份库、恢复已撤销凭证或删除pending文件解决连接失败。变化涉及本地格式或协议时必须提高兼容epoch并提供明确迁移/恢复方案，不能复用旧epoch冒充兼容。

## 自动验证与待验收边界

原P07完整Windows门槛保持；新增manager/sales矩阵分别构建当前版及补丁号+1的实际安装包，执行中文含空格路径安装、跨角色目录拒绝、安装后原生元数据/真实设备登记与续期、升级、直接降级拒绝、受控卸载后兼容回退、身份原字节与WebView目录保留、自然关闭及临时目录完整清理。使用实际非verification exe，不把验证版换皮当安装包。设备票据仅留在临时服务根，上传产物不含这些秘密。

`tools/p07_package_check.py`只运行Windows，失败必须返回非零。CI若为提权runner，会如实登记，不能称为普通Windows用户验收；真实非管理员、无WebView2/断网干净系统、完整安装后业务UI操作及用户视觉仍需目标环境证据。离线安装配置和已装运行时机器上的安装通过不等于证明“干净无运行时”场景。检查明细见[P07-04检查](P07-04-checks.json)，04在这些门槛完成前不收尾。
