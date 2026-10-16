# 业务与数据迁移契约（业务规则 v1）

状态：**业务规则v1已确认冻结，P01已验收归档；P02-01纯计算已实现，应用接入与业务提交/权限仍待后续任务。** 用户于2026-10-10 21:52:38（Asia/Shanghai）回复“采用推荐方案”，采纳`ed0c627d5151970e53448e92a21315ca31957142`中的D01–D06。[决策与金额示例](baseline/P01-02-decisions.md)及[确认记录](baseline/p01-02-confirmation.json)登记确认范围和证据。来源：[审计报告](audit/python-audit.md)。本文件维护唯一字段/规则定义，阶段任务书只引用。

规则标识：`rule_version=business-v1`。冻结范围为第2节的金额/输入/折扣与错误语义、第6节的价格生效和角色权限；第3至5节实体/schema/API设计仍为拟议，尚未形成已实现接口。P01-04已交付[技术参数与验收材料](baseline/P01-04-validation.md)和[numeric-v1-proposed](baseline/p01-04-numeric-profile.json)，现已按[P01确认](baseline/p01-acceptance.json)原值采纳为numeric-v1；历史候选JSON与黄金元数据保留并在批准记录映射，不重写旧证据。不得把原16例精度64当生产决策。后续变更已确认的业务语义需登记新决策并升规则版本，不能直接重写v1含义或覆盖旧单。

## 1. 源码核实的业务现状

| 类型 | 销售额公式 | 成本公式 |
| --- | --- | --- |
| 面积项目 | 高×宽×数量×销售单价×K | 高×宽×数量×成本单价 |
| 单件项目 | 数量×销售单价×K | 数量×成本单价 |
| 折扣行 | 前面当前销售小计×(折扣百分比/100−1) | 0 |

订单利润＝总销售额−总成本；综合利润率＝总利润/总销售额，不取各行利润率的平均值。当前零销售额显示0%，销售/成本/利润分别用float原值累计后格式化；行显示金额不参与总额累加。折扣按顺序叠加，折扣后新增商品不追溯打之前的折扣；90或90%表示按原价90%收款。K只作用于销售额，成本不乘K，空K默认为1，单件项目忽略高宽。

普通字段当前支持单位标记、四则运算、余数、括号、百分号、科学计数法；折扣字段只接受0至100的数字及可选尾随%。布尔量被当成数字、负输入仅提醒、运算乘积可溢出、错误行跳过后仍可导出有效部分，是现有缺陷或待决行为，不直接作为迁移正确规则。源码观察不等于用户已确认目标规则。

## 2. 已确认金额与输入规则（business-v1）

以下D01至D03和D06已获用户确认，确认原文与影响见P01-02决策文档。

| 决策 | 已确认规则 | 明确边界 |
| --- | --- | --- |
| D01 金额链 | 普通行销售额和成本分别ROUND_HALF_UP至0.01；行利润＝二者之差；总销售/成本/利润分别为行金额之和 | 负折扣金额也按ROUND_HALF_UP，半分向远离0方向舍入；金额0统一显示0.00；UI/保存/导出/汇总共用结果，不分别重算 |
| D02 数值范围 | 普通行高、宽、数量、销售单价、成本单价、K的最终解析值均≥0，允许小数数量，空K＝1 | 0是合法数值；负折扣是合法特殊行；成本高于销售产生的负利润合法；不借负数量暗中增加退单功能 |
| D03 利润率 | 普通行和订单按已结算利润/销售额计算，显示百分比ROUND_HALF_UP至1位小数 | 销售额为0时返回null并显示“—”；折扣行利润率同样为null，不保存伪造的0%；只用于展示，不反向生成金额 |
| D06 折扣和错误 | 保留顺序折扣；每次基于前面已量化的当前收入小计计算本行负金额，成本为0 | 90%是九折；0%免费、100%原价；首行折扣金额0并提醒；折扣百分比保留原精度，显示不得把不同值伪装为同一数值 |

输入保留原文并解析为十进制，禁止先经float再转Decimal。沿用普通字段的单位、运算及百分号语义；表达式最终值校验与普通行限制一致，布尔/变量/调用/非有限数/除零和超容量运算报VALIDATION。JSON的single仅接受真正的布尔值，重复名称或非法价格项阻断整份价格发布，不静默跳过或bool("false")。任何行/所用价格错误使整单不可提交、不可生成正式Excel或正式报价图；可呈现逐字段诊断及明确标为未完成的预览。空列表不可提交；含合法零值或0%折扣的订单不因零销售额冒充错误。

尺寸/数量/价格/K保留输入精度，不把单价/尺寸先压成两位。P01-04的numeric-v1-proposed建议字段0～10亿/12位小数、表达式每次除法12位ROUND_HALF_UP、中间容量10^45/60小数位、分整数对称i64上限；具体原文/树资源限制和精确运算证明见所链接profile/说明，数值参数已按P01验收采纳为numeric-v1。53例静态黄金目标已用独立有理数诊断核对，Python生产与Rust同规则的实现证明仍在P02/P06，不以诊断器通过冒充实现验收。原16例的Decimal精度64不是生产决策。历史已确认账本保留原值及旧rule_version，不因新规则重算覆盖；旧利润率与新期望分列对账。

IPC/JSON使用十进制字符串（如`"123.45"`），持久化已结算金额用有符号整数分；跨JS边界大整数用字符串避免精度丢失，尺寸/单价的精度不得粗暴压成两位。Rust十进制表示必须证明满足范围、舍入及溢出策略；使用checked操作。前端只展示服务返回的权威结果。

## 3. 实体与身份

| 实体 | 必需字段（拟议） | 一致性与历史要求 |
| --- | --- | --- |
| Product | product_id、name、unit_kind、active | 名称非主键；改名不改变旧单含义 |
| PriceVersion | price_version_id、schema_version、published_at、publisher、items、checksum | 发布后不可变；销售投影不含cost；订单绑定版本 |
| QuoteDraft | draft_id、revision、customer/order_ref/wechat、ordered_lines、price_version_id、rule_version | UI修改使计算过期；草稿不进入正式汇总 |
| Order | order_id、external_order_no、customer_id_text、wechat_text、created_at、business_date、actor_id、device_id、revision、status、request_id、rule_version、price_version_id、totals | 内部ID独立于淘宝ID、时间及用户订单号；业务日期和时区显式记录 |
| OrderLine | line_id、order_id、sequence、line_kind、product_id、product_name_snapshot、unit_kind、raw_inputs、normalized_inputs、unit_prices_snapshot、k、discount、amounts | line_kind=normal/discount；备注不伪装商品；金额快照不可被新价格重写 |
| OrderNote | note_id、order_id、revision、text、actor_id、created_at | 已确认只追加；更正追加新备注，不覆盖/删除旧备注；具体字段/schema仍拟议，引用稳定订单，不引用Excel行号 |
| Attachment | attachment_id、order_id或draft_id、relative_path、content_hash、created_at | 路径由受控根目录解析；截图不可覆盖同名文件 |
| ImportBatch | batch_id、source_hash、schema_detected、row_map、counts、totals、errors、status | 相同来源重导入幂等；源行→新ID可追踪；歧义不擅自合并 |
| AuditEvent | event_id、actor、operation、target_id、old/new_revision、time、request_id | 记录变更/作废/恢复；不泄露凭证或非必要客户资料 |

ID采用经评估的随机/排序唯一标识方案，不以“加毫秒”替代全局身份。业务订单号可能空或复用，作为外部引用，不默认唯一。请求幂等键与订单身份分离；同一请求重试只提交一次，相同键不同负载返回冲突。revision用于乐观并发，原子检查与更新在同一事务内。

## 4. 旧字段到新模型

| 旧字段/位置 | 新归属 | 迁移规则 |
| --- | --- | --- |
| 淘宝ID / 用户 | Order.customer_id_text | 保留文本及前导零，旧字段别名显式映射 |
| 订单号 / 微信号 | Order.external_order_no / wechat_text | 文本，不转数字，不作为权限主体 |
| 记录时间 | created_at原文＋解析值 | 老表无时区则按已确认部署时区解释并记假设，不猜同秒两单归属 |
| 项目名称 / 基础类型 | name_snapshot / 产品映射 | 未知名称先保留，人工建立商品映射；不要根据名称删除记录 |
| 是否单件 | unit_kind / line_kind | “是/否/折扣行”显式枚举；字符串false不能bool强转 |
| 高度/宽度/数量、原文字段 | normalized_inputs / raw_inputs | 同时保留，缺失/非法列进入错误报告 |
| 销售/成本单价、K及原文字段 | 单价快照 / k / raw_inputs | 当前目录与历史成交快照分离 |
| 折扣 / 折扣系数 / 折前销售额 | 折扣行参数与审计快照 | 兼容旧格式，验证次序和范围 |
| 销售额 / 总成本 / 利润 / 利润率 | amounts / totals | 旧值独立保留；比较校验，差异不自动“修正”真实账本 |
| 本次总计 / A4:H4 | 对账参考 | 不再导入为商品或重复计入；固定列号不可作唯一依据 |
| 备注行 / 备注工作表 | OrderNote / 文件级待核对备注 | 文件最近备注不能强行归属最后订单；保留来源 |
| 输入问题工作表 | 导入诊断 / 订单事件 | 只有时间不能唯一定位时留待人工核对 |
| 价格设定工作表 / config.json | PriceVersion / 导入证据 | 日表只有最后快照；缺失的旧价格版本不能伪造 |

