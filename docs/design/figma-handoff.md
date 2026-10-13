# Figma 设计交接与软件接入

## 当前状态

2026-10-13：按用户要求建立 `Figma` 分支的[仓库 agent](../../AGENTS.md)，纳入 Hallmark、Open Design、UI/UX Pro Max、Taste、shadcn 五项来源及职责。分支基线为 `223e86e0bef90dfef083281a42f8d7919b13c07d`。Agent 与流程已在 `e916efa` 提交；随后按用户要求清理继承的业务文件，当前分支仅保留 `AGENTS.md` 和本交接文档。后续只在此分支维护 Figma / agent 相关内容，业务材料通过原开发分支链接读取，不复制进来。

本交付是项目级组合流程及上游来源登记，**不是五个 skill 的本地安装或源码镜像**。未执行上游安装脚本、未新增生产依赖，也没有创建 Figma 设计或实现 Tauri 页面。实际使用时从登记版本读取完整 skill 及相关引用；若需安装脚本/数据，先核对权限、依赖和许可，不仅复制一个 SKILL.md 后声称工具可用。

[主任务书](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/MASTER_PLAN.md)和[P07](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/new/P07-tauri-desktop.md)仍约束正式接入；本设计准备不更新 P06 验收结论、不提前启动 P07。未来续接先检查当前开发分支，不能把此基线快照当最新业务状态。

## Skill 来源与适用边界

以下为 2026-10-13 核对的上游 main 提交；具体文件已读取。上游变化时重新审阅后更新记录，不静默跟随最新版。固定提交用于追溯，不代表已安装到宿主。

