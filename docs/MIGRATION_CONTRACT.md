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

## 7. 跨语言黄金样本要求

当前共用材料为[P01-04静态黄金集](baseline/p01-04-golden.json)，53例；[验证入口/格式候选/性能方案/Windows清单](baseline/P01-04-validation.md)。每例明确business-v1或numeric-v1-proposed的期望依据；参数已按[P01确认](baseline/p01-acceptance.json)原值采纳，历史numeric-v1-proposed元数据对应numeric-v1；后续不得重写原黄金期望。P02/P06读取同一JSON，不复制期望值。

正确样本覆盖面积、单件、K空值默认1、零成本、0/100%折扣、连续折扣、折扣后加商品、中文单位、百分号及表达式。边界覆盖分位舍入、最大金额、除零、非法bool、负数政策、重复商品名和陈旧价格。每例包含input、price_snapshot、rule_version、期望行金额/总额/错误码；精确比较，不用浮点近似。

审计中复现的错误另列“旧缺陷→确认后的新期望”，不作为Rust必须复现的黄金正确结果。历史导入按订单数/明细数/收入/成本/利润/备注关联五类指标核对，歧义名单必须清零或经业务确认隔离并注明未迁移范围。

## 8. P02-01已实现的Python领域接口

实现入口为[quote_core](../quote_core/__init__.py)，使用business-v1与已采纳的numeric-v1，生产模块只依赖标准库。它不读取仓库profile、黄金、配置或Excel；[批准记录](baseline/p01-acceptance.json)与测试按Git已提交LF字节指纹（工作区仅CRLF转LF）核对参数。历史候选标识numeric-v1-proposed仅是保留的证据别名，不是生产接口默认版本。

| 已实现类型/入口 | 输入与结果 | 边界 |
| --- | --- | --- |
| NormalLine / DiscountLine | 普通行product_id/q/h/w原文，或明确的折扣percent原文；名称仅展示 | 普通/折扣由类型显式区分，原文保留；不凭商品名称判断折扣 |
| PriceItem / PriceSnapshot | 商品键、sale/cost/k原文、single布尔；独立的price_version_id和不可变items元组 | 用到的价格逐字段校验；single字符串false拒绝，空价格拒绝，空K默认1；整份配置发布校验在P02-02 |
| QuoteSnapshot | 不可变有序lines、绑定price_version_id、rule_version和numeric_profile | 列表入参复制为元组；不接受可变字段/控件，布尔或浮点等错误原文由计算报VALIDATION；空订单/超过10000行拒绝 |
| calculate_quote(snapshot, prices) | QuoteResult；逐行整数分、原输入/价格和规范十进制串、折前整数分、订单总额、错误/提醒 | 快照版本须相同；不加载/刷新价格、不写账，不能据此证明已发布价格或正式提交授权 |
| Amounts | income_cents/cost_cents整数，profit_cents派生；margin_tenths为百分比十分位或null | display仅从整数分生成文本，cents_payload把分整数转字符串跨JS边界；不从UI文本回读金额 |
| capture_legacy_quote(rows, config, price_version_id=...) | 主线程读取两版当前行与已获取价格映射一次，返回QuoteSnapshot/PriceSnapshot | 单件不读高宽，自定义折扣保留全部精度；不读res/status/summary、不保存Tk变量；尚未接入两版窗口 |

QuoteResult携带business-v1/numeric-v1/price_version_id。VALIDATION时lines和totals均为null，issues含reason/field及从1开始的行号；成功才有完整金额。首行或零小计折扣返回零并附DISCOUNT_ZERO_SUBTOTAL提醒，折扣行及零收入利润率为null。未实现草稿revision、输入变更/PRICE_STALE状态及真实导出阻断，它们属于P02-03/P02-04。领域价格包含成本，仅用于受信任计算链，销售DTO及服务鉴权由P05落实，不能把完整领域对象直接当销售投影。

母子原calculate尚未切换，原summary回读/部分导出缺陷也未据此关闭。P02-04接回两端后才能验收UI、保存/Excel/图片都使用同一权威结果；历史账本不重算覆盖。
