# 业务与数据迁移契约草案

状态：拟议，P01确认规则后冻结首版；不能把草案当作已实现接口。来源：[审计报告](audit/python-audit.md)。本文件维护唯一字段/规则定义，阶段任务书只引用。

## 1. 已确认的业务现状

| 类型 | 销售额公式 | 成本公式 |
| --- | --- | --- |
| 面积项目 | 高×宽×数量×销售单价×K | 高×宽×数量×成本单价 |
| 单件项目 | 数量×销售单价×K | 数量×成本单价 |
| 折扣行 | 前面当前销售小计×(折扣百分比/100−1) | 0 |

订单利润＝总销售额−总成本；综合利润率＝总利润/总销售额。当前零销售额显示0，是否改为“—/不适用”由P01确认。折扣按顺序叠加，折扣后新增商品不追溯打之前的折扣。单位标记、四则运算、余数、括号、百分号的现有支持需做兼容样本；布尔接受和溢出不是要保留的特性。

## 2. 建议金额规则（待确认）

输入保留原文并解析为十进制，禁止先经float再转Decimal；尺寸/数量/价格/K的最大值、小数位、表达式中间精度及除法规则由P01表格冻结。建议业务金额逐行ROUND_HALF_UP到0.01，行利润＝量化销售−量化成本，订单金额为已量化行之和。折扣以当前已量化收入小计计算并量化至分；0%/100%、多次折扣、负值、零分母单独测。历史已确认账本保留原值及旧rule_version，不因新规则重算覆盖。

IPC/JSON使用十进制字符串（如`"123.45"`），持久化已结算金额用有符号整数分；跨JS边界大整数用字符串避免精度丢失，尺寸/单价的精度不得粗暴压成两位。Rust十进制表示必须证明满足范围、舍入及溢出策略；使用checked操作。前端只展示服务返回的权威结果。

## 3. 实体与身份

| 实体 | 必需字段（拟议） | 一致性与历史要求 |
| --- | --- | --- |
| Product | product_id、name、unit_kind、active | 名称非主键；改名不改变旧单含义 |
| PriceVersion | price_version_id、schema_version、published_at、publisher、items、checksum | 发布后不可变；销售投影不含cost；订单绑定版本 |
| QuoteDraft | draft_id、revision、customer/order_ref/wechat、ordered_lines、price_version_id、rule_version | UI修改使计算过期；草稿不进入正式汇总 |
| Order | order_id、external_order_no、customer_id_text、wechat_text、created_at、business_date、actor_id、device_id、revision、status、request_id、rule_version、price_version_id、totals | 内部ID独立于淘宝ID、时间及用户订单号；业务日期和时区显式记录 |
| OrderLine | line_id、order_id、sequence、line_kind、product_id、product_name_snapshot、unit_kind、raw_inputs、normalized_inputs、unit_prices_snapshot、k、discount、amounts | line_kind=normal/discount；备注不伪装商品；金额快照不可被新价格重写 |
| OrderNote | note_id、order_id、revision、text、actor_id、created_at | 确认追加/编辑规则；引用稳定订单，不引用Excel行号 |
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
| add_note / void_order | order_id、expected_revision、request_id、操作内容 | 新revision或明确CONFLICT/FORBIDDEN；作废可恢复策略待确认 |
| publish_prices | 完整schema、expected_version、request_id | 新不可变版本；只允许授权角色 |
| import_legacy | 受控文件选择、dry_run、策略 | 检测结果、差异报告、导入批次；确认后事务提交 |
| export_report | 数据范围、格式版本、角色 | job_id与完成路径；失败不撤销已确认订单 |
| get_job / cancel_job | job_id | running/committed/completed/failed/unknown/cancel_requested；不能把取消请求等同于已停止 |

错误结构至少包含code、可读message、field_errors、request_id、retryable、commit_state；典型码VALIDATION、PRICE_STALE、CONFLICT、FORBIDDEN、NOT_FOUND、IO_UNAVAILABLE、SCHEMA_UNSUPPORTED、COMMIT_UNKNOWN。技术路径/堆栈保留在受控诊断，用户只见可操作信息；错误不可替换成正常零值。

## 6. 状态与权限

草稿→校验通过→提交中→已提交；任一输入或价格版本变化使旧计算过期。结果未知先查询request_id再重试。订单提交与Excel生成分开：订单成功、报表失败可单独补导出，不重复记账。

管理角色拟拥有价格发布、利润查看、导入、备份与作废权限；销售角色拟拥有报价、提交订单、销售查询；备注/作废以及“仅自己的订单或全部订单”的权限在P01确认。服务从认证会话确定actor，不能相信客户端role/actor字段。Tk隐藏页面或Tauri capabilities均不能代替局域网业务鉴权。

## 7. 跨语言黄金样本要求

正确样本覆盖面积、单件、K空值默认1、零成本、0/100%折扣、连续折扣、折扣后加商品、中文单位、百分号及表达式。边界覆盖分位舍入、最大金额、除零、非法bool、负数政策、重复商品名和陈旧价格。每例包含input、price_snapshot、rule_version、期望行金额/总额/错误码；精确比较，不用浮点近似。

审计中复现的错误另列“旧缺陷→确认后的新期望”，不作为Rust必须复现的黄金正确结果。历史导入按订单数/明细数/收入/成本/利润/备注关联五类指标核对，歧义名单必须清零或经业务确认隔离并注明未迁移范围。
