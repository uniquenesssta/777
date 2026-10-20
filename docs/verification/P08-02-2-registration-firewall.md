# Host 注册防火墙核验修复（2026-10-20）

## 现场证据与边界

用户 runtime(7).jsonl 显示：沿用账本后停止任务，automatic-host-update 成功并发布第 22 代快照，随后 host-registration.ps1 抛出 REGISTRATION_FIREWALL_OWNERSHIP_CONFLICT。外层 HOST_ELEVATED_ACTION_FAILED 是转述，不足以证明密码或提权失败。原日志没有具体字段值，不能断言现场究竟是哪项不匹配；也没有重新启动成功记录。

本次仅修复 Host 部署核验，不修改开发者数据源、页面导航、母子权限或封包签发流程，不处理 CI 失败。P08-02-3 E 仍暂停。

## 实现

- 独立 host-registration-firewall.ps1 负责规则读取、语义比较和差异日志；部署编排继续由 host-registration.ps1 负责。
- 连接范围统一为数组再比较，避免 RemoteAddress 是标量字符串时取到首字符；TCP / 协议编号 6、Profile 文字 / 编号 3、路径大小写及斜杠等价处理。
- 所属描述、程序、8479 端口、TCP、单一 LocalSubnet、入站允许继续严格匹配；同时确认规则启用且为 Domain/Private，不扩大到公网或任意地址。真实差异不删除或覆盖未知规则。
- 在停止任务和原生更新之前核验规则；缺失时创建并重新读取核验。失败不会为这一检查先停止原有后台。
- 冲突日志只记录规则名称及不匹配字段的 expected/actual；不序列化完整 CIM 对象、不记录业务数据或凭据，沿用现有日志限流和轮换。
- 新模块纳入 Host 压缩包资源清单、完整性白名单及控制台加载链。

## 验证

- 本地 Python Host 打包回归 3 项通过：完整资源/哈希、Host 专有信任材料、已有输出与非 Windows 资源拒绝。这是使用合成二进制的打包逻辑测试，不是 Windows 安装包构建。
- git diff --check 通过。
- 新增 6 项 Windows PowerShell 5.1 回归：标量/数组/协议等价、10 类真实字段差异、重复规则、首次创建后重复更新、创建失败不停止后台、重试部署启动原有 Disabled 任务。测试使用真实部署函数，防火墙/任务系统边界由受控函数替代，已纳入现有 test_p08_*.py 发现范围。
- 当前辅助环境没有 Windows PowerShell，因此以上 6 项及原有 3 项 Windows 包执行检查均跳过，不能计为通过。尚未执行 Windows 真实防火墙或 4.23 现场复验。未执行母子安装包专项，不轮询 CI。

## 使用

开发电脑 git pull 后运行 npm run package:host，重新生成与本机签发身份配套的 Quote777Host.zip。在原主机更新原 Quote777Host 内的部署包文件，保留 host-local.json、Quote777Service 与 Quote777Hidden，再运行 deploy.cmd。不要手工只替换脚本而留下旧 host-package.json 哈希。若实际字段仍不匹配，提交本次 runtime.jsonl，其中会包含具体差异。

## 同轮开发版页面问题

用户补充截图仅显示开发者工具。App.tsx 在 session 为空时隐藏业务导航；这不能证明页面被删除，也不能证明与 4.23 停止有关。核对 f08bf5a 差异后确认未改启动、连接或导航条件。npm run dev 使用本机 127.0.0.1:18477 服务；封包独立本机签发。此前将截图与 Host 停止联系起来的推断已撤回。开发版具体启动失败须依据该次开发端日志继续定位，不修改连接目标或将本机入口接到 4.23。
