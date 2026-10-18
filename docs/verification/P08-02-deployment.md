# P08-02 独立后台部署入口与正式母版设置

用户于2026-10-17 22:30:19（Asia/Shanghai）明确“开始推进02”。沿用 `stage/p08-cutover`，启动基线 `91c86b42cd6ece05540d6166033c02297e16274d`，工作区原本干净。01的现场资料和主备实现缺口转接，不补记01已验收，不启动03正式启用。

## 已实现与未完成范围

- `deployment/host` 按策略、机器采集、原生程序调用、准备流程和CLI分工；`deployment/windows` 管理Windows身份、后台监管及计划任务。根目录增加 `npm run deploy:host`，默认只采集当前Windows电脑信息，不初始化账本、不注册任务。
- `prepare` 仅在本机地址包含192.168.4.23时允许创建独立的新服务根目录。复用现有原生初始化、设备授权开关和每日双位置备份配置；不从开发环境搬订单、价格、账号或草稿。服务根使用本机磁盘，备份仍允许所选UNC/共享位置，目录不得与主机资源重叠。
- `configure` 用现有管理员身份补完已创建且停止的主机；不重新初始化账本，不覆盖不同的部署资源或连接文件。中途失败保留目录和现有订单；管理员密码通过原生标准输入传递，不在参数、文件或报告保存。已有外部主机的构建来源未知时记录null，不编造源码归属。
- 实际后台资源在操作者本机按锁文件构建，最多12个构建任务；不构建或验证母子安装包。`--skip-build` 只复用已有Windows资源，原生初始化还会验证实际worker和宿主资源。主机资源构建要求已跟踪源码干净。
- 初始化成功输出公开 `connection.json`（HTTPS地址、公开证书、证书指纹），供最终本地母子封包使用；私钥、业务密码和设备票据不在公开连接文件。`private/deployment.json` 登记账本、源提交、主机、当前Windows SID和后台脚本/程序SHA256。
- `install` 为这个账本注册独立的开机任务，使用准备主机时的Windows账户，以有限权限运行；仅为该程序和端口添加域/专用网络的LocalSubnet入站规则，不关闭防火墙。安装不启动后台，后续 `start` 单独启动；任务重试最多3次，禁止同任务并发实例。
- Windows任务密码由PowerShell凭证框输入，只交给系统注册任务，不放命令行或日志；它与业务管理员密码不同。采用带密码的开机任务，不使用无网络凭证的S4U，也不把仅用户登录后启动写成开机即运行。依据：[任务注册](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask)、[任务设置](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset)、[登录类型](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)。实际机器的账户权限、网络访问和重启结果仍待核实。
- 监管脚本持有本账本的文件锁，校验SID及资源指纹，通过新的生产参数 `--shutdown-stdin` 启动原生后台；该参数只开放退出通道，不启用故障注入、测试字体或验证权限。`inspect` 增加 `shutdown_control=stdin-v1`；旧测试参数的隔离门槛保持。
- `stop` 先禁用后续自启，再向本目录监管脚本请求正常退出，等待原生服务排空并释放账本所有权，不按端口杀进程。`remove` 只移除已核对归属、已停止的任务/防火墙规则，保留账本、设备与备份。`status` 显示任务状态和LastTaskResult；Running不单独证明HTTPS、实际业务或每日备份已验收。
- 操作者入口沿用根目录 `logs/<本次启动>/runtime.jsonl`，记录机器采集、操作和错误码/HRESULT，不记录密码。后台每次启动在所选服务根的 `logs/<本次启动>/runtime.jsonl` 记录，同样有噪声合并和容量轮转。

**主备复制和自动接管没有实现。** 已保存地址顺序4.23→4.38，但当前可运行链路仍是一个HTTPS服务。工具会拒绝把4.38初始化成独立写入主机，不能把两套新账本称为同步完成。复制确认规则、共同设备/回执、单写入权与安全接管仍属本阶段未完成项；本轮没有接触4.23或4.38，也没有注册真实计划任务、开防火墙或发放设备。

## 正式母版设置

先在原Figma文件完成可编辑变体 [92:1556](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=92-1556)，复用既有导航、Field/Button、紫灰变量和Noto Sans SC，无扁平界面图片。截图发现原组件73px标签列换行，缩短示意标签后复验；目标字段 [92:1646](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=92-1646)已取得含截图的设计上下文。没有新图片或图标资产，实际代码保留既有设置布局和业务标签，未扩大到重做整页。

