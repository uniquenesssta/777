# A：上传、回执与裁定协议

本文是 `777-offline-order-v1` 的分阶段契约。B 提供显式启用的 receive_only 接收基础；C 已实现显式 apply、业务拉取及独立授权裁定，实际边界见文末。终端离线模式仍待 D；客户端继续原在线模式，不猜测支持、不得把 404 当成已接收。

## 身份与授权

入口仍是受信任的 4.23 HTTPS Host。Host 从业务设备会话解析 `site_id + ledger_id + device_id + subject + package + capabilities + authorization_epoch`；设备 ID 等请求字段只能用于一致性核对，不能代替认证。销售只能提交/读取自己的订单与允许字段，母版也受所选包权限限制。价格维护、输出、发行和节点管理不随离线写入开放。

新设备使用既有 a2 业务会话。旧 device-auth-v1 设备在明确采用/升级后才能取得离线授权；仅密码登录的维护会话、节点会话、发行会话不上传业务离线操作。不能为方便维护，将所有 admin 自动变成冲突裁定人。

首次在线登记后，经设备认证获取 `777-offline-lease-v1`：签发者、key_id、site/ledger/device/stream/subject/package/授权 epoch、能力交集、允许价格版本及摘要、规则版本、签发/到期时间。采用 Host 专用 Ed25519 签名（B 锁定 ring 0.17.14），公钥经既有可信 TLS 通道绑定，私钥只在服务机受保护位置，不从发行密钥或 TLS 私钥推导。

B 租约请求为 `protocol + request_id`，可选布尔 `new_stream`。同一 request_id/正文返回同一签名租约；不同正文不能冒充重试。正常续期复用同一设备、包及授权/恢复 epoch 的 stream；恢复旧终端副本时显式 `new_stream: true`，保留原操作身份。响应为 body、signature、public_key；签名输入为 `777-offline-lease-v1\n` 加 body 的 canonical UTF-8。B 的价格摘要使用去除成本等私有字段的公共报价投影及 canonical 编码，所有角色采用相同口径；不对低熵成本值提供可猜测的摘要。D 需使用该投影验证缓存，不能下发完整成本价格库。

默认离线保存窗口 30 天，联网可自动续期；这是初始受控策略，正式端无设置项。原生层校验签名并维护受保护时间高水位，明显回拨或过期后保留已有订单和输入，停止新增正式落盘，使用既有业务保存反馈，不弹技术状态。不能承诺在完全断网时即时收到撤销，也不把本机时间当成可信撤销证据。

上传时重验当前身份/包状态/权限。已过期租约、撤销或权限变化的原始操作不得删除；可认证但不能应用的内容进入受限保全状态，供独立授权开发者处理。已失效设备不能靠“上传保全”绕过 401，原件继续留本机；后续重新授权的保全导入必须绑定原设备/主体来源。到期后跨过较长时间才回传的原单不凭自报创建时间自动放行。

## 操作身份与摘要

批次包含 `protocol, batch_id, operations`。批次 ID 只关联传输，不决定幂等；一批所有操作来自同一已认证设备/账本，批量最多 32 项，UTF-8 请求体最多 1 MiB，单项最多 256 KiB。超限先拒绝，不部分接收；客户端拆批重试原操作。

每项固定字段见 [examples.json](examples.json)：全局随机 UUID `operation_id/order_id/stream_id`、设备内单调 `device_sequence`、`site_id/ledger_id/device_id/owner_id/lease_id`、`kind`、`base`、业务创建时间、规则与数值版本、`payload` 和 `content_sha256`。金额、序号、版本在 JSON 里使用十进制字符串；不用浮点金额、电脑时间或外部订单号构造唯一 ID。业务时间保留来源，中央财务按核验后的业务日期归属，不按到达当天改写。