支持样本：当前26列表；新增备注列；旧“用户”表头；旧价格字典与新版items；字段重排；缺摘要；真实公式与无缓存公式；同秒多单；重复文件；截断/损坏文件。未知schema只读隔离。

## 5. 业务接口与错误语义（逻辑契约）

| 操作 | 输入 | 输出/限制 |
| --- | --- | --- |
| calculate_quote | 草稿快照、价格版本、规则版本 | 权威金额、逐字段问题、calculation_revision；不能写账 |
| commit_order | 校验通过的草稿版本、request_id | order_id、revision、提交状态；幂等且服务端重验 |
| query_orders / get_order | 筛选、稳定分页游标 / order_id | 按角色过滤的DTO；不可让前端指定成本权限 |
| add_note / void_order / restore_order | order_id、expected_revision、request_id、操作内容 | 已确认权限见第6节；追加备注/作废/恢复均审计，作废/恢复须原因；新revision或明确CONFLICT/FORBIDDEN |
| publish_prices | 完整schema、expected_version、request_id | 新不可变版本；只允许授权角色 |
| import_legacy | 受控文件选择、dry_run、策略 | 检测结果、差异报告、导入批次；确认后事务提交 |
| export_report | 数据范围、格式版本、角色 | job_id与完成路径；失败不撤销已确认订单 |
| get_job / cancel_job | job_id | running/committed/completed/failed/unknown/cancel_requested；不能把取消请求等同于已停止 |

错误结构至少包含code、可读message、field_errors、request_id、retryable、commit_state；典型码VALIDATION、PRICE_STALE、CONFLICT、FORBIDDEN、NOT_FOUND、IO_UNAVAILABLE、SCHEMA_UNSUPPORTED、COMMIT_UNKNOWN。技术路径/堆栈保留在受控诊断，用户只见可操作信息；错误不可替换成正常零值。

## 6. 状态与权限

### 6.1 草稿与提交状态

草稿→校验通过→提交中→已提交；任一输入修改使旧计算过期。结果未知先查询request_id再重试。订单提交与Excel生成分开：订单成功、报表失败可单独补导出，不重复记账。作废保留原订单/金额/备注，汇总分别统计有效和作废金额，不物理删行；恢复使用revision检查与审计。

### 6.2 D04 已确认价格生效规则

新草稿绑定当时有效的已发布价格版本；计算不静默切换版本。发布新版本时，已提交订单保持原快照；旧版本草稿标为价格待更新，提交返回PRICE_STALE。用户刷新后展示销售价格差异并重新计算、确认；若升级期间再次发布新版本，提交重新校验。管理员同样不能以旧计算绕过检查；首期不增加旧价特批通道。

离线可用上次已授权取得的销售价格缓存编辑未提交草稿，明确显示离线/待校价；未成功取得已发布版本时只允许演示草稿，不把代码默认价作为正式成交价。读取价格失败不得抹成正常价格来源。正式提交需要服务可达、认证有效及版本校验通过；不自动补交离线草稿。重新连接后先校价、重新计算并确认，再提交。缓存不含成本或利润。

### 6.3 D05 已确认角色与字段权限

“自己的订单”指服务从认证会话绑定的actor_id创建的订单，不按客户/淘宝ID、设备名或客户端自报owner判断。管理员可查询全部订单；销售仅自己的订单。备注只追加，更正另加一条；管理员作废/恢复必须填写原因，销售不能作废。首期不提供业务客户端物理删除订单/账本功能。

| 操作/数据 | 管理员 | 销售 | 未认证 / 会话无效 |
| --- | --- | --- | --- |
| 商品与有效价格查询 | 完整价格及成本 | 销售价格、K、商品单位；不返回成本 | 拒绝 |
| 报价计算、创建/提交订单 | 允许，actor由会话确定 | 允许，actor由会话确定；结果不返回成本/利润/利润率 | 拒绝服务业务请求 |
| 查询/查看订单及附件 | 全部；完整财务DTO | 仅本人；销售DTO及本人报价附件 | 拒绝 |
| 追加备注 | 全部订单 | 仅本人订单 | 拒绝 |
| 编辑/删除已保存备注 | 拒绝，追加更正保留历史 | 拒绝，追加更正保留历史 | 拒绝 |
| 作废/恢复订单 | 允许，原因＋revision＋审计 | 拒绝 | 拒绝 |
| 物理删除订单/账本 | 业务接口不提供 | 业务接口不提供 | 业务接口不提供 |
| 发布价格、导入旧账、备份/恢复 | 允许，受控入口及审计 | 拒绝 | 拒绝 |
| Excel/报价图片导出 | 授权范围内完整报表 | 仅本人销售数据或本人草稿；不含成本/利润/利润率/成本快照 | 拒绝服务业务请求 |
| 直接调用API/IPC、绕过隐藏控件 | 执行相同角色、字段、范围、版本检查 | 执行相同角色、字段、范围、版本检查 | 拒绝 |

服务从认证会话确定actor，不能相信客户端role/actor字段。查询、按ID读取、附件、导出和后台任务状态都检查资源归属，不能先取完整财务对象再在前端删字段；非本人订单ID统一按未找到处理，阻止枚举。销售版共享JSON/本地缓存/DTO/Excel/截图都不得包含成本快照；前端隐藏、Tk页面和Tauri capabilities不能代替局域网业务鉴权。管理员恢复功能不是绕开数据备份恢复流程。

以上为已确认的业务授权规则，当前Python没有认证服务，尚不能执行直接接口权限测试。业务确认不等于授权实现已经通过；P05和P07的验收必须覆盖：未认证请求、伪造actor/role、查询他人order_id、本人/他人备注、销售作废、导出/附件/任务越权及嵌套成本字段泄漏。

### 6.4 已确认的开发版与母子版交付方式（待实现）

用户于2026-10-14 23:12–23:14（Asia/Shanghai）确认：开发版本保留连接、登录及调试能力，设置好后在封包时确定母版或子版；正式使用者直接进入获分配的业务界面，不填写连接参数或账号密码。本节是交付与认证交互的新要求，不改变business-v1金额规则和6.3的权限/订单归属。需求确认时源码仍为显式登录。现P07-02已按[实现契约](verification/P07-02-auth-contract.md)交付设备身份/自动入口，待Windows/用户验收；两种实际安装包仍待P07-04。

| 交付类型 | 入口与可见能力 | 配置与授权 |
| --- | --- | --- |
| 开发版 | 保留服务地址、证书/pin、账号登录、调试及母子界面验证；验证角色仍须服务端授权 | 使用独立开发profile和隔离服务；不得把开发账号、测试数据或凭证带入正式包 |
| 正式母版 | 已部署授权后直接进入母版业务；保留价格、利润、业务目录及备份管理 | 打包锁定manager类型；服务端授予admin权限，不提供运行时母子切换或技术登录页 |
| 正式子版 | 已部署授权后直接进入报价页；仅本人销售业务 | 打包锁定sales类型；服务端授予sales权限，自动继承母版发布的价格和导出/图片目录，目录显性只读 |

1. 打包配置包含版本类型、受信服务地址和公开证书信任信息；由开发/部署人员选择并校验，使用者无需设置。业务导出/图片目录继续由母版发布，不固化进子版安装包，不恢复旧E盘业务根隐性fallback。
2. 安装包类型只限制产品能力，不能自己颁发权限。部署人员在受控维护入口预先分配主体/角色并准备一次性、限时、限角色的登记材料；目标机首次启动自动登记取得独立凭证。材料缺失、已用、过期或角色不匹配时不得注册成功，也不得弹出技术配置/登录页；显示简洁的“尚未配置，请联系管理员”。登记材料单独安全交付，不把可复用管理员密码、TLS私钥或全员通用业务凭证写入公共安装包、仓库、前端或日志。
3. 凭证保存在Windows原生受保护存储，绑定本机Windows用户profile、服务及服务端登记记录；原生层自动取得/续期会话，服务端可撤销设备并使其现有会话失效。DPAPI不是不可克隆硬件证明，不把设备名、IP或客户端自报role当授权。开发能力不因运行时参数、环境变量或localStorage而在正式包中开启。
4. device_id只用于登记和撤销；订单归属仍为服务端绑定的稳定actor_id。同一人员多台设备由部署人员明确绑定同一主体，不把所有子版共用为一个账号，也不因重装/换机自动改写历史归属。换人、换机或角色调整经受控重新授权，旧授权撤销；更换安装包本身不授予新角色。
5. 正式入口启动时可显示简短连接状态，正常恢复后直接进入对应业务；服务不可达允许保留草稿/重试和正常关闭，不自动成交。凭证失效或证书变化进入待维护状态，恢复由部署人员处理，不向使用者要求填写PEM/pin或密码。未知提交继续绑定原服务/actor/request_id，恢复会话后先核查，不能跨身份重放或另建订单。
6. 服务端身份库扩展必须登记协议/schema版本、旧账号与设备映射、迁移及完整备份恢复策略；恢复后不得复活已撤销凭证或旧会话。开发登录及获授权旧客户端的兼容范围要明确，正式包移除登录UI不代表删除现有服务鉴权。旧服务不支持自动登记/续期时给出版本不兼容状态，不静默降级为共享密码登录。