- 正式母版原本不显示开发连接/登录设置，继续保持。设置页的报价表、图片和备份位置含完整4.23地址时，显示“已配置的…位置”；value/title均不回显地址，开发版仍显示真实路径。
- 对这类位置，输入框只读，管理员可继续用原文件夹选择器更换位置。选择和发布始终使用原真实值，不把展示标签写成文件夹路径；其他地址及本地路径的编辑能力保留。
- 设置和导出记录已拆为 `features/settings/SettingsPage.tsx`、`features/TasksPage.tsx`，地址展示规则在独立模块；不继续把两个页面职责堆在一个文件。
- 隐藏范围为普通设置界面；不承诺开发工具、系统目录选择器或网络诊断无法查到实际网络地址。角色权限继续由服务端决定。

## 服务电脑使用独立后台包（2026-10-18修正）

用户确认4.23和4.38均为Windows电脑。10:24收到的日志来自操作电脑4.17，只证明本机采集成功；不把该电脑的账户、SID或地址登记为目标主机身份，也不将这些私人信息提交Git。

服务电脑不需要安装开发者版、母版/子版、Git、Node、Python或Rust SDK。此前要求在每台服务电脑运行 `npm run deploy:host` 的步骤会额外要求开发环境，已改为下列独立流程；该npm入口保留给开发者维护。

在开发用Windows电脑的项目根目录，只构建后台包（按锁文件、最多12个构建任务）：

```powershell
npm run package:host
```

命令输出实际ZIP路径，默认 `reports/host-packages/<时间-提交>/Quote777Host.zip`。把这个ZIP复制到服务电脑并完整解压；无需把仓库、开发账号或开发数据库搬过去。后台包有独立文件白名单、源码提交和逐文件SHA256，包含两个Windows后台exe、PowerShell脚本和使用说明。当前版本不会生成真实服务器账号、证书或账本后再跨电脑搬迁；这些始终在目标机以实际运行身份初始化。

在4.23、4.38各自解压的文件夹中双击 `collect.cmd` 即可采集信息；每次日志在本包 `logs/<启动文件夹>/runtime.jsonl`。等价的PowerShell命令为：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1
```

随后先在4.23上准备独立的新服务根，路径以下仅作示例。服务根的父目录必须存在，目标根必须尚不存在，位于本机固定磁盘且不经重解析点；备份位置可选本机或UNC的独立目录，原生程序继续核对映射/链接身份及访问能力：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation prepare -Root D:\Quote777Host -Backup '\\192.168.4.23\共享\backup' -Hidden D:\Quote777Hidden
```

准备会要求输入新的业务管理员密码（12～128字符），成功后服务仍停止。若中途配置失败，保留现有目录、用原管理员密码，将上述 `prepare` 改为 `configure` 补配；不会重新初始化或删除账本。密码只通过UTF-8标准输入传给原生程序，不在参数、环境、日志或报告保存。