摘要为 `SHA256("777-offline-order-v1\n" + canonical(operation_without_content_sha256))`，输出小写十六进制。canonical 仅允许对象/数组/字符串/布尔/null：对象键限定 ASCII 并逐字节排序、数组保持顺序、UTF-8 无 BOM、无空白、字符串非 ASCII 原样编码，JSON 控制字符按标准转义，不转义 `/`、不做 Unicode 归一化，不允许孤立代理项、重复键或任何 JSON number。业务数值全部为字符串。批次 ID 和访问凭据不入摘要。Host 重算摘要，同时将认证所得设备/主体与原文绑定，不相信客户端仅填一个摘要。

转义采用唯一形式：引号与反斜杠分别写作 `\"` 和 `\\`；退格、制表、换行、换页、回车分别为 `\b/\t/\n/\f/\r`，其余 U+0000–001F 使用小写四位 `\u00xx`；其他 Unicode 标量直接 UTF-8 编码。UUID 使用小写标准 36 字符格式；device_sequence 和非空订单版本为 1 至 9223372036854775807 的无前导零十进制字符串。业务创建时间使用 UTC RFC3339 六位小数，必须核对格式但不将其当成可信排序/授权依据。

同 `operation_id` 同正文只返回原接收身份及最新持久状态；终态结果不因重试重算。同 ID 不同摘要或同 stream/sequence 不同操作返回 409，并在受限配额内保存碰撞证据；不改写第一份。旧在线 request_id 与离线 operation_id 共用命名冲突检查，不能从另一入口覆盖原请求。

`device_sequence` 用于防复原重号及核查，**不要求全设备严格依次应用**。处理依赖按订单链：`base.order_revision` 是最近已确认主机版本；`base.previous_operation_id` 指向同设备/stream/订单的上一条本机操作。创建的 base 两项均 null；连续本机修改引用前项，允许尚未取得主机版本。不允许环、跨订单依赖、跨设备引用或直接依赖别人的未决候选。跨设备以主机确认版本为共同基线，不能仅看修改时间决定胜负。

## 接口及状态

| 接口及阶段 | 语义 |
| --- | --- |
| B：设备业务会话 `POST /v1/offline/lease` | 在线核定身份、能力和价格版本，签发/续期租约；不宣告终端离线模式已可用 |
| B：`POST /v1/offline/operations` | 有限批量认证、校验并持久接收；202 只表示接收事务已提交，逐项返回稳定 ID/状态，不表示已应用 |
| B：`POST /v1/offline/receipts` | 最多 32 个原 operation_id 的状态查询；只读、限当前设备和主体，不返回业务原文、成本或拒绝原因，不用 GET 请求体 |
| `POST /v1/offline/changes` | 不透明游标拉取已确认投影/删除或撤销标记；最多 100 项及 1 MiB，分页不漏不重 |
| 开发者专用裁定接口（C） | 单独服务端授权、基础版本、稳定裁定 ID；普通母/子、发行/节点会话均无权调用 |

租约另有完整能力协商；当前 capabilities 没有这些字段，B 不提前返回可用。逐项基础格式/摘要/绑定验证失败时整批不接收并返回限定错误；可认证、格式正确但规则/权限已变化的原件可持久接收为 rejected 或待裁定，不能应用。每批接收事务只写原件与 received/rejected 状态，所有操作要么共同持久接收，要么未收到；后续按项独立处理，绝不为了一个业务冲突回滚无关订单。请求中断/超时后用原 ID 查回执。

| 内部状态 | 含义和下一步 |
| --- | --- |
| received | 4.23 已可靠存下原文，待处理，不计入中央金额 |
| waiting_dependency | 等待已知/未到达的前项；无关订单继续。超过 24 小时未满足转人工保全，不删除原件 |
| applied | 业务、订单版本、审计、去重结果和状态同一事务生效，返回确定业务回执 |
| conflict | 双方/共同基础版本保留，主机现行有效版本继续统计；争议增量不重复计账 |
| rejected | 不能依现有权限/规则应用，原件保留；通过新裁定操作处理，不能循环自动强行重试 |

已确定的冲突原件保持不可变；解决时追加有权限的新裁定操作并建立关联，记录原候选的处置结果，不伪造原件“本来就无冲突”。received/waiting 可续做，applied 的结果不可更改。conflict/rejected 的原候选不再自动应用，处理结果由裁定记录追踪。