| Skill | 上游固定入口 | 本项目职责与限制 |
| --- | --- | --- |
| UI/UX Pro Max | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/7246805992a42b7bba37d4cac83b01416f0c6c44/.claude/skills/ui-ux-pro-max/SKILL.md) | 需求、交互、可访问性、布局与设计系统候选；按实际栈检索，不假定框架。需要脚本时连同其数据和引用读取。 |
| Hallmark 1.1.0 | [Nutlope/hallmark](https://github.com/Nutlope/hallmark/blob/13ac0ec7e148655948100b6396439e481361d690/skills/hallmark/SKILL.md) | 视觉层级、字体、token、一致性和截图复核；应用共用一套系统，不套营销页章节或逐页随机主题。 |
| Open Design | [nexu-io/open-design skills 目录](https://github.com/nexu-io/open-design/tree/1343f374c63d7866f4f3ff5d48ef038eba647f1b/skills) | 设计能力集合，不是一个万能转换器；[Figma 实现入口](https://github.com/nexu-io/open-design/blob/1343f374c63d7866f4f3ff5d48ef038eba647f1b/skills/figma-implement-design/SKILL.md)仅为上游流程目录，执行应使用完整 Figma 技能及可用工具。 |
| Taste v2 experimental | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill/blob/c924fad1a79c7d70a04bcc8c415b593e9928ad8a/skills/taste-skill/SKILL.md) | 明确不适用于 dashboard/app screens；记账器不以其营销页脚本、大图数量和动画数量作为门槛。仅保留通用审美复查参考，不能称完整采用 v2。 |
| shadcn 官方 skill | [shadcn-ui/ui](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/skills/shadcn/SKILL.md) | 设计前判断组件可实现性，接入时复用组件与主题。配置、底层 primitives、组件 API 以实际安装版本为准；不自动初始化项目或覆盖 preset。 |

Open Design 同名项目较多，本流程明确采用 `nexu-io/open-design`，不与其他同名 agent kit 混用。上述技能是工作方法，不能授予额外 Figma/GitHub 权限，也不替代本项目任务书。未复制上游代码；未来引入代码、字体、图标或依赖时单独核验许可和分发义务。

## 执行与交付顺序

| 环节 | 主导能力 | 应交付内容 | 完成依据 |
| --- | --- | --- | --- |
| 需求与交互 | UI/UX Pro Max | 页面清单、角色矩阵、任务路径、错误/异步状态 | 与 P07、业务契约对应，无范围外功能 |
| 实现可行性 | shadcn 前置核对 | 组件候选、组合方式、定制缺口、框架候选说明 | 能说明如何实现；不将候选写成已安装 |
| 视觉方向 | Hallmark | 中文字体方案、信息密度、语义 token、组件风格 | 真实业务内容可读，跨页面一致 |
| 可编辑设计 | Open Design 方法 + Figma 专用技能 | 变量、组件/变体、页面实例、角色状态及原型 | 可编辑节点及链接，实际截图复核 |
| 设计复核 | UX/Hallmark + Taste 通用参考 | 可用性、层级、长文本、焦点/错误等缺陷修复 | 有节点截图与复查记录，Taste 应用页完整流程不适用 |
| 软件接入 | Figma design-to-code + shadcn/实际栈 | tokens/组件映射、功能模块、IPC/服务绑定 | P06 前置和实施授权满足；真实动作经过现有后端 |
| 验收 | P07 任务书 | 视觉、角色权限、真实业务、DPI、安装证据 | 逐项通过；未验证项不宣称完成 |

## 设计范围与业务依据

从[迁移契约](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/MIGRATION_CONTRACT.md)、[P07](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/new/P07-tauri-desktop.md)、[架构方案](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/RUST_TAURI_DESIGN.md)和当前已实现接口派生设计。至少覆盖：

- 报价编辑、输入校验、计算反馈、价格快照与过期重算。
- 管理员价格与利润视图、订单分页查询/详情、追加备注、作废/恢复；销售仅获授权的本人订单和追加备注，不接收成本/利润。
- 报表/报价图任务进度、成功/失败/可重试、未知提交核查，订单成功与附件失败分开呈现。
- 设置 → 存储与备份：完整路径、用途、来源和真实状态；角色权限依照[目录/备份定义](https://github.com/uniquenesssta/777/blob/stage/p06-rust-core/docs/baseline/P01-03-directory-backup.md)。
- 登录/会话失效等支撑状态依现有认证接口设计；离线仅草稿。截图与完整报价图依据 P07 确认要求，不擅自删除任一已有入口。

不新增店铺分红、库存、税务、云同步、移动端、营销网站或跨平台验收。

## Figma 文件组织与可实现性

实际设计开始后建议用 Foundations、Components、Patterns、Screens、Prototype/Review 分组；名称可按文件实际结构调整。所有正式页面复用组件实例与变量；状态以明确的属性/变体或页面状态表达。装饰资产可位图，输入、表格、导航和弹窗不能整页栅格化。

先完成一条代表性路径的设计与组件映射检查，再按授权范围展开，避免所有页面画完后发现无法实现。该检查可以是文档级映射；在 P07 前不因此提前引入生产前端。已确认的 Figma 外观不能被 shadcn 默认主题覆盖；合理定制落在组件变体/token，差异需解释并记录。

首期只有 Windows 产品要求。画布尺寸、最小窗口、字体、主题范围在实际设计时记录为候选或已确认；未确认时不伪造数值和用户决定。长订单采用明确分页/滚动策略，受控表格横向滚动不能被通用“禁止横向滚动”规则剪掉数据。

## Figma 到代码的交接字段

以下空表是待填写的交接契约，**不是已完成映射**。实际设计/实现时在本节维护，规模变大再按职责拆分。

### 文件与页面

| 文件链接 / file key | 页面 / 根 node ID | 角色与任务 | 设计状态 | 用户确认与证据 |
| --- | --- | --- | --- | --- |
| 待创建或指定 | 待登记 | 见设计范围 | 未开始 | 无 |

### 变量与资源

| Figma variable/style ID | 语义名称与模式 | CSS/主题 token 或资源路径 | 精确值/单位/字体授权 | 验证证据 |
| --- | --- | --- | --- | --- |
| 待登记 | 待设计 | 待前端选型 | 未确定 | 未验证 |

覆盖语义颜色、字体/字重/行高、间距、边框/圆角、必要阴影与动效；中文字体回退和离线可用性须实测。新增资源记录来源与许可；不依赖远程字体加载才能显示核心界面。

### 组件与动作

| Figma node ID / 组件 / 变体 | 代码文件 / 导出名 | 属性与状态映射 | 用户动作 → IPC/服务接口 | 输入/返回 DTO 与权限 | 检查证据 |
| --- | --- | --- | --- | --- | --- |
| 待登记 | 待实现 | 未确定 | 以现有接口为准，未填写 | 待核对 | 未验证 |

每个动作同时记录失败、取消、重试、未知结果、焦点返回与状态保留规则。可用时用 Code Connect 关联组件；不能自动关联的部分保留此表和原因，人工映射不等于自动同步已完成。

## 软件接入与验收方法

1. 从已确认 Figma URL 精确读取节点上下文、截图和变量；先取页面结构再按组件读取，避免只靠截图猜属性。落实框架选择后核对依赖与组件配置。
2. 语义 token 接到统一主题层，公共交互接到现有组件，业务页面按功能组合。前端 UI 状态和服务器订单/价格状态各有权威归属，不在各页面复制缓存与计算规则。
3. 逐项绑定真实业务接口。金额整数分字符串不转换为 JS Number 参与计算；接口 DTO、鉴权、幂等、价格版本和错误语义以当前业务实现为准。任何占位/mock 需标注并在正式验收前替换。
4. 用相同样例、窗口条件和状态对照 Figma 与运行画面，记录差异并修复；核对中文长名称、长订单、空数据、焦点与快捷键、加载/失败/关闭状态。
5. 按 P07 跑管理员和销售真实链路、直接越权调用、路径边界、Windows DPI 及安装/更新/回退验收；测试环境与已通过范围明确记录。Figma 原型连接通过不代表真实业务、权限或安装通过。

## 续接记录

- 已完成：远端 `Figma` 基线与干净工作区核对；通用规则、主任务书、P07 与架构阅读；五项上游来源、职责和适用边界核对；agent 与映射字段建立。
- 清理记录：按用户明确要求，从 `Figma` 分支移除所有非 Figma / agent 文件及文件夹，包括业务源码、测试、依赖、阶段任务书和业务 README；只保留两个上述文档。修复被移除文档的链接，改为指向原开发分支；其他分支不修改。
- 本次验证：完整提交树只含上述两个文件，保留文档的相对链接有效；业务文档链接目标在清理前基线存在。此为设计分支内容整理，不运行该分支已移除的业务测试；未实施 UI，不存在 UI 或 Windows 验收通过结论。
- 待后续授权范围内执行：按设计请求创建/登记本项目 Figma 文件、明确视觉依据与角色状态并绘制；P06 硬性前置及 P07 授权满足后才接入正式客户端。
- 恢复：清理保留 Git 历史，可通过撤销本次清理提交恢复原分支内容；不改写历史、不改业务数据，不将清理提交合并至业务开发分支。后续软件接入只选取所需设计资产，避免传播删除。
