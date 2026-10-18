777 独立后台包（服务电脑无需开发者版）

开发电脑运行 npm run package:host 构建此包。只复制本包到服务电脑，不复制开发数据库或开发账号。
服务电脑无需 Git、Node、Python、Rust SDK、Tauri 或开发者版。使用 Windows 自带 PowerShell 5.1 即可。

解压后直接双击 collect.cmd 采集主机信息；也可在该文件夹打开 PowerShell：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1
默认只采集本机信息，日志在本包 logs\本次启动文件夹\runtime.jsonl。

先完成主机身份与目录登记，再在4.23电脑准备新后台（以下目录仅为示例）：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation prepare -Root D:\Quote777Host -Backup \\192.168.4.23\共享\backup -Hidden D:\Quote777Hidden
将提示输入新业务管理员密码。初始化后仍停止；不创建开机任务。
失败时保留目录，使用相同参数将 prepare 改为 configure，并输入原业务管理员密码。

准备主机的同一Windows账户，在提权PowerShell中注册开机任务：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -Operation install -Root D:\Quote777Host
系统凭证框要求的是该Windows账户密码，不是业务管理员密码。
之后将install改为start启动、status查看、stop正常停止、remove移除已停止的开机任务。
只有明确执行install才注册开机任务和对应防火墙规则；移除任务不删除业务目录。

服务根的connection.json只含公开连接和证书，用于开发电脑最终本地封包母版/子版。
服务主机后台运行期间不需要打开母版、子版或开发者版。
4.38仅可采集信息，当前不允许准备独立备用账本。主备复制与安全接管尚未实现。
任务Running不等于业务或备份已验收；维护前应确认正常退出及LastTaskResult=0。
