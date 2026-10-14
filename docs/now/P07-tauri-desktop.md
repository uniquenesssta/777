# P07 Tauri桌面界面与Windows交付

状态：执行中。用户2026-10-14 14:37:59（Asia/Shanghai）“开始P07”；前置P06已验收，基线为P06收尾`7a243d5d1d103ae968f27adb7f54fea41a64d9cb`。唯一阶段分支`stage/p07-tauri-desktop`。当前P07-01已实现，辅助及原实现Windows CI通过；本机原生窗口定位release误用Vite，生产特性/内嵌资源核对已修复，待新CI及本机/用户视觉交互验收；P07-02至04尚未启动。

设计权威来自本仓库`Figma@c517d8b3086932abe2dc01908e4dae3209b9f956`的[交接](../design/figma-handoff.md)、[状态](../design/figma-state.json)和[tokens](../design/figma-tokens.json)，Figma文件为[记账器](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu)。只使用当前页21:2及其中已确认的紧凑紫灰横向布局，不使用归档旧稿；未改写Figma文件。实现映射见[P07组件映射](../design/P07-component-map.md)。

目标：以Tauri桌面入口承载已验证的业务核心/服务，完整覆盖两版角色功能。依据：[主任务书](../MASTER_PLAN.md) / [架构方案](../RUST_TAURI_DESIGN.md)。

| ID | 实施与交付 | 可执行验收 | 恢复方式 |
| --- | --- | --- | --- |
| P07-01 | 报价编辑/反馈、管理员利润/价格、销售订单视图、分页详情、备注/作废、任务进度按功能目录实现；统一状态源和IPC DTO | 页面路径可达、返回定位保留；新增/修改价格使报价按规则过期；母子功能矩阵无遗漏；中断任务/网络失败状态清楚；UI无权威金额副本 | 保留Python客户端作为兼容回退，服务数据接口一致；不启动生产替换 |
| P07-02 | capabilities、CSP、必要命令/文件scope、服务会话及角色控制；不暴露任意SQL/shell/绝对路径写 | 直接invoke受限命令、伪造参数、未知窗口、非法路径、junction越界、销售读取成本/利润全部被拒；事件/日志也不泄露；后端重验所有写输入 | 权限配置与代码一起回退；不能临时开放全盘/全命令让测试通过 |
| P07-03 | 实现确认的截图/报价图、附件唯一保存、图标、中文字体、键盘、滚动与DPI；窗口关闭与长任务协调 | 100%/125%/150%/200%DPI、多屏、长订单、中文长路径；图片内容/金额完整且不覆盖；关闭不会遗留未知写；无图标资源时提示或明确降级 | 图片失败可重生成，不影响订单；保留业务输入草稿 |
| P07-04 | Windows安装包、WebView2检测/安装策略、非管理员启动、配置迁移、卸载保留数据、更新/回退；锁定前端和Rust依赖 | 干净目标机安装启动；WebView2缺失/离线情形有可执行方案；升级保留配置/数据；回退版本兼容检查；CI与实机证据分列 | 保留上一安装包和配置/数据库备份；卸载不得顺带删除用户账本 |

P07-01采用Tauri 2.12.3、React 19.3.0、TypeScript 5.9.3、Vite 8.3.4与Radix Dialog 1.3.1，精确版本及依赖锁已建立；用途/替代/许可与实际构建大小见[实现契约](../verification/P07-01-desktop-contract.md)及[依赖清单](../verification/P07-01-dependencies.json)。默认不新增自动更新服务器、付费服务或远程UI加载。

退出门槛：管理员和销售两条完整真实链路（报价→提交→查询→按权限备注/作废→报表→恢复）、Windows安装/退出及权限测试通过，用户视觉/交互验收完成；不能用截图或构建替代功能验收。P08负责真实历史数据切换，P07不提前宣布已迁移。

## P01-03确认后的存储与备份界面

P07-01按[目录/备份定义](../baseline/P01-03-directory-backup.md)实现“设置 → 存储与备份”：完整路径、用途、来源和保存/备份状态可见；管理员管理主机账本/备份，销售只设置自身服务连接；导出/图片位置由管理员发布，销售显性查看、自动继承且不可修改。取消旧E盘业务路径隐性fallback，保存后重启生效。

P07-02验证销售直接invoke改主机账本/备份、读取含成本备份均拒绝，路径选择走受控能力。P07-04迁移独立设置、改安装目录/升级后保留用户已选路径，卸载保留账本和备份；隐藏属性/权限失败显示实际状态。目录变更只切设置，数据迁移另走可审阅的维护流程。

## P07-01当前交付与验证入口

[实现契约/Windows步骤](../verification/P07-01-desktop-contract.md)、[启动依据](../verification/P07-01-start.json)、[检查证据](../verification/P07-01-checks.json)。报价与反馈、订单完整分页/详情/追加备注/管理员作废恢复、价格发布/利润视图、报表图片任务和存储备份页面已经接真实Rust HTTPS宿主；无前端权威金额、直接数据库或通用文件/HTTP命令。客户输入在草稿中保存；会话/成本/权威结果不进入草稿。

P07-02专项边界审计、P07-03多DPI/原生图片及字体、P07-04安装升级仍按上表执行。已实现的最小CSP/capabilities/DPAPI不等于02已验收；浏览器辅助截图也不替代Windows WebView2或用户视觉验收。P08真实部署/历史切换未启动。

本机入口已修复静默/高并发问题：默认`--jobs 1`、环境预检与实时日志；`--preflight`只查环境、不下载/编译。`--windows-smoke`执行必要release构建与真实协议/原生窗口，完整lint/unit/浏览器检查在`--ci-checks`执行。原第一次窗口回传为中断，不能记通过；[工具修复证据](../verification/P07-01-runner-checks.json)和[原CI通过](../verification/P07-01-ci-evidence-01.json)分列。

本机release页面来源修复见[证据](../verification/P07-01-release-checks.json)：默认custom-protocol、release拒绝开发模式、CI实际exe资源核对、WebView2先验tauri.localhost来源；Tauri CLI常规dev保持Vite。原CI的build/业务结果继续有效，不能替代未覆盖的release原生页面。下一次本机输出使用p07-01-windows-03，01继续待验收。
