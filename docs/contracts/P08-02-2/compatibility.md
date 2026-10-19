# 现状差距、存储兼容与实施检查

## 1. 源码审计基线

下表保留 A 阶段的源码差距审计，不是 B 之后的当前实现状态；B 的源码和针对性结果见[实现说明](../../verification/P08-02-2-B-implementation.md)。

| 现有位置 | 观察 | 后续工作 |
| --- | --- | --- |
| `crates/quote-host/src/devices.rs` | 777-device-auth-v1，票据 30–3600 秒，仅一设备绑定；会话映射原业务用户 | B 增加可分发包授权，保留单票据语义，不能放宽旧票据为无限共享 |
| `desktop/src-tauri/src/client/enrollment.rs` | 设备 candidate/active 文件与旧 bootstrap；依赖预先提供票据 | D 接新协议，保留先持久化再请求的幂等语义 |
| `crates/quote-host/src/auth.rs` | Actor 只有 subject/role，密码用户及 admin 粗角色判定 | B 引入 scope/主体类型，禁止正式 device 旁路旧管理接口 |
| `desktop/src-tauri/src/permissions.rs` | 原生包能力及裁剪已存在 | B 在 Host 重复强制授权；D 保留原生上限 |
| `crates/quote-host/src/service.rs` | 多处提前返回和独立输出路由 | B 统一鉴权，不能只保护主业务分派 |
| `crates/quote-host/src/cluster/membership.rs` | 旧邀请 1800 秒、一次性节点绑定；peer 上限 128 | B 增自动候选许可并遵守现有站点资源上限 |
| `crates/quote-host/src/cluster/snapshot.rs` | v1 快照固定数据库白名单及版本校验 | B 显式升级快照兼容，不默默忽略新授权表 |
| `crates/quote-host/src/recovery.rs` | data-backup-v2 逻辑用户仅 id/username/role/enabled，恢复禁用用户 | B 保持归属可解析，逻辑备份不携带接入秘密 |
| `deployment/windows/host-identity.ps1` | 已有 SID、机器、根目录和资源归属核对 | B/C 复用，不能以相同 IP 替代 |
| `crates/quote-security/src/protect.rs` | Windows 当前用户 DPAPI | C/D 区分交互用户与后台运行账户，不能跨账户直接复制密文 |
| `desktop/tools/package.mjs` 及安装脚本 | 仍需连接/登记材料，现行 release 清单非可分发授权 | E 后续实现选择式界面，再接 B/C/D 新契约 |

## 2. 授权存储设计

选择在 **既有 auth.sqlite3 内升级到 schema user_version=2**，不新增另一个与用户主体无法原子绑定的身份库。保留原 users UUID、订单归属、旧密码摘要和用户 enabled/epoch。增加下列逻辑实体（具体 DDL 在 B 编写，不把本文当成可直接执行的迁移）：

| 实体 | 必须持久化的约束 |
| --- | --- |
| site_binding | 单一站点、原 ledger_id、trust_revision、升级绑定状态 |
| issuers | 唯一 issuer_id、秘密摘要、允许版本/能力/额度、状态/epoch |
| package_grants | 唯一 package_id、不可变清单与摘要、登记秘密摘要、期限、额度/计数、状态 |
| principal_modes | subject 外键，legacy_password 或 device_only；自动创建主体一律 device_only，密码登录拒绝 |
| automatic_devices | 全站唯一 device_id、subject、package_id、秘密摘要、状态/epoch |
| automatic_sessions | 会话摘要、主体类型/ID、包/主体纪元、到期时间；不得存明文秘密 |
| automatic_node_bindings | node_id、package_id、许可摘要、节点秘密摘要、reserved/active/revoked、关联 peer 与回执 |
| automatic_receipts / audit | 请求范围、请求 ID、规范请求摘要、无秘密回执及变更审计；相同键异内容冲突 |

自动主体仍占现有 users 行，系统用户名使用合法的唯一设备标识，不要求用户填写。为兼容旧非空字段，可存随机不可用密码的盐/摘要，但 **不能仅依赖“没人知道密码”**：principal_modes 必须阻止 device_only 密码登录。自动主体创建、设备登记、额度占用与回执在同一 auth 数据库事务提交；密码模式用户默认迁移为 legacy_password。