准备主机的同一Windows用户在提权PowerShell中注册任务。此时凭证框要求该Windows账户的实际密码，与业务密码不同：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation install -Root D:\Quote777Host
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation start -Root D:\Quote777Host
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation status -Root D:\Quote777Host
```

只有明确的install会注册开机任务/相应防火墙规则，不会默认启动服务。后台运行时无需保持开发者版、母版或子版打开。维护前使用 `-Operation stop` 请求正常退出，确认任务停止且LastTaskResult=0；remove只移除本账本已停止的任务/规则，保留业务数据。任务Running不单独证明HTTPS、实际业务和每日备份已验收。

当前4.38可采集，不允许prepare独立备用写账本；主备复制/接管仍未实现。真正启用前仍需实机身份/目录、重启后业务入口、双位置双格式备份的独立恢复，以及首批设备映射。最终母子封包继续在开发电脑本地进行，使用目标机生成的公开 `connection.json`；已取消的母子构建准备验证不重跑，不下载远端测试包。

新增脚本按采集、路径、包校验、受限日志、原生调用、准备和入口分工。见[后台包检查记录](P08-02-portable-checks.json)。

## 验证与既有失败

[P08-02检查记录](P08-02-checks.json)区分辅助检查、Windows功能CI和真实部署。

上轮 `aca4ce3` 的Windows功能CI [39036319450](https://github.com/uniquenesssta/777/actions/runs/39036319450)最终失败：29个浏览器用例中1个用例在筛选后对全页“查看详情”调用click，匹配20个按钮触发strict mode错误。原Rust检查已通过；后续原生客户订单步骤尚未执行，不写成通过。本次按订单号00001的具体行定位并断言唯一，再点击该行详情，保持原草稿/放弃行为断言，未削弱成随便取第一行。

本次功能CI扩展到P08分支，新增部署策略检查、PowerShell语法解析、正常监管退出的原生HTTPS检查及正式设置地址隐藏浏览器用例。母子installers仍默认跳过。新增Windows任务注册/重启、真实主机部署、跨机复制/接管和完整P08-02验收没有完成。

代码已提交 `a72fa83`，新一轮[Windows功能CI39043402540](https://github.com/uniquenesssta/777/actions/runs/39043402540)已启动：记录时desktop-contracts运行中，installers已跳过，尚无通过结论。本条仅登记发起状态，后续以实际完成结果为准。

该轮随后失败于新增部署单元检查：Windows路径短名/完整名称不一致时，服务根未规范化而备份目录已规范化，导致重叠目录没有在构建前被拒绝。现已将经本地磁盘/重解析检查的服务根也规范化；原拒绝断言保留，本地4项重跑通过，Windows复查待新提交触发。原生和浏览器步骤本轮尚未执行，见[首轮Windows失败记录](P08-02-windows-ci.json)。

修复提交 `ae313a1` 的[第二轮Windows功能CI39043638535](https://github.com/uniquenesssta/777/actions/runs/39043638535)中，4项部署检查及PowerShell语法解析已通过；记录时正在执行Windows Rust/浏览器/WebView2步骤，后续后台/备份检查尚未执行，installers仍跳过。计划任务注册和真实重启仍未在服务主机验证。

2026-10-18复查：第二轮CI39043638535的desktop-contracts最终success，installers为skipped；原有30项浏览器及后续原生功能步骤均已完成。本次独立后台包为后续新增实现，须另行检查，不能沿用旧CI冒充新包已验证。

独立后台包代码提交 `ddc537f`，新增[Windows功能CI39090902645](https://github.com/uniquenesssta/777/actions/runs/39090902645)中8项部署/包检查及PowerShell语法解析已通过，包括Windows PowerShell 5.1在无开发工具PATH下采集、拒绝错误主机/被修改的包、以及密码仅走UTF-8标准输入的检查。记录时Rust/浏览器阶段仍在运行，真实原生初始化/补配夹具尚待后续步骤，installers跳过；未据此登记实际4.23/4.38部署成功。


## 双击部署与管理入口（2026-10-18）

用户已在4.23完成初始化、开机任务安装和启动，提供任务Running输出；本机使用公开证书进行curl校验后收到业务服务的422/INVALID_TEXT响应，已确认空凭证在设备认证回退分支导致这个错误码，不据此补记已登录业务验收。随后4.17检查8477端口为True，4.23重启后再次检查仍为True；该证据只确认重启后端口恢复。实际操作由用户执行，维护端没有远程登录主机。Windows账号、SID和业务密码不提交仓库。

用户要求把整段手输命令整合进Quote777Host.zip。本轮新增：

| 双击入口 | 行为 |
| --- | --- |
| `setup.cmd` | 核验当前主机和包，必要时以同一Windows账户提权；准备新后台或补完中断配置；沿用已有账本；仅缺少开机任务时询问Windows密码并注册；仅未运行时启动；安静等待HTTPS响应 |
| `manage.cmd` | 中文菜单提供部署、状态与连接、启动、正常停止、打开日志和采集；退出菜单不停止后台 |
| `check.cmd` | 展示任务状态及端口/HTTPS检查；其他电脑没有公开连接文件时只确认端口，不绕过证书验证 |
| `collect.cmd` | 保留旧的只读采集入口 |

本现场公开默认值收进`host-defaults.json`：业务根D:\Quote777Service、普通备份\\192.168.4.23\共享\backup、隐藏副本D:\Quote777Hidden、主机4.23、8477端口、北京时间23点。程序包目录D:\Quote777Host与业务根分离。此文件不含密码。已有4.23直接沿用已设置业务密码，新主机首次准备才通过隐藏输入设置；Windows凭证继续通过系统对话框输入，不进入参数、Git或日志。

重复运行不会初始化已有账本、重置密码或重新注册运行中的任务。准备中断保留原目录，用原密码补完。UAC若换成另一Windows身份，入口在任何准备动作之前拒绝；提权父子进程共用本次有限轮转日志会话，检查轮询不逐条记录。网络检查使用Windows内置.NET及独立C#网络模块，校验证书DER SHA256和主机名称，使用未知的有效格式凭证获得401/UNAUTHENTICATED应答；仅端口可达或任意200页不能作为HTTPS服务就绪。检查不建立业务会话、不输出票据。

在开发电脑拉取后可运行`npm run package:host -- --skip-build`重新封装已有原生exe；本轮未改Rust资源。若无已有资源则正常运行`npm run package:host`。服务电脑解压新版包后直接双击入口，不删除D:\Quote777Service；无须输入长命令，也无须SDK。实际新版ZIP仍由用户Windows开发电脑本地生成，不下载远端测试包。

独立后台包上一轮Windows功能CI39090902645已最终success，installers跳过，真实原生准备/补配夹具也通过。本轮菜单新增Windows检查另见[双击入口记录](P08-02-console-checks.json)，不混用旧CI为新入口作验收。母子版构建准备保持取消，4.38复制与安全接管仍未实现。
