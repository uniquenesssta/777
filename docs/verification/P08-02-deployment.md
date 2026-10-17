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

## 在实际Windows服务电脑执行

先只采集当前机器的系统、Windows账户/SID和本机IP，并写入本次运行日志：

```powershell
npm run deploy:host
```

当前未取得两台电脑的采集结果，不能将它们登记为已经能运行Windows后台。下面是后续操作格式，路径为示例，由部署人员选定；执行前保留原程序和已有目录。`--root` 必须是父目录已存在、目标尚不存在的本地目录，备份位置必须为绝对路径。

```powershell
npm run deploy:host -- prepare --root 'D:\Quote777Host' --backup '\\192.168.4.23\共享\backup' --hidden 'D:\Quote777Hidden' --admin manager
```

准备会要求输入新的业务管理员密码（12～128字符），成功后服务仍停止。若在备份配置中失败，使用同一目录、原管理员密码和明确选定的路径运行 `configure`，不要删除目录或重新初始化。

```powershell
npm run deploy:host -- configure --root 'D:\Quote777Host' --backup '\\192.168.4.23\共享\backup' --hidden 'D:\Quote777Hidden' --admin manager
```

准备主机的同一Windows用户在提权PowerShell中注册任务；系统会要求该Windows账户的实际密码。任务/防火墙操作需要Windows权限，不能通过换成另一用户绕过SID一致性核对。

```powershell
npm run deploy:host -- install --root 'D:\Quote777Host'
npm run deploy:host -- start --root 'D:\Quote777Host'
npm run deploy:host -- status --root 'D:\Quote777Host'
```

维护前正常停止并检查任务已经结束；不要在Running时移除任务、替换程序或尝试第二个写端：

```powershell
npm run deploy:host -- stop --root 'D:\Quote777Host'
npm run deploy:host -- status --root 'D:\Quote777Host'
```

真正启用前仍需：主机重启后的HTTPS/设备入口、当前身份对备份目录的访问、每日双格式备份和独立恢复，以及首批1台母版和实际子版的人员/设备映射。最终本地封包沿用[P07流程](P07-04-packaging-contract.md)，连接输入改用本次生成的 `connection.json`；不下载远端测试包，不重跑已取消的母子构建准备验证。

## 验证与既有失败

[P08-02检查记录](P08-02-checks.json)区分辅助检查、Windows功能CI和真实部署。

上轮 `aca4ce3` 的Windows功能CI [39036319450](https://github.com/uniquenesssta/777/actions/runs/39036319450)最终失败：29个浏览器用例中1个用例在筛选后对全页“查看详情”调用click，匹配20个按钮触发strict mode错误。原Rust检查已通过；后续原生客户订单步骤尚未执行，不写成通过。本次按订单号00001的具体行定位并断言唯一，再点击该行详情，保持原草稿/放弃行为断言，未削弱成随便取第一行。

本次功能CI扩展到P08分支，新增部署策略检查、PowerShell语法解析、正常监管退出的原生HTTPS检查及正式设置地址隐藏浏览器用例。母子installers仍默认跳过。新增Windows任务注册/重启、真实主机部署、跨机复制/接管和完整P08-02验收没有完成。

代码已提交 `a72fa83`，新一轮[Windows功能CI39043402540](https://github.com/uniquenesssta/777/actions/runs/39043402540)已启动：记录时desktop-contracts运行中，installers已跳过，尚无通过结论。本条仅登记发起状态，后续以实际完成结果为准。

该轮随后失败于新增部署单元检查：Windows路径短名/完整名称不一致时，服务根未规范化而备份目录已规范化，导致重叠目录没有在构建前被拒绝。现已将经本地磁盘/重解析检查的服务根也规范化；原拒绝断言保留，本地4项重跑通过，Windows复查待新提交触发。原生和浏览器步骤本轮尚未执行，见[首轮Windows失败记录](P08-02-windows-ci.json)。

修复提交 `ae313a1` 的[第二轮Windows功能CI39043638535](https://github.com/uniquenesssta/777/actions/runs/39043638535)中，4项部署检查及PowerShell语法解析已通过；记录时正在执行Windows Rust/浏览器/WebView2步骤，后续后台/备份检查尚未执行，installers仍跳过。计划任务注册和真实重启仍未在服务主机验证。
