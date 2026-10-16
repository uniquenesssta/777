# P07-05 开发部署设计映射

用户2026-10-16在任务书提交 b6b117e 后明确“那就开始吧”。先在原 Figma 文件的当前页21:2设计，再实现。继续使用已确认的 Noto Sans SC / Inter 字体、紧凑紫灰色系、现有 Button / Field / Badge 和确认框；不改正式业务页结构。

| 状态 | 可编辑 Figma 节点 | 实现 |
| --- | --- | --- |
| 配置与封包 | [70:1188](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=70-1188) | `DeveloperPage.tsx` 两列数据/备份与封包配置，下方任务区 |
| 读取失败 | [73:1126](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=73-1126) | 当前数据源保留，错误就近显示 |
| 构建中 | [73:1235](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=73-1235) | 两个封包按钮禁用，显示真实日志、取消入口，无假百分比 |
| 构建成功 | [73:1348](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=73-1348) | 当前任务产物目录、大小和源码提交 |
| 新建确认 | [76:1258](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=76-1258) | 复用紧凑 Modal；明确两个空目录与保留旧数据 |
| 首次读取认证 | [76:1269](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=76-1269) | 复用原管理员身份，认证失败不切换 |

主页面1440×884；画布#F5F6F8、白色卡片、16px圆角、24px内边距、20px区块间距、40px输入框/按钮、73px横向标签。复用现有CSS token与组件，1100px以下转单列，长路径可查看完整title，不撑宽操作区。Figma样例路径、账本ID、备份时间和封包大小只是排版示例；运行时全部来自真实状态。

已对主页面和弹窗执行截图检查；原页读取失败、构建中及成功状态分开检查。当前设计不是用户最终视觉签收。Windows运行截图由`desktop/tests/windows-developer.mjs`生成到CI产物的`developer-ui`目录；Linux环境浏览器下载被网络返回内容阻断，不将其算作视觉通过。

Windows初次运行截图b0a1460发现1028px窗口继承旧通用样式后标签竖排，且确认框被380px紧凑规则覆盖；已定点覆盖为开发页横排标签和420px弹窗。新增自然窗口/1440px/720px分别截图及窄窗标签中心线检查，等待新提交运行证据；不把修正前截图算作视觉通过。

06d8ca4 Windows截图已核对1440px两列布局、横排路径字段、420px确认框及空账本价格维护页，和本项Figma结构一致；该轮在切回账本时失败，720px和封包完成截图尚未执行，不作为整体通过。

f30fa59 Windows实际开发窗口已完成两种按钮封包。母/子1440×884完成页及子版720×900窄窗截图已核对，路径换行、字段横排、按钮和完成产物信息符合设计结构；窄窗无横向溢出断言通过。原生客户区1028×749、dpr=1；1440/720为明确的CDP视口模拟，不冒充物理DPI。用户视觉/交互签收仍待完成，详见[本轮证据](../verification/P07-05-ci-evidence-03.json)。