404 回执只说明当前核查范围内未查到；不是允许换 ID。401/403 停止自动应用与盲目重传，保留本机数据；409 比对原件并进入保全；413 拆批；429/503 按服务端 Retry-After 和带抖动退避恢复。正式 UI 不投影技术状态或原始错误，业务保存失败保留输入。

## 合并、拉取与业务口径

kind 覆盖 create、edit、append_note、set_state；create 使用稳定订单/商品项 UUID，edit 携带稳定行 ID 与共同基础版本。payload 只含允许业务输入，不包含可自报的最终成本/利润、数据库路径或 SQL。已登记价格版本和规则由主机重算；获授权的历史价格不因后来发布新价被悄悄替换，缺失/不兼容版本保留候选等待处理。

payload 的类型边界：create 为 `snapshot + details + customer`，snapshot.lines 每项固定 `line_id + raw`，raw 沿用现有 normal/discount 业务输入且不带成本；details 为 customer/order_ref/wechat，customer 沿用显式归集选择。edit 为 `detail_changes + line_changes + customer`，detail_changes 仅允许变动的既有客户字段，line_changes 为按稳定 line_id 的 add/replace/remove（add/replace 含 raw）；不能修改 owner/order_id/创建时间。append_note 为 `note_id + body`；set_state 为 `state + reason`，state 仅 active/void。不接受未知字段；C 在此边界下实现来源价格、行排序与折扣关系的整体校验，不能通过任意 JSON patch 修改财务派生值。

沿用既有业务字段长度/数值规则：客户信息各最多 256 字符、备注最多 4096 字符；同时受整项字节限制，不因离线入口放宽线上校验。示例只覆盖创建/追加备注及传输依赖，不冒充 edit 合并或裁定功能用例。

同一操作重复只入账一次；相同客户不同订单号保留多单。同外部订单号的独立新单进入疑似重复核对，不自动删除或拼单。独立行新增、互不相关字段仅在可证明兼容时合并；价格/折扣/金额按关联整体检查。同字段不同值、作废对编辑保存三方快照等待裁定，禁止最后上传覆盖。C 需完成这些规则后才应用复杂修改。

拉取返回 Host 依据当前主体/包权限生成的业务投影；不得直接下载整个主数据库给子版。游标绑定主体、能力 epoch 和账本恢复 epoch；越权变化或恢复后游标失效，执行有权限的重建。单笔投影超过响应限制时用专门有界订单明细分页/分块，不无限增大响应或截断订单。下发写入确认区，再叠加本机未上传操作，不能覆盖唯一的本机候选。

Excel 历次金额红色、最终确认值黑色；中央汇总只取已应用的当前有效版本。界面沿用现有逐版本修改记录，不投影收件、拒绝或冲突技术信息。输出副作用用独立稳定任务 ID，不随上传重试再导出。

## C 已实现的接口与裁定边界（2026-10-20）

以下均为 POST，`protocol` 仍为 `777-offline-order-v1`，输入拒绝未知字段。没有新增正式端入口；完整离线能力仍不对外宣告。

| 路径 | 请求及返回边界 |
| --- | --- |
| `/v1/offline/changes` | 设备会话及 orders 能力；`protocol,cursor`，首次 cursor 为 null。最多 100 条确认变更标记，返回 event_revision、当前 order_revision、state、签名 cursor 和 has_more；不返回原始候选或成本 |
| `/v1/offline/order-chunk` | `protocol,epoch,order_id,revision,section,offset`；section 为 lines/notes，offset 为十进制字符串。每页最多 64 项、900000 字节；固定恢复 epoch 和订单版本，版本已变返回冲突要求重读；按当前归属和成本/利润能力裁剪 |
| `/v1/offline/review` | 独立授权的密码维护会话；`protocol,after`（首次 null）。最多 32 项、900000 字节的未裁定 conflict/rejected 原件、原因和基础/当前版本引用；next_after 为下一页 UUID 或 null |
| `/v1/offline/review-chunk` | 同独立授权；`protocol,operation_id,section,offset`，section 为 base/current。读取保存的不可变版本引用，每次最多 65536 原始字节的 base64，含整份 SHA256、total_bytes、next_offset；不截断完整历史 |
| `/v1/offline/resolve` | 同独立授权；必填 `protocol,request_id,operation_id,expected_revision,decision,reason`；可选强类型 payload、target_order_id、allow_duplicate。request_id 为新的稳定 UUID；同 ID 同正文返回原结果，异正文或竞争裁定拒绝 |