实施顺序与验收由[P07任务书](now/P07-tauri-desktop.md)负责，真实设备部署与人员映射由[P08任务书](new/P08-cutover.md)负责。新增接口名称、构建命令和schema版本在实现时确定，本轮不虚构已可执行的封包命令。

## 7. 跨语言黄金样本要求

当前共用材料为[P01-04静态黄金集](baseline/p01-04-golden.json)，53例；[验证入口/格式候选/性能方案/Windows清单](baseline/P01-04-validation.md)。每例明确business-v1或numeric-v1-proposed的期望依据；参数已按[P01确认](baseline/p01-acceptance.json)原值采纳，历史numeric-v1-proposed元数据对应numeric-v1；后续不得重写原黄金期望。P02/P06读取同一JSON，不复制期望值。

正确样本覆盖面积、单件、K空值默认1、零成本、0/100%折扣、连续折扣、折扣后加商品、中文单位、百分号及表达式。边界覆盖分位舍入、最大金额、除零、非法bool、负数政策、重复商品名和陈旧价格。每例包含input、price_snapshot、rule_version、期望行金额/总额/错误码；精确比较，不用浮点近似。

审计中复现的错误另列“旧缺陷→确认后的新期望”，不作为Rust必须复现的黄金正确结果。历史导入按订单数/明细数/收入/成本/利润/备注关联五类指标核对，歧义名单必须清零或经业务确认隔离并注明未迁移范围。

## 8. P02-01已实现的Python领域接口

实现入口为[quote_core](../quote_core/__init__.py)，使用business-v1与已采纳的numeric-v1，生产模块只依赖标准库。它不从文件读取仓库profile、黄金、配置或Excel；P02-02配置入口只接收调用者已取得的JSON文本/字节，见第9节。[批准记录](baseline/p01-acceptance.json)与测试按Git已提交LF字节指纹（工作区仅CRLF转LF）核对参数。历史候选标识numeric-v1-proposed仅是保留的证据别名，不是生产接口默认版本。

| 已实现类型/入口 | 输入与结果 | 边界 |
| --- | --- | --- |
| NormalLine / DiscountLine | 普通行product_id/q/h/w原文，或明确的折扣percent原文；名称仅展示 | 普通/折扣由类型显式区分；P02-02补充固定且不可传入改写的line_kind=normal/discount，dataclasses.asdict包含该标签；不凭展示名称判断折扣 |
| PriceItem / PriceSnapshot | 商品键、sale/cost/k原文、single布尔；独立的price_version_id和不可变items元组 | 计算只逐字段校验用到的价格；整份配置候选由P02-02全量校验，见第9节；single字符串false拒绝，空价格拒绝，空K默认1 |
| QuoteSnapshot | 不可变有序lines、绑定price_version_id、rule_version和numeric_profile | 列表入参复制为元组；不接受可变字段/控件，布尔或浮点等错误原文由计算报VALIDATION；空订单/超过10000行拒绝 |
| calculate_quote(snapshot, prices) | QuoteResult；逐行整数分、原输入/价格和规范十进制串、折前整数分、订单总额、错误/提醒 | 快照版本须相同；不加载/刷新价格、不写账，不能据此证明已发布价格或正式提交授权 |
| Amounts | income_cents/cost_cents整数，profit_cents派生；margin_tenths为百分比十分位或null | display仅从整数分生成文本，cents_payload把分整数转字符串跨JS边界；不从UI文本回读金额 |
| capture_legacy_quote(rows, config, price_version_id=...) | 主线程读取两版当前行与已获取价格映射一次，返回QuoteSnapshot/PriceSnapshot | 单件不读高宽，自定义折扣保留全部精度；不读res/status/summary、不保存Tk变量；尚未接入两版窗口 |

QuoteResult携带business-v1/numeric-v1/price_version_id。VALIDATION时lines和totals均为null，issues含reason/field及从1开始的行号；成功才有完整金额。首行或零小计折扣返回零并附DISCOUNT_ZERO_SUBTOTAL提醒，折扣行及零收入利润率为null。P02-03已实现本地草稿revision、输入/价格状态失效与正式输出门槛，见第10节；原窗口及真实输出入口统一接入仍属于P02-04。领域价格包含成本，仅用于受信任计算链，销售DTO及服务鉴权由P05落实，不能把完整领域对象直接当销售投影。

母子原calculate尚未切换，原summary回读/部分导出缺陷也未据此关闭。P02-04接回两端后才能验收UI、保存/Excel/图片都使用同一权威结果；历史账本不重算覆盖。

## 9. P02-02已实现的配置候选校验

[configuration.py](../quote_core/configuration.py)复用同一parse_number/parse_percent，数值规则仍为numeric-v1；没有另一套JSON金额算法。JSON数字通过parse_int/parse_float接收原始token，之后与字符串使用同一十进制表达式解析；不先转换为float。旧JSON数字可兼容，后续IPC金融字段仍输出十进制字符串。

| 入口/类型 | 已实现行为 | 边界 |
| --- | --- | --- |
| parse_price_config(source, price_version_id=..., legacy_single_names=...) | UTF-8字节或文本，允许UTF-8 BOM；成功返回PriceConfigResult(ok, config)，配置含不可变prices、source_schema、export_dir、可选screenshot_dir和original_json | 失败status=VALIDATION且config=null，issues定位json/items[0].sale等字段；不是文件加载、价格发布或认证接口 |
| refresh_price_config(previous, source, ...) | 全部校验成功后返回新active；失败active保留previous同一对象，applied=false；首次无有效配置时保持null | previous须来自此前成功校验；保留原文、原价格版本及目录，不写文件、不以硬编码默认价格替代，也不授权陈旧/离线价格成交 |
| ValidatedPriceConfig / PriceConfigResult / PriceConfigRefresh | frozen领域记录及不可变PriceSnapshot；金融原文保留，空K保留原文并按1计算 | price_version_id由调用者显式传入；该标签不证明已发布，版本分配/鉴权在P05，陈旧状态及提交阻断在P02-03 |

支持的文件形状：

- 新格式顶层只接受items及可选export_dir/screenshot_dir；items必须是非空数组，成员只接受name/sale/cost/k/single/qty_only。sale和cost必填且不可空；k缺失或空白为1，null及bool不是空K。single/qty_only只接受真正的布尔值；两者同存必须一致，均缺失时按现有读取器兼容为false。
- 旧格式为商品名→恰好三个sale/cost/k值的数组及可选export_dir/screenshot_dir；未知/多余尾项和非价格记录拒绝。旧格式没有单件标志，调用者必须显式传入各端现有默认商品中的单件名称集合，可以为空；不凭常见名称猜测，也不使用一套隐藏名单。P02-04接入时从原有default_items取得该集合。
- 商品名必须是真正的文本，trim后非空且唯一；重复原始JSON键在解码时直接拒绝，重复trim名称也拒绝整份。保留名称“折扣”不能作为价格商品，折扣由独立行类型表达。items数组内名为items/export_dir的普通商品没有元数据歧义，允许；旧顶层export_dir必须是目录文本，不能兼作商品数组。
- 任一价格项、未知字段、目录文本类型或其他schema错误均拒绝整份候选，不跳过坏项或部分生效。目录字段仅保留原文/缺失null，核心不探测目录；P02-04按共享配置根解析/发布并接回实际writer，文件可用性/连接设置分离/锁事务仍由后续任务处理。

当前JSON解码保护为1MiB UTF-8、嵌套深度32、最多10000商品、商品名256字符、目录文本32767字符；数字原文沿用numeric-v1的256字符限制。名称/目录拒绝控制字符及非法Unicode。上述是当前配置载入容量保护，不改business-v1金额范围或舍入，也不冒充服务协议/最终目录设置已实现。未知扩展拒绝，原配置保留待处理；旧单不重算。

整份候选校验与计算所用价格校验范围不同：损坏的未用商品也不能进入新有效配置；已冻结的PriceSnapshot计算时仍只校验引用商品，不因未引用空价无故阻断报价。母子配置加载已在P02-04切换到该校验，首次坏配置无默认fallback，失败保留有效对象；A18应用适配已完成辅助回归，Windows交互待04验收。

## 10. P02-03已实现的草稿状态与正式输出门槛

[session.py](../quote_core/session.py)是无UI/I/O依赖的本地草稿控制器；复用calculate_quote及business-v1/numeric-v1，不再实现一套金额算法。QuoteSession的更新/应用完成/确认/输出方法必须由所属UI线程串行调用；计算工作线程只接收不可变CalculationRequest并调用run_calculation。

