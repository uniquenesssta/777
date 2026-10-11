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

Excel保留原26列与normal/discount/order_total行类型，新单额外列为订单ID、明细ID、订单版本、请求ID、记录状态。身份UUID、订单初始版本1，新备注/作废令整单版本加1，文件全局版本在隐藏`_写入事务`回执中递增；明细ID不使用用户、时间或UI行号。作废保留金额和原行，active/void决定有效日汇总。重复同一计算导出复用request_id；主动重新计算得到新的计算revision及写入请求。旧未识别记录不补猜身份、不改原金额。

备注按稳定order_id追加，独立订单备注记录request_id及文本，并在该单总计的备注列追加文本。当前未开放作废恢复/归档UI、历史转换和子版备注归属认证，按P03-02/P03-04/P05补齐。销售仍不能直接接收安全保证：隐藏列/工作表不是保密；现有共享Excel/JSON可能含成本，A05持续开放。

配置整份校验后按读取版本CAS保存，JSON业务schema不加请求字段；配置效应由内容SHA和旁路日志核查。恢复副本在`.777-recovery`，与正式主机独立备份分开。所有旧写端需退出协作写入；非协作外部Excel仅作关闭写端后的查看，不保证任意外部编辑并发安全。P03-01辅助证据不等于真实Windows/SMB验收。

## P03-02 已实现的格式读取契约

完整定义及兼容矩阵见[工作簿契约](verification/P03-02-format-contract.md)，证据见[辅助检查](verification/P03-02-checks.json)。规范26列、行类型、5列身份在`quote_files/schema.py`单一定义，识别完整字段、别名和重排；两端读取、追加、订单操作及金融样式按列映射。未知字段/身份残缺不猜测；未知附表/扩展和公式只读保留；模板禁止清空已有数据。

读取返回`ok/error/unsupported`，仅ok有权威整数分总额；失败不返回正常零。摘要只读表头前的标签；无摘要按有效明细核算，有摘要必须完整且与明细一致，正常零仍可读取。公式只读已有缓存且报告时效未知，无缓存或不一致明确失败；不执行公式、不覆盖原件。新身份、用户字段及原始表达式以显式文本保存。

历史分组只有稳定订单ID或已核对的明确导出边界才可靠；同客户同秒的订单号差异不合并，归属歧义报告并保留明细/文件总额，不分配持久ID。UI文件列表给出读取状态；合法零计文件数，部分统算报告排除数量，全部失败显示无可用金额。上述类型、问题码和字段映射可供P05/P06复用，但历史转换、服务授权、Rust IPC及完整迁移尚未实现。P03-01已按[用户确认](verification/P03-01-acceptance.json)验收通过；P03-02的21项格式检查及母子Tk联测已在Windows通过，见[本机证据](verification/P03-02-windows-evidence.json)。