裁定 decision：keep_current 保留当前有效结果；apply_candidate 可携带更正后的原类型业务输入，按明确的当前版本应用；merge_into 仅将新建候选的稳定商品行追加到指定的同归属有效订单，并保留目标订单身份。含折扣的归并要求明确商品编辑，不能猜测折扣覆盖范围。同订单号疑似重复需更正/明确归并，或经授权者明确 allow_duplicate 后保留独立单。

设备/发行/节点会话及未获单独授权的管理员都不能读取或裁定。裁定授权仅在停服、owner 排他锁下用真实维护管理员密码授予既有 legacy_password 管理员，绑定账本、恢复 epoch 及用户授权 epoch；不随正式母版身份或包能力取得，不进入备份。恢复或授权 epoch 改变后必须重新授予。

C 为裁定追加透明的 `777-offline-resolution-v1` 服务端操作：origin 固定 server_resolution，记录真实裁定主体、原候选 ID、决定正文和独立 request_id；使用专门的 server-resolution stream 命名空间，不伪造设备或租约。原 conflict/rejected 状态及原始摘要不改写，设备回执通过 resolution 字段返回裁定处置和经权限裁剪的 result。

三方合并以可验证的历史订单版本及稳定 line_id 为基础。无共同基础、同一行不同修改、同一字段不同值、状态与编辑竞争、涉及折扣的并发商品变化均保全待裁定。独立普通行和不同详情字段可兼容合并，金额由主机按各行保留的价格版本重算。关联客户仅复用唯一且身份兼容的候选；不同外部订单号保留多单，外部订单号按非空去首尾空白的精确值检查疑似重复。

原候选的后继不会因人工归并而悄悄换订单或换基础；冲突/拒绝的后继保留为待审原件，后续需要逐项核对。创建时间格式、租约签发时间（允许 300 秒时钟偏差）和未来时间也重验；D 的本机可信时间高水位见下节。

## D 本机模式与业务历史

`POST /v1/offline/ready` 使用真实业务设备会话，正文仅 protocol；返回 `local_orders:777-local-orders-v1`、application、恢复 epoch、设备/用户 epoch 及当前 price_version_id。客户端必须确认 application 为 true，再核验签名租约、包身份、能力、公开目录摘要及保护时间后才开启本机正式写入；旧 Host/receive_only 继续在线模式，不伪造离线授权。

`/v1/offline/order-chunk` 的 section 增加 history，沿用固定版本、归属和财务权限校验；摘要只对应原 save_order 业务修改，不投影收件和冲突技术状态。`POST /v1/offline/diff-chunk` 使用同一 orders 授权，字段为 protocol、epoch、order_id、revision、offset；按现有修改前后业务差异分块，每次最多 65536 原始字节，返回 SHA256、total_bytes、next_offset。客户端保存加密碎片，全部完成核验后发布；无成本/利润能力者不取得对应字段。

本机命令身份与上传原件身份均稳定。连接恢复只唤醒瞬时网络退避，实际传输仍走认证 HTTPS，429 及授权失败不被绕过。每次只上传可满足依赖的有限原件；202 不是应用成功，不删除唯一原件。回执核查优先新 received，并持久分页核查 waiting/conflict/rejected；主机的明确 resolution 才结束待审状态。确认 feed 分阶段下载 lines、notes、history，完成整单后再推进 cursor，不能用半份订单覆盖本机修改。

本机查询只承诺已经按权限缓存的历史和本机正式订单；首次未登记、未下载历史、过期租约和未保护的旧备份不在离线新写入承诺内。正式界面与问题日志策略不变，细节见 [D 实施](../../verification/P08-02-3-D-local-orders.md)。