| 类型/方法 | 已实现行为 | 调用约定 |
| --- | --- | --- |
| DraftDetails | 冻结customer/order_ref/wechat文本，保留前导零；数字或控件拒绝 | 这些是草稿展示/业务引用，不是认证身份或最终订单schema；更新同样使计算失效 |
| QuoteSession(snapshot, prices, ...) / state | 返回冻结QuoteState：revision、calculation_revision、状态、输入/价格/身份、结果、输入问题、价格来源/最新版本和确认要求 | 初始价格来源为unverified，无默认成交许可；state.status的valid仅表示数值有效，不表示正式输出或提交已授权 |
| update_inputs / update_details / invalidate_inputs | 编辑使revision递增并清空result/calculation_revision；invalidate_inputs先清空旧快照，可带原字段/从1开始行号的VALIDATION问题 | UI编辑trace/增删/排序/折扣切换应立即失效，完整快照取得后再update_inputs；失败捕获不可继续使用旧快照 |
| observe_price_source(status, latest_price_version_id=...) | current/unavailable/unverified/invalid严格枚举；事实改变时递增revision并清空结果，完全相同的观察无操作 | 仅记录调用者提供的当前载入/服务状态及最新版本，不读取文件、探测网络、刷新价格或证明发布身份 |
| refresh_prices(prices) | 显式替换完整冻结价格，并把已有草稿绑定该版本；失效计算，已有价格被刷新时要求重新确认 | 新版本观察不会自动调用此方法；即使版本文字相同，显式内容替换也需重算。失败候选不能传入，必须保留原有效价格并observe invalid/unavailable |
| begin_calculation / run_calculation / apply_calculation | 请求冻结本草稿owner、revision、输入/价格/身份；纯计算返回完成；仅本owner、当前revision及原快照相同才应用 | 旧/跨草稿完成返回false，不覆盖当前结果或错误；owner是进程内不透明对象，非持久身份或IPC字段；完成只在受信任内部链传递 |
| calculate() | 同步请求→计算→应用，返回当前冻结state | 允许用缓存价计算草稿预览，但正式输出仍独立检查来源/版本/确认；错误整单lines/totals=null |
| confirm_prices(expected_revision=...) | 仅当前revision、计算完整且来源/版本有效时接受；解除该次价格刷新确认要求 | 04先展示旧/新价格差异，再重算并确认；旧确认、未重算确认、升级再次变化均不接受。已确认价格后的普通输入编辑需重算，无需重复确认同一价格 |
| prepare_output(kind) | excel/quote_image/screenshot返回冻结OutputDecision；允许时附OutputPayload，失败时payload=null及结构化问题 | 所有三种正式输出共用门槛，不提供草稿图片旁路；历史decision不是许可令牌，不应缓存后直接写 |
| dispatch_output(kind, writer) | 调用时重新检查当前状态；阻断抛OutputBlocked并保留decision，writer零调用；成功writer仅拿冻结OutputPayload | 先结束路径选择/对话框，再同步dispatch；writer不可yield、进入Tk嵌套事件循环或修改草稿。异常原样传播，不猜提交结果或自动重试 |

输入/身份/价格及来源变化后原数值结果被清空；即使改回同一原文/版本，旧revision结果也不能复活。QuoteState.status为uncalculated/stale/valid/invalid；实际输出限制由OutputDecision体现：字段/计算/配置错误或待确认为VALIDATION，当前缓存版本落后最新版本为PRICE_STALE，读取不可用为IO_UNAVAILABLE，已算过但失效的结果为CALCULATION_STALE，首次未算为VALIDATION/CALCULATION_REQUIRED。问题携带reason/field和可用的输入行号，错误不会替成正常零值。

OutputPayload冻结revision、输入、价格、客户/订单/微信文本和同一个QuoteResult；不从summary或其他结果控件回读。输出前核对业务/数值/价格版本、完整行及对应原行、销售/成本行和与总额恒等。合法零收入、0%免费、首行折扣提醒及亏损不因金额为0/负而阻断。此门槛不重新舍入金额、不生成Excel/图片本身，也不处理公式文本/文件格式、并发覆盖或持久化结果未知。

本接口是当前Python内部链，不是已冻结服务协议。调用者的current与latest_price_version_id不等于认证/已发布价证明，完整领域载荷含成本，不能直接作为销售DTO/IPC响应。P05在服务事务内重验认证、归属、价格版本及revision；P03负责真实文件提交/恢复，P04负责后台输出任务。P02-04现已接回两版编辑/载入/价格差异确认/输出路径，当前类方法辅助检查错误/陈旧零写入；A04/P02-04已按用户明确通过确认验收，见[阶段确认](verification/P02-acceptance.json)；P03文件事务另验。

## 11. P02-04已实现的窗口与输出适配

[quote_app/integration.py](../quote_app/integration.py)供两版PriceCalculator继承，Tk/文件/Excel/Pillow依赖仅在适配边界。QuoteSession和核心数值规则没有修改；Rust迁移复用同一黄金/配置/状态规则，Tk变量trace、沙箱、格式投影不是跨语言协议。

- initialize_quote_state在布局/价格加载前建立无有效价控制器；真实变量trace及行增删/清空立即invalidate_inputs，结果显示为待计算，不保留局部金额。冻结输入只在计算所属线程捕获；折扣行的discount与discount_choice为同一输入变量，结果渲染不得回写选择或截短自定义百分比。
- 文件读入上限1MiB+1后parse_price_config整份验证。成功来源current与local-sha256字节版本仅代表当前路径读取/本地schema成功；服务发布认证及文件读取与提交间的竞态仍待P05/P03。失败观察invalid/unavailable，保留旧有效对象供草稿计算，不默认成交或关闭自动覆盖。未保存的编辑价格版本使用editor-sha256，正式门槛不允许输出。
- 观察新版不刷新冻结价；刷新按钮/显式有效保存才refresh_prices，已有价格要求重算/确认，包括相同文件显式刷新。差异可见字段按现有角色投影，销售不展示成本。确认对话框结束后重新观察来源，以对话前revision确认，期间编辑/升级不能得到许可。
- 正式Excel先观察当前来源/编辑状态再dispatch；writer只读OutputPayload中的金额和身份。截图after_idle后再次门槛，选页/绘制事件在writer之前，worker不进入Tk嵌套事件循环；不存在错误订单草稿截图旁路。保存异常不自动重试；文件已保存后的列表异常单独提示已保存。
- [projection.py](../quote_app/projection.py)保留原26列，金额采用两位十进制文本避免Excel数值单元格15位精度无法覆盖i64分；折扣/利润率为文本或“—”，身份原文保留。扩展“行类型”列记录normal/discount/order_total，追加到空的新列，不覆盖已有备注。新日汇总按显式类型纳入新正常/折扣行，Decimal求和后整数分结算，旧明细不重写；无标签历史歧义仍待P03，旧查看/备注/删除还需按类型升级。价格快照首行登记本地版本/规则/profile；完整财务载荷/旧Excel含成本，仍不是销售授权DTO。

P01诊断使用[source-location.json](baseline/source-location.json)及原manifest验证[不可变原版源码](baseline/original/README.md)，不会拿已改动入口伪造原行为。当前Windows检查独立使用tools/p02_gui_check.py。辅助119项、两端53例和核心孤立标准库检查见[04证据](verification/P02-04-checks.json)；真实Windows截图/交互、SMB/部署及后续文件安全不提前宣称通过。

### P02-04目录继承与关闭修复

[目录适配](../quote_app/storage.py)纯词法解析共享配置的export_dir/screenshot_dir；缺失/空串分别表示配置父目录下利润表/截图，不把本机E盘硬编码补进业务目录。母版保存根内位置为相对路径，根外Windows位置必须UNC；销售拒绝本机盘符与相对盘符，relative不能越过配置根。启动、刷新列表/计算/输出前自动观察并采用新目录，价格版本SHA变化仍须显式价格刷新/重算/确认。显示路径与已采用路径分离，未保存文本不能重定向writer；销售无保存能力、界面全readonly。截图根相同，销售保留按天子目录。配置入口既有E/UNC连接地址在界面可见，本机连接配置分离仍在P03。

当前纯schema的ValidatedPriceConfig末尾兼容新增screenshot_dir=null，旧四位置参数构造保持；其文本类型/UTF-8/控制字符/32767容量与export_dir一致，未知字段仍拒绝整份。旧字典顶层screenshot_dir为目录元数据，items数组内同名商品仍是商品。该扩展不改business-v1/numeric-v1及53例。

母版计算页增加正式Excel按钮，母版摘要仅扫描已识别表头前区域，避免成本被表头覆盖；完整历史/未知schema继续由P03定义。窗口拥有延迟刷新/截图任务ID，关闭取消；Windows工具捕获callback exception及bgerror，原漏报记录保留在[回传证据](verification/P02-04-windows-evidence.json)。[130项辅助检查](verification/P02-04-directory-checks.json)不替代Windows共享窗口/真实截图/SMB验收；04/P02现已按用户明确确认收尾归档，见[验收](verification/P02-acceptance.json)，原回传/辅助报告不重写。


## P03-01 过渡文件事务

当前Python文件层为[quote_files](../quote_files/transactions.py)，窗口文件编辑为[共享适配](../quote_app/file_edits.py)。协议`777-file-v1`遵循完整原生锁内读取最新内容、版本/哈希检查、校验后临时文件、写前副本、替换及回读；未知提交先查请求而不是新建单。详细状态、恢复与使用限制见[文件协议](verification/P03-01-file-protocol.md)。这不是服务认证或已冻结Rust IPC协议。

Excel保留原26列与normal/discount/order_total行类型，新单额外列为订单ID、明细ID、订单版本、请求ID、记录状态。身份UUID、订单初始版本1，新备注/作废/恢复令整单版本加1，文件全局版本在隐藏`_写入事务`回执中递增；明细ID不使用用户、时间或UI行号。作废保留金额和原行，active/void决定有效日汇总。重复同一计算导出复用request_id；主动重新计算得到新的计算revision及写入请求。旧未识别记录不补猜身份、不改原金额。