旧 devices.sqlite3 保留旧设备和会话；新自动设备使用 auth 库的独立命名表。业务鉴权结果带来源类型，不能在 v2 校验失败后尝试把同一 token 当旧管理员会话解释。群集 peer 库与授权库的跨库恢复采用 enrollment.md 的意图/回执流程。

迁移必须事务化并留升级前受保护备份，校验 application_id、已知旧 DDL/版本及完整性后才写新表；未知库或半迁移不能强制改版本。成功后旧 Host 不允许直接打开 schema 2。回退要停止新写入并恢复匹配的整套升级前数据库与二进制；不得仅替换旧 exe 或丢新表继续运行。

## 3. 副本、备份和旧设备

- 新快照格式 `777-cluster-snapshot-v2` 声明 auth schema 2 和 scoped-auth 协议，继续严格数据库/产物白名单，禁止把 TLS 私钥、发行秘密或配对材料加入快照。授权摘要可随受控副本复制；节点仍不能成为写主机或本地签发授权。
- 在主机迁移前核对已登记节点的能力；不兼容节点暂停接收新快照，保留旧副本并由维护日志标记待配套升级。新母版节点直接要求新版本。不能以“下载成功”掩盖旧节点无法打开 auth schema 2。
- 旧桌面身份及业务主体不重建；已签发 v1 票据仍按单设备规则运行。旧客户端只有粗角色授权，其改用细分能力需经过新版接入，不宣称本轮契约已约束所有旧客户端。
- 旧节点身份迁移必须持有原节点凭据并核对部署归属，或由受信维护明确重绑；仅有本地账本文件/机器名不能领取复制权。现场 .38 是否与 .23 同账本仍未核验。
- `.qbackup` 保持业务逻辑 v2 格式，只导出已有用户描述列和业务数据，不包含 issuer/package/device/node 秘密或会话；新用户必须包含在 owner/author 完整性检查中。恢复后全部用户仍禁用，不恢复发行能力，不把恢复出的独立账本自动当作原可信站点。若后续改变逻辑备份字段，必须另升格式，不挤入 v2 未知列。
- `.xlsx` 继续同快照可读业务导出，按月分表、表内按日；同日双位置交付沿用既有流程。A 不改变备份实现及目录。

## 4. 后续定向检查矩阵

| 实现任务 | 必须提供的证据 |
| --- | --- |
| B 首次绑定 | 正确部署可绑定；错误所有者/站点/证书拒绝；超时清理；保存后确认响应丢失可重试；不修改原账本/证书 |
| B 发行授权 | 同包多设备；到期只阻止新增；撤销影响现存会话；改角色/权限/摘要拒绝；额度并发无超额 |
| B 授权边界 | sales 拒绝财务/节点；有限 manager 拒绝旧维护 API；输出下载/重试/历史裁剪及销售归属无旁路 |
| B 存储兼容 | 事务失败恢复；旧用户/订单保留；v2 主体无法密码登录；新逻辑备份可恢复但无接入秘密；旧节点明确阻断 |
| C 母版部署 | 主机识别不靠 IP；已有独立账本不覆盖；节点意图跨库中断后续做；运行账户保护存储可读取 |
| D 桌面接入 | 两设备不同主体；丢响应/重装保持身份；跨角色不混草稿；撤销不自动创建新身份；正式 UI 无技术提示 |
| E / F / G | Figma 先行、选择式封包、备份命名、限量脱敏日志；不把 UI 隐藏当作 Host 鉴权证据 |

以上为实施检查矩阵；B 对应项的源码与隔离结果见[B 实现说明](../../verification/P08-02-2-B-implementation.md)，C/D 和 E 的源码/隔离结果见[C/D 说明](../../verification/P08-02-2-CD-implementation.md)，F/G 源码与针对性结果见[F/G 说明](../../verification/P08-02-2-FG-implementation.md)；真实现场项仍未执行。A 当时只做文档差异、链接及约束一致性检查，不运行产品测试，不重启现场服务，不恢复已取消的 Windows 构建准备/封包验收。
