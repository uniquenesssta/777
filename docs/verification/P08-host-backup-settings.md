# P08 开发者维护当前 Host 的每日备份

## 范围

开发者工具新增独立的「Host 设置」。使用当前已认证、证书固定的业务连接读取和应用配置；不借用本机开发启动器，不继承到母版/子版封包。正式端无入口，原生权限检查禁止此操作；Host 只接受管理员登录会话，自动签发及旧设备会话不能调用维护接口。从机拒绝此维护请求，不转发后误改主机。

可选择北京时间 00:00–23:00 整点及普通备份目录。目录列表实际来自 Host，最多 500 个子目录，支持驱动器、上一级、完整共享路径跳转；不读取文件内容，不递归扫描。隐藏备份目录保持现有配置，只读，不接受修改字段。

## 应用语义

- GET `/v1/developer/backup-settings` 返回账本、两个路径、时间、配置摘要 revision。
- POST 同路径带 `ledger_id`、`expected_revision`、`backup_dir`、`daily_hour`。旧配置冲突与错误账本拒绝；重复提交已应用的相同选择可回读成功，不生成多次备份。
- 新目录必须已经存在且由 Host 运行账号可写，不能与业务根目录/隐藏备份互相包含；目录别名按实际路径校验。时间单独修改不依赖共享备份在线。
- 普通目录与 `daily_backup_hour` 一起原子写入 `private/service.json`；未设置该字段时继续兼容原 `daily-backup.json` 时间。隐藏目录仍取原配置。本机维护命令和 Host 控制台读取兼容此优先级。
- HTTP 维护路由与每日备份调度共用独立 backup Service 和互斥锁，避免只改 HTTP 内存而调度器仍用旧目录。主业务锁不承担目录网络操作。
- 保存后 UI 再 GET 回读，对比账本与 revision 才显示成功。失败保留选择，支持重新读取/再次应用。原目录已有备份不删除、不搬迁。
- 当日已有快照继续使用原来的每日去重规则。新目录可触发当前仍有缓存快照的补送；不会因为修改时间重新生成同日多个业务快照，也不会补造历史日期。
- 维护请求在 auth_audit 记录 `host_backup_settings_requested` 与前后选择；该条表示请求，是否实际生效以原子保存后的配置和回读为准。

## 一次性升级

本次新增 Host 接口，需要在开发 Windows 电脑 `git pull` 后运行 `npm run package:host` 生成新包，更新 4.23 上已有 Host 程序；不要删除 Quote777Service、Quote777Hidden 或其内容。仅复制新包不会自动替换正在运行的已部署二进制。

现有已部署且已经是 primary 的主机，可使用包内「8 将现有后台设为同步主机」的现有受控升级路径：它停止旧任务、使用新包核验后的 select-host --upgrade-resources 更新程序、核对账本与证书、保留现有 primary 身份并重新启动。此路径不得用于将 replica 强行变为 primary。新包脚本放入原 Quote777Host 位置并保留 host-local.json。Windows 密码和业务管理员凭据仍仅在本机现有升级流程输入。

开发电脑更新后重启 `npm run dev`，打开「开发者工具 → Host 设置」，确认当前连接为 4.23，再选择和应用。此次升级之后，修改这些备份设置不需重新封包、不需重装或重启 Host；母版、子版也不需因此重新封包。旧 Host 在本页显示需升级提示，不假报成功。

## 验证记录

- 静态：TypeScript、Rust fmt、git diff --check、Host/native clippy（warnings denied）。
- 构建：Linux 隔离辅助 Host release 与 native verification bridge；不是 Windows 母/子安装包构建。
- Host 集成：真实调度生成 data.qbackup + data.xlsx、新目录生效、保留旧文件、重复请求/每日去重、配置重新读取；过期 revision/错误账本/无效小时/冲突目录/隐藏字段注入/销售身份/正式能力边界拒绝；共享离线时只改时间。
- 浏览器：开发者选择远程目录/小时、保存并回读、失败保留选择、旧 Host 提示、720px 无横向溢出。该 UI 测试使用明确的测试夹具。
- 原生与 HTTPS：独立真实 Rust Host + Rust desktop bridge，在线改目录/小时后调度自动执行，Host 重启后配置及当日备份身份保留；不使用 UI 测试夹具代替此链路。
- Figma：复用现有组件新增 165:2310（Host 设置）、165:2350（远程文件夹选择），开发者专用。
- 未做 Windows 实机、SMB 实际权限、母/子封包及安装验证；未轮询 CI。

## 2026-10-21 旧部署配置读取修复

用户 `runtime(9).jsonl` 显示 `host-deployment / host.console.failed`，位置 `host-settings.ps1:14`，异常 `System.Management.Automation.PropertyNotFoundException`。Host 控制台启用 StrictMode，而旧 `service.json` 没有新增的可选 `daily_backup_hour` 属性；直接访问即异常，尚未进入部署操作。

改为先通过 `PSObject.Properties['daily_backup_hour']` 查询属性是否存在，再读取 Value。缺省和 null 沿用已有 daily-backup.json 时间；00:00 正确保留，不按 false 处理。只调整读取逻辑，不修改用户配置、业务数据、证书或任务。

新增 Windows PowerShell 5.1 回归覆盖 7 种配置情形（无每日文件、旧每日配置、null、0/6/23、移除覆盖字段），真实临时 JSON + StrictMode，并核对读取不写回文件。当前环境无 PowerShell，测试已发现但明确跳过，不能计为 Windows 通过；Python 语法和 git diff --check 通过。需要拉取后重新生成 Host 包，使用其完整校验清单及脚本，不手改部署包绕开完整性检查。无需删除 Quote777Service 或 Quote777Hidden。