备注按稳定order_id追加，独立订单备注记录request_id及文本，并在该单总计的备注列追加文本。P03-04已补订单备注浏览、原因确认和作废恢复UI，具体见下节；完整历史转换和子版备注归属认证留P05/P08。销售仍不能直接接收安全保证：隐藏列/工作表不是保密；现有共享Excel/JSON可能含成本，A05持续开放。

配置整份校验后按读取版本CAS保存，JSON业务schema不加请求字段；配置效应由内容SHA和旁路日志核查。恢复副本在`.777-recovery`，与正式主机独立备份分开。所有旧写端需退出协作写入；非协作外部Excel仅作关闭写端后的查看，不保证任意外部编辑并发安全。P03-01辅助证据不等于真实Windows/SMB验收。

## P03-02 已实现的格式读取契约

完整定义及兼容矩阵见[工作簿契约](verification/P03-02-format-contract.md)，证据见[辅助检查](verification/P03-02-checks.json)。规范26列、行类型、5列身份在`quote_files/schema.py`单一定义，识别完整字段、别名和重排；两端读取、追加、订单操作及金融样式按列映射。未知字段/身份残缺不猜测；未知附表/扩展和公式只读保留；模板禁止清空已有数据。

读取返回`ok/error/unsupported`，仅ok有权威整数分总额；失败不返回正常零。摘要只读表头前的标签；无摘要按有效明细核算，有摘要必须完整且与明细一致，正常零仍可读取。公式只读已有缓存且报告时效未知，无缓存或不一致明确失败；不执行公式、不覆盖原件。新身份、用户字段及原始表达式以显式文本保存。

历史分组只有稳定订单ID或已核对的明确导出边界才可靠；同客户同秒的订单号差异不合并，归属歧义报告并保留明细/文件总额，不分配持久ID。UI文件列表给出读取状态；合法零计文件数，部分统算报告排除数量，全部失败显示无可用金额。上述类型、问题码和字段映射可供P05/P06复用，但历史转换、服务授权、Rust IPC及完整迁移尚未实现。P03-01已按[用户确认](verification/P03-01-acceptance.json)验收通过；P03-02的21项格式检查及母子Tk联测已在Windows通过，见[本机证据](verification/P03-02-windows-evidence.json)。

## P03-03 已实现的设置与价格归属

详细字段和使用流程见[设置契约](verification/P03-03-storage-contract.md)。当前角色本机设置为777-local-v1，保存显式data_root和管理端backup_dir；共享目录777-shared-v1单独保存price_file/export_dir/screenshot_dir。价格保存只发布items，兼容读取旧格式；目录不再写入价格文件，不因改目录分配新价格字节版本。首次连接显式选择，旧根不是启动fallback；子版只改连接，不能改发布的输出位置。

每个新增稳定订单在同一事务追加订单价格快照，含订单/请求、价格/规则/数值版本和全部价格原文；历史快照及原价格表保留，同请求回放不重复。PNG唯一目标也沿用暂存校验/未知查询。设置恢复、来源状态、冻结价格和附表关系供P05/P06复用；用户E盘根隐藏独立备份/ACL和服务授权仍未实施，不把当前共享文件当安全的销售投影。


## P03-04 已实现的订单历史与恢复接口

[订单契约](verification/P03-04-order-contract.md)及[237项辅助证据](verification/P03-04-checks.json)登记按稳定order_id浏览备注/操作记录、追加更正、原因必填和确认目标固定。active→void→active保留原行/金额/备注/价格/输入记录，恢复不复制订单、不重复计入；新状态操作回执带previous_state/state/reason/order_revision，旧原因不补造。未知操作拒绝、同请求先回执、旧哈希/版本冲突拒写；保存后刷新失败和提交未知分别提示，未知先查request_id。

输入问题兼容原六列，新导出在同一事务加订单ID/请求ID，旧行不推断归属；关联表有匹配订单和对应操作回执后才可追加，孤立关联、重复备注请求拒写。订单投影与修改位于独立quote_files.orders，Tk只负责选择/确认/显示，为P05/P06迁移提供行为契约；这不是认证服务API。子版编辑继续拒绝，独立隐藏备份与完整历史转换按后续阶段实施。04的[Windows本机22项/母子Tk联测](verification/P03-04-windows-evidence.json)已通过，21项实现指纹匹配02b62f0；具备收尾条件，已通过检查无需重跑，用户验收另行登记。


## P04-01 已实现的后台任务边界

[P04-01契约](verification/P04-01-background-contract.md)登记主线程输入快照、后台无Tk文件控制器、任务代号/连接代次/输入revision交付以及有界读取/串行写通道。排队返回不是保存成功，终态以P03事务回执为准；写入使用冻结报价，后续输入编辑不改变在途请求。取消和超时停止旧读取呈现，不承诺原生I/O已终止；读关闭拒绝迟到回写，写关闭保持事件循环直到原提交状态交付。备注/原因仅成功清除，未知请求继续核查原ID。

普通视图数据与队列事件供后续服务/Rust/Tauri任务适配复用，不引入新的财务规则或认证协议。解析复用/缓存、完整分页/附件范围和性能对照按P04-02/03/04实施；01的[Windows本机24/24及实际母子Tk联测7项](verification/P04-01-windows-evidence-03.json)已通过，24项LF实现指纹匹配cbaf87e。诊断清理等待所属读线程退出，产品读关闭仍不等待原生I/O；导出控件实际点击产生新任务、按所属窗口等待，备注/作废恢复及读关闭/写关闭交付均通过。后台24项/完整261项辅助及前两次失败原值保留。[01已验收收尾](verification/P04-01-acceptance.json)，本次检查无需重跑；短会话125ms心跳不是P04-04规模性能验收。

## P04-02 已实现的只读模型与索引

[P04-02契约](verification/P04-02-incremental-contract.md)登记工作簿一次解码/源Sheet一次遍历的脱离句柄快照、共享摘要/身份/历史/母子视图以及摘要与完整视图的双层有界缓存。元数据不可信时回读核查，读取前后变更丢弃重试；写前后只失效实际目标，目录切换清空，外部改单和删除同步撤销旧租约。目录金额以变动文件差额更新，失败/不支持分开，不变成零金额成功。缓存是可丢弃派生数据，正式写始终通过原完整事务/哈希CAS/回执。

新增22项与完整283项辅助通过，冷热/改单/删除计数与20/40行XML计数另存；[Windows本机22/22及实际母子Tk联测11项通过](verification/P04-02-windows-evidence-01.json)，30项LF指纹匹配fe0c276。4文件冷读4次、暖刷新0次且源读取次数/字节数不增加，外部改单一次解码、删除零解码、实际备注写入仅重读目标；关闭及清理正常，02具备收尾条件，本次无需重跑。缓存计数不含事务/CAS必需读取，短会话67个心跳样本/最大110ms仅作诊断。母版300行限制/完整分页与同设备规模性能分别保留P04-03/04，不在02冒充完成。

[P04-02已按用户指令验收收尾](verification/P04-02-acceptance.json)，P04-03完整分页/附件范围获启动授权，继续唯一stage/p04-performance；本次不重复实测，不改历史报告。

## P04-03 已实现的分页和报价图片

[P04-03契约](verification/P04-03-pagination-contract.md)登记完整原行号视图、200行分页/文本及订单筛选、有限位置保存与外部变更后稳定身份定位。分页索引只用于显示，原整数分金额/Excel全单输出及稳定订单ID/revision/哈希CAS不变；销售搜索只基于可显示字段。

窗口截图仅取当前可见应用窗口，Windows用HWND避免逻辑桌面坐标，遮挡可能影响且界面明确提示，截取期间revision变化则拒绝保存。完整报价图只从冻结OutputPayload投影并逐页渲染，与Tk/屏幕/筛选无关；销售字段不含成本利润，每张标全单金额及完整明细范围。独占UUID目录/已验证PNG/最终complete清单与部分失败保留，沿用原事务/回执；草稿revision不是已持久化服务订单身份，P05/P07另做附件归属和接口鉴权。

23项新增/306项辅助通过；[第二次Windows本机23/23及实际母子Tk联测16项通过](verification/P04-03-windows-evidence-02.json)，37项LF指纹匹配3c614c7，两端10000明细全页可达（母版含表头/汇总等共51页、子版50页），筛选/跳转/文件返回及后段备注保留选择和金额。真实报价图母版42条/2张、子版1条/1张全部覆盖；10000条图片布局由本机单元检查验证。无回调错误，关闭、所属线程退出与临时清理正常。03已按[用户接续指令验收收尾](verification/P04-03-acceptance.json)、无需重跑，04执行中。金额核心、黄金和历史原报告保持。

P04-03首次Windows回传的报价清单诊断读取按默认GBK出错，实际GUI未开始；[原证据](verification/P04-03-windows-evidence-01.json)保留。诊断/测试6处改为显式UTF-8并覆盖GBK默认，见[修复检查](verification/P04-03-encoding-checks.json)；清单发布协议、应用/金额及旧报告不变，第二次复查已通过，原值另存[新报告](verification/P04-03-windows-report-02.json)。

当前设备微软雅黑、Tk缩放1.3339898243886428、1180×840像素HWND截图有合成标记且未观察到遮挡颜色，完整报价图遮挡前后像素一致；窗口截图只证明本机当前配置，不承诺其他后端消除遮挡，其他DPI/多显示器未实测。440个刻意延迟I/O的短会话心跳样本、最大563ms保留，缺少健康环境多轮p95及同设备规模/SMB对照，不登记P04-04性能通过；563ms留04定位核对，冻结响应门槛不变。

## P04-04 已交付的性能采样边界

[P04-04契约](verification/P04-04-performance-contract.md)及工具按P01 performance-v1执行：三档9种工作负载各5轮、同存储位置内相同源字节/设备/插桩，50ms实际Tk心跳按刷新/查看/翻页/筛选分段；p95≤100ms、最大≤500ms，全部原始间隔保留。输入准备/哈希/结果验证在阶段外，短操作的至少1.1秒观察时段显式记录；新进程首读不是物理冷盘，Python分配峰值不是RSS或既有缓存总占用。

[全档辅助计数](verification/P04-04-read-profile.json)验证当前45个进程的金额/明细完整与冷每文件一次/暖0解码；原版小档10个进程仅作同数据对照，成本缺陷不改。新增17项及完整323项辅助回归见[最终检查](verification/P04-04-checks.json)，Windows/UNC阶段性能待回传；原563ms无阶段归因且保持原值。仅显式UNC根下独占临时合成子目录被创建/采样/清理，不读写现有生产账本。金融、价格、原事务/CAS/回执及业务源码未修改，旧生命周期/写入证据沿用；此工具不成为Rust或服务接口，P04留now，P05未启动。

首次[Windows/UNC报告](verification/P04-04-windows-evidence-01.json)的41项LF指纹匹配b84d774，17项本机检查通过；22个窗口进程因诊断页面匹配遗漏标签空格在采样前退出，无性能数据，输入未改且临时清理正常。诊断已直接选择既有excel_page，实际标签配置纳入预演、异常链/完整stderr保留；请求矩阵与全部轮次实际完成分开登记。[20项/完整326项修复辅助检查](verification/P04-04-startup-checks.json)通过，原报告与全档后台样本保持，业务/金额/事务代码未改。待第二次Windows/UNC采样，冻结门槛及原563ms不变，04和整阶段不收尾，P05未启动。

第二次[Windows/UNC回传](verification/P04-04-windows-evidence-02.json)20项检查通过，母版/原版80个进程及340个阶段完成，但6个子版进程超时，239个当前阶段样本不足、17个样本充足阶段p95超限。修复后台列表交付对角色的保护：母版更新整数分统算，子版没有该组控件，只呈现销售列表，不添加成本利润显示。诊断在空目录中完成原300ms启动回调再启用合成输入；短阶段实际采够20次心跳，所有长间隔保留，交付失败及时报告阶段/原因，超时保存阶段日志。[23项/329项辅助检查](verification/P04-04-sampling-checks.json)通过；金额/价格/事务/解析/索引协议及旧报告保持，待第三次实机复查，原100/500ms门槛不变，P04留now，P05未启动。

第三次[Windows/UNC证据](verification/P04-04-windows-evidence-03.json)及[原报告](verification/P04-04-windows-report-03.json)匹配2cd9887的41项指纹/23个测试ID，本机23项通过，110个进程全部测量完成，无窗口超时/回调错误。两位置当前9档各5轮及原版小档各5轮完成，金额/全部明细、冷每文件一次/暖0、输入未改及清理通过。450个当前阶段中390个心跳通过、60个p95超限，零样本不足；本机最大283.7558ms、UNC最大255.6336ms。剩余失败集中在1000/10000行首读、10000行查看及本机部分母版翻页；不是源数据或读取次数失败，也不能据最大值低于500ms登记通过。

Windows应用背景I/O初始化将进程解释器切换间隔设为min(原值,1ms)，保留已有更短设置；配对诊断在原/新版窗口构造前应用同一策略并记录实际值。目标是改善后台CPU解析时主线程的调度机会，报告本身不能证明GIL是根因，内部长调用也不受该间隔硬性保证；这是待实机验证的优化。可能增加调度开销，耗时/分配指标仍按原插桩记录；非Windows辅助环境不改变设置，未新增产品跨平台验收。

分页仅在表头/控件改变时配置列，翻页保留用户列宽；每页最多200行通过一次Tcl apply/foreach插入，行ID和值均为嵌套列表参数，不拼接数据为脚本，不重入update事件循环、不改原行号映射/选择恢复/金额/订单身份。中文、多行、括号/引号/美元符号及脚本样式内容按数据保留。金融/价格/写入/CAS/回执/解析和缓存预算保持。[26项/完整332项辅助检查](verification/P04-04-latency-checks.json)通过，但实际Tk/Windows吞吐和响应仍需第四次采样；不虚构改进比例，不重写旧报告或原563ms。P04-04及整阶段不收尾，P05未启动。

第四次[Windows/UNC证据](verification/P04-04-windows-evidence-04.json)及[原报告](verification/P04-04-windows-report-04.json)匹配f728c99的41项指纹/26个测试ID，26项检查通过、110个进程全完成；两位置当前9档各5轮及原版小档完整，金额/全部明细/冷一次暖0/源未改/清理均通过。本机及UNC当前原始最大间隔256.2393ms/256.2310ms，翻页心跳组本轮全部达标；仍有28+29=57个当前阶段p95超限，集中在1000/10000行首读及10000行查看。所有原/新版记录的切换间隔均为1ms，上一轮调度策略没有满足剩余指标。原值保留，不据此推断具体卡顿根因或统计因果。

现新增--diagnose-latency，实际Windows本机母版/子版10000行各一轮，只生成这两个文件，不生成1000文件档、不读UNC、不跑原版或全档；预计约1～3分钟。保留冷暖/查看/全页/筛选五阶段及整数分/行数/源哈希核验，加入缓存取得、workbook解码、脱离句柄、汇总分析、身份/订单、视图转换、主线程交付/呈现、GC区间及每线程CPU时间。全部起止相对同一心跳起点，长间隔列出重叠事件；重叠只表示相关性，嵌套区间不能相加。每阶段最多4096个事件，events_dropped与unfinished_gc显性列明，不把截断数据写成完整定位。

诊断额外插桩会改变耗时；状态为latency_diagnostic_completed_acceptance_pending、latency_diagnostic_only=true，全档/Windows健康验收门槛为false，即使单轮心跳通过也不能收尾。读取/交付失败保留所属阶段及部分事件，函数钩子和GC回调在成功/失败时还原，不强制GC、不改变回收设置。普通--gui-heartbeat仍要求至少5轮；诊断明确拒绝共享盘和旧版选项，非Windows在接触输入/窗口前阻断。程序业务/界面实现、价格/金额、缓存/解析、事务/CAS/回执和100/500ms门槛保持。[33项/完整339项辅助证据](verification/P04-04-trace-checks.json)含真实解码与Tcl分段预演、错误恢复、事件上限、真实选中文件/指纹门禁与一轮绝不能验收；本机延迟诊断待回传。先定位再优化，暂停第五次全档，P04留now，P05未启动。

## 短诊断01结果与读取线程让步

[短诊断01原报告](verification/P04-04-windows-latency-report-01.json)完整保存，原附件SHA256为380fcdfd88d882eca6567b210f2ee882ea1142bc30c3d4de468b671e58a999b6；[核对证据](verification/P04-04-windows-latency-evidence-01.json)确认07e5956的41项LF指纹、33个测试ID一致。实际本机母子10000行各一轮、共10阶段完成，无回调/进程失败、源未改、正常关闭/清理。冷读workbook/XML各1、10006源行；暖刷新/查看/翻页/筛选均0打开，全部明细/金额与末行可达正确。不是5轮/UNC验收，原第四次57个失败结果保持。

| 阶段 | 母版p95 / 最大ms | 子版p95 / 最大ms | 诊断状态 |
| --- | --- | --- | --- |
| 首读 | 143.6565 / 255.2839 | 128.1208 / 238.7705 | 均超限 |
| 暖刷新 | 64.0629 / 67.5819 | 64.0807 / 64.1433 | 单轮通过 |
| 查看 | 143.1392 / 190.1100 | 141.6649 / 157.3118 | 均超限 |
| 全部翻页 | 77.8309 / 143.2541 | 96.2574 / 97.7176 | 单轮通过 |
| 末行筛选 | 64.5303 / 124.9123 | 64.1175 / 79.3255 | 单轮通过 |

所有阶段事件丢失/未结束GC均0。母子单元格脱离分别1.5335/1.5106秒、汇总分析1.7775/1.7452秒、视图转换0.7403/0.8710秒；这些是带tracemalloc和额外trace的后台线程区间，不能等同无插桩实际耗时。母版最大255.2839ms区间在单元格脱离，主线程呈现跨度未重叠、GC重叠82.8185ms；子版最大238.7705ms也在脱离，GC重叠97.0475ms。查看的大部分超限与后台视图循环重叠，GC只有零点几毫秒，母子主线程整次视图交付11.1451/8.2831ms。现有记录支持优先改善后台连续循环的调度机会，不能单凭重叠认定GIL/GC独占根因，也不把解码/解析等嵌套耗时相加。

新增quote_files/scheduling.py：Windows读任务进入线程本地read_turns作用域，约每8ms连续循环预算后在行边界time.sleep(0.001)，醒来后重新计预算；嵌套复用、异常退出还原，下一个读任务新预算。Jobs仅读取通道启用，主线程及串行写入通道均不启用；非Windows辅助默认不启用。脱离单元格、只读行访问、分析/分组、视图转换及筛选加入检查点，所有行/校验仍执行，格式/金额/组归属/读取次数及缓存预算保持。原生解码、单次GC和操作系统调度可能超预算，8ms不是硬延迟保证；暂停可能增加总处理耗时，必须由下一份同设备报告核验响应和耗时。没有强制GC、修改回收阈值、停止后台任务或重入Tk事件循环。

额外trace仅包装ReadTurn.pause记录cooperative_pause区间，不钩全局time.sleep；原普通心跳全部保留。预演的故意界面交付失败输出现由其测试捕获，避免与实际worker故障混淆，实际worker完整stderr仍保留。[37项专项/完整343项辅助检查](verification/P04-04-cooperative-checks.json)包括时间预算/超时唤醒/嵌套异常恢复、真实并行读写线程隔离、真实1000行各端完整视图/末行筛选/精确金额/源不变/一次XML、真实读暂停trace钩子还原以及母子Tcl五阶段。辅助环境不是实际Windows/Tk/UNC，不冒充改善证据。

API依据：[Python 3.12 time.sleep](https://docs.python.org/3.12/library/time.html#time.sleep)、[threading.local](https://docs.python.org/3.12/library/threading.html#thread-local-data)；sleep只暂停调用线程，实际等待可能长于请求。恢复点07e5956；移除新读线程让步与检查点即可回到上一实现，业务数据无需恢复。

## 短诊断02通过与正式复验

[短诊断02原报告](verification/P04-04-windows-latency-report-02.json)按字节保存（1272010字节，SHA256 bf83cf3a2d2befc34ff55a8b697d15aac52c8c5b1ff24ae47fd2ab3e1f75c9d7）；[核对证据](verification/P04-04-windows-latency-evidence-02.json)确认f40e72b的42项LF指纹及37个测试ID全部一致，实际Windows本机37项检查通过，0失败/错误/跳过。母子10000行各一轮、10阶段均有足量原始心跳且全部达到冻结100/500ms门槛，最大124.7948ms；所有心跳统计与事件重叠独立重算，事件丢失/未完成GC均0，1028次cooperative_pause全部在读取线程。

| 阶段 | 母版p95 / 最大ms | 子版p95 / 最大ms | 本次状态 |
| --- | --- | --- | --- |
| 首读 | 75.2072 / 117.7576 | 77.6082 / 124.7948 | 单轮通过 |
| 暖刷新 | 64.0623 / 64.0756 | 64.0874 / 64.1547 | 单轮通过 |
| 查看 | 69.5156 / 99.8827 | 77.5957 / 97.2275 | 单轮通过 |
| 全部翻页 | 74.0373 / 74.3280 | 96.7699 / 97.3843 | 单轮通过 |
| 末行筛选 | 64.0853 / 64.1318 | 64.0757 / 64.0774 | 单轮通过 |

金额100000.00/40000.00/60000.00与10000条明细正确；冷workbook/XML各1、10006源行，暖刷新/查看/翻页/筛选零打开；母版51页及子版50页完整可达，末行10006筛选正确。输入未改，无回调/进程失败，实际窗口关闭及独占临时目录清理正常。回传没有读写生产路径，未读UNC，full_scale_five_rounds与Windows_healthy_performance_passed仍为false；诊断状态与这些门槛保持，不由十阶段单轮通过改成正式验收。

该设备/解释器/Tk/scaling记录与短诊断01一致，但两次独立生成工作簿的SHA不同，只核对规模/金额一致，不作为严格字节配对或改善百分比证据。本次首读母子11.2308/11.1528秒，查看1.0814/1.2531秒，较01的10.4925/10.2546及0.8756/0.9957秒有所增加；保留响应改善与总处理时间的实际取舍，不把让步暂停与嵌套解析/视图耗时相加。正式多轮报告将继续记录总耗时、分配峰值、全部心跳及读取正确性，无新的吞吐百分比门槛，也不撤销旧57个失败阶段。

本次不改程序、诊断工具、测试或金额/写事务；[完整343项含37专项辅助证据](verification/P04-04-cooperative-checks.json)保持，已通过的独立辅助检查不额外重跑。短诊断已满足推进正式性能复验的条件，使用原9种工作负载各5轮、原版小档配对、同批字节和实际本机/UNC临时子目录；保持正式每阶段至少20次回调及p95≤100ms、最大≤500ms，无事件丢弃、静默截断或降低门槛。断网/双机占用不重新安排，P04-01/02/03无需重新跑。P04-04及整阶段待正式报告与用户确认，P05未启动。

## 正式05共享根阻塞

[正式05原报告](verification/P04-04-windows-report-05.json)按字节保存（19164字节，SHA256 3ce3081f62e3332647e82d40741a65c1d1d1980cb365a68c3a670ffefac710b9）；[核对证据](verification/P04-04-windows-evidence-05.json)确认55f359e的42项LF指纹、37个测试ID全部一致，37本机检查通过、0失败/错误/跳过。报告status=failed、storages为空，error为ValueError: SHARED_ROOT_MUST_BE_EXISTING_DIRECTORY_WITHOUT_LINK。本机/UNC均未开始正式矩阵，没有新的心跳、金额或读取计数结果；这不是新的性能超限，也不算通过。

已验证的工具先构造两个storage父目录列表，shared_parent失败会早于本机/UNC测量临时目录创建；37个检查自身仍使用隔离合成夹具。原报告production_paths_accessed=true与explicit_shared_root_requested=true保持，说明显式共享根元数据检查曾尝试；production_files_read_or_modified=false，不写成“完全没有共享路径访问”。现有门禁将is_symlink、is_junction和not is_dir合并报错，附件未记录实参、具体属性或底层Windows错误，不能据此断定目录不存在、权限不足或实际链接。程序/工具没有变化，不在缺少现场信息时放宽目录门禁。

下一步只读查看指定UNC根的FullName/PSIsContainer/Attributes/LinkType/Target或实际访问错误。普通目录且可访问后才继续正式本机/UNC各5轮复验；如路径不同，使用实际已确认的普通目录，不自动扫描/猜目录，不移除或改造共享目录。正式05输出已存在，重试必须使用新的reports/p04-04-windows-06，保留原失败报告。[短诊断02十阶段通过](verification/P04-04-windows-latency-evidence-02.json)、[343项含37专项辅助](verification/P04-04-cooperative-checks.json)和历史完整报告保持原值，已通过无变动检查不另跑。P04-04及整阶段待正式证据，P05未启动。

## P05-01本地账本接口

[ledger-v1契约](verification/P05-01-ledger-contract.md)建立订单/明细/追加备注/发布价格/导入批次/审计/请求回执。存储层收到QuoteSnapshot与可信内部Principal，由账本当前发布版本调用既有核心计算，不接收客户端金额结果；不同价格版本先重算确认，管理员价格发布带expected_price_version_id CAS。request_id绑定主体/操作/规范负载，同键同载荷重放原回执，冲突拒绝。订单/明细/价格不可变，状态和备注变更带revision审计；成功事务不因后续回执发送错误撤销，通过请求查询恢复未知结果。

备份为完整一致SQLite快照及版本/哈希/核对清单，独立恢复后才登记成功；不兼容库拒绝写、独立新路径恢复，不覆盖现有文件或其WAL/SHM。高精度参数按原文/规范十进制字符串保留，金额对外字符串分而非JS浮点。Principal在当前模块是内部信任前提，不能把客户端自报role当认证；网络会话、角色DTO和实际客户端移交P05-02，ImportBatch实际填充及历史行归属移交03，附件移交04。

## P05-02认证服务协议v1

[P05-01已验收](verification/P05-01-acceptance.json)；[P05-02契约](verification/P05-02-service-contract.md)冻结HTTPS业务边界：服务端账户/会话恢复Principal，客户端actor/role/财务总额不可信。调用者以lossless字符串提供business-v1/numeric-v1输入、request_id/expected_revision/价格CAS；钱为字符串整数分。销售只获得本人销售数据和允许字段，不含成本/利润/其他归属，原参数/价格仍冻结。标准DraftDetails字段customer/order_ref/wechat不当登录身份。结果未知查询本人回执再用原ID原负载重试，客户端DPAPI保存并绑定原服务/身份。目录属于服务发布配置，不再由Excel文件路径决定权威账本。

主机完整服务恢复包含财务库、Auth账户ID/设置/计划和TLS材料，独立新目录核对后为维护状态；旧会话/凭证失效，管理员新密码及其他账号重设/启用后按停旧写端与增量对账切换。42专项/427辅助通过；Windows原生Tk/DPAPI及真实主机/E盘/物理双机未完成。旧账本迁移在03，报表/附件任务在04，当前未生产切换。


## P05-03 导入协议与来源守恒

[legacy-import-v1](verification/P05-03-import-contract.md)只接受显式文件、只读预演SHA与管理员/保管人绑定。原钱/输入/价格逐行与共享核心核对；差异、未知格式、公式或无可靠边界的同秒记录隔离，不从显示名或时间补造业务身份。历史价格不成为当前发布版；源表/行到稳定新ID、原版本/状态/事件和完整源字节存于受保护ImportBatch，并与不可变请求回执核验。单来源全事务、相同来源/适配版本重放不重复，未知结果沿用原batch request_id。公开金额/差异分用十进制字符串，明确区分通过部分金额和源读取金额，未知金额不伪装零。

本轮复用ledger-v1 DDL；本机管理员入口持主机锁并先验证完整维护备份，不提供客户端任意路径写入接口。具体跨语言适配、来源恢复验证及限制见契约，真实历史存在性与上线迁移仍待现场/副本证据。


## P05-04报表、附件与查询兼容

账本财务提交与输出任务独立；ledger-v1的schema/revision不因创建或补导出而改变。输出扩展777-output-store-v1绑定ledger_id，冻结订单版本/价格/规则/金额/备注、只追加回执和事件，queued/running/failed/done持久恢复。共有发布类型只含收入字段，内部成本/利润报表限管理员且仅在私有目录；客户端输入不能指定输出路径。完整备份v2包含扩展与索引文件，继续读取/恢复旧v1；恢复仍维护状态、旧会话失效。

777-output-v1固定四表和PNG元数据；金融整数分始终十进制字符串，Excel文字不执行公式，XML控制字符显示码点且原输入不改。源价格与原snapshot冻结，重复请求/补导出不重新计价或入账。777-query-v1签名游标绑定身份/范围/view，变化拒绝旧页；范围统计只计active并通过审计增量重算，不建立第二套持久财务权威。静态样例、精度/版本拒绝、角色允许字段与备份兼容见[P05-04契约](verification/P05-04-output-contract.md)和[协议样例](verification/P05-04-protocol.json)，供Rust复用。


## P06-01领域影子JSON边界

business-v1/numeric-v1规则不变。Rust领域影子协议见[P06-01 JSON契约](verification/P06-01-protocol.json)；输入金融字段是原文本，原配置JSON数字保留token，输出金额及u64草稿revision用十进制字符串，不经JS或JSON浮点。原53例黄金的numeric-v1-proposed仅按P01批准映射，原文件与期望不改。

草稿以稳定draft_id和revision标识；纯核心生成的私有请求/完成类型绑定同进程generation，拒绝迟到/跨草稿/同值变回工作。`price_source=current`只表示可信调用者观察，并非认证或价格发布凭证。现有Python服务仍执行认证、角色过滤和唯一账本写入；将领域成本DTO直接交给销售不符合P05边界。此轮没有改变ledger-v1、P05业务API或真实数据；接替留P06-02/04。


## P06-02同schema原生存储与领域适配

Rust账本保持ledger-v1、已确认P05 API/客户端及角色过滤；[02契约](verification/P06-02-storage-contract.md)登记原请求指纹的Python排序紧凑JSON、事务/revision/价格CAS和原生备份。私有native JSON不是外部认证API；主体只能由现有会话恢复。显式后端配置只选择一个财务写端，未知/损坏Rust不自动回退；同v1交接不升级schema，不覆盖未知库。导入的Python格式桥接仅内存预演，最终Rust重验全账本并提交。

完整包v3包含已登记私有worker/许可与输出队列，旧v1/v2可读；新目录恢复保留后端与账户/TLS身份，撤销旧会话，默认维护。真实切换仍需P08停止旧写端及增量对账；本轮只隔离实现/验证。


## P06-03已实现的Excel格式接入

[03契约](verification/P06-03-excel-contract.md)在保持ledger-v1、legacy-import-v1、777-output-v1及原角色/发布规则下，以Rust保留受限OOXML原数字并生成新报表。正常旧源的完整Plan/review SHA和批次身份不变；数字浮点兼容会有损时明确复核定位，公式即使有缓存也拒绝，未知/扩展格式不写原件。新输出按冻结字段/整数分文本/前导零/字面字符串及样式核对，来源Excel仍不成为另一个财务写端。

新worker声明rust-excel-v1；已知旧财务版v1的能力未知命令回复只协商明确的python-v1-compatibility格式桥接，财务仍由原生执行文件负责，缺失/坏hash/未知能力形状拒绝。恢复保留v3原资源/输出/回执/账本，不自动覆盖旧执行文件。依赖与临时Python桥接及04退出门槛见[私有协议](verification/P06-03-protocol.json)，当前未部署或切换真实资源。


## P06-04原生宿主与完整包v4

[04协议](verification/P06-04-protocol.json)保留ledger/auth/output-v1与777-service/query/output-v1，Rust宿主直接链接领域/账本/Excel并执行当前会话角色过滤；原请求/金额文本、目录继承/成本隔离及批次身份不变。host-v1可选service_backend/rust_host_sha256明确选择一个监听宿主，原owner锁/完整维护备份及资源登记约束切换；已选Rust主机不能启动Python监听或隐式回退。

完整v4只增加已登记宿主/许可，旧v1/v2/v3可读；原包不改，独立新目录恢复撤旧会话、禁用其他旧凭证、默认维护，显式确认旧主机停写后才启动副本。离线历史字段映射与独立Python验证器保留为兼容工具，运行服务与原生完整备份不调用Python。真实部署/迁移仍按P08交接执行。


## P07-01桌面DTO与状态

[桌面契约](verification/P07-01-desktop-contract.md)保持business-v1/numeric-v1、ledger-v1、777-service/query/output-v1。UI原文输入和十进制金额/revision字符串，经deny_unknown_fields的Action枚举交给Rust；不存在任意URL/path/actor/SQL/shell透传。每次编辑/价格更新使草稿结果失效，迟到结果不能恢复提交资格；Rust再比冻结snapshot/revision，服务最后重验价格与金额。

变更发送前以DPAPI独占保存原request_id/请求/账号/服务pin；未知结果只能查询或按原请求重试。核查回执返回该新单原始snapshot/details，UI仅清理仍与原请求相同的草稿，提交期间新编辑保留且重新计算。已确认保存后的视图刷新失败不改变提交结论，也不提供重复入账重试。销售导出/图片目录是管理员发布的只读继承值，不能沿用早期规划的销售自行修改表述。

## P07-02设备身份与启动扩展

[设备协议与v5恢复](verification/P07-02-auth-contract.md)实现6.4：稳定actor仍来自原users，设备只负责登记/撤销，token和device_secret不跨IPC。普通发布包须选择manager或sales，服务端重验类型/角色/epoch/归属；未知提交保持原request_id及身份，不因自动认证另生成订单。可选devices.sqlite3及service.json标记不改变ledger-v1/auth-v1。完整v5包增加设备库，恢复全部撤销设备/会话/登记材料；旧v1至v4仍读，旧恢复器不接v5。

用户指定admin / 123456仅用于已标记的固定回环开发宿主，证书和连接跨重启保留；普通账号创建/重设策略保持，不把开发材料编入正式母子包。辅助验证已通过，Windows与用户验收待完成，真实服务/数据未切换。

## P07-03利润汇总与目录选择补充

管理员专用只读 `/v1/analytics` 按入账时间和北京时间统计全部有效订单，支持日、周（周一起始）、月、年，日期边界含首尾，最多400桶；跨年周按周一起始日期作键。保存的收入/成本/利润使用BigInt整分聚合、字符串返回，历史订单不因价格更新重算；作废排除、恢复计入，未知历史日期显性计数。销售直接请求同样拒绝，前端不以订单分页小计生成利润分析。完整字段/舍入与空状态见[P07-03业务契约](verification/P07-03-business-ui-contract.md)。

母版目录弹窗只选择共享导出/图片文件夹，取消保持原值，显式发布后服务按原revision/路径规则保存；子版只读继承。主机私有账本/备份不经此弹窗变更。“导出记录”呈现既有导出任务，不新增记账入口。

P07-03快捷时间以当前北京时间为上界，回推1天=24小时、1周=7天、1月=1日历月、1年=1日历年；月份缺少对应日时取月底并保持时刻。范围与日/周/月/年分组独立。服务接受精确本地时刻边界并先过滤后分桶；旧日期查询保持整日含首尾。自定义时段刷新不移动，快捷时段刷新重新回推。金额/作废/权限/分页边界不变。

P07-03按最新截图移除所有页面提醒条，保留无条形样式的错误文字与报价操作区原请求恢复。利润分析可切换柱状/折线/饼图/K线，同一时间筛选和revision；只读analytics响应新增每桶整分字符串profit_ohlc，按精确时间过滤后同刻合并、累计利润开高低收，末收等于总利润。饼图按各桶净利润绝对值且保留亏损标记。旧服务缺失OHLC时不伪造K线；无数据库schema变更，权限/已保存金额保持。详见[业务契约](verification/P07-03-business-ui-contract.md)。


### P07-03用户确认的最终销售单价扩展

2026-10-15 20:13用户要求独立售价和“成本×K”勾选。本扩展由每项`pricing_mode`显式区分，不覆盖旧D06/历史样本：缺失＝原基础售价×K；manual＝sale为最终单价，K不再乘收入；cost_plus＝最终单价由cost×K精确重算，输入sale不能覆盖该计算。基数仍为高×宽×数量或单件数量，成本不乘K，行结算/折扣/容量保持；单价不提前按分量化。旧价格未编辑保持原快照，旧订单金额不变，新的模式/成本/K随不可变版本冻结。SQL/schema不变；不识别模式的旧宿主不可降级写入，需兼容版本或改动前备份。

管理员目录增加精确`unit_sale`和版本能力标记。销售不接收新成本倍率/模式，以最终售价和实际报价因子1投影，避免推导成本。Rust/Python独立核对、自动价防篡改、恢复/重启及行内商品切换规则见[业务契约](verification/P07-03-business-ui-contract.md)与[检查](verification/P07-03-price-editor-checks.json)。
