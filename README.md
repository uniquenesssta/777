# 记账器 / 报价利润计算器

- [P08-02-3 本机离线正式入账与主服务器合并任务书](docs/now/P08-02-3-offline-orders.md)：A/B 已交付，C 对应 Windows CI #83 已直接核实成功；D 本机正式订单、稳定保存回执和独立原生续传已完成源码及 Windows CI #86 验证（四个功能任务成功，安装包专项按约定跳过）。E/F/G 及现场验收继续保留。目标为断网本机保存正式单，联网自动上传，由 4.23 去重与处理冲突；Excel 历史金额红色、最终确认金额黑色，界面沿用现有修改记录。正式端界面保持现状，Figma 仅用于按需新增的开发者界面；优先补齐 4.23 后台处理，共享 backup 仅存备份。CI 提交后正常触发，不轮询或等待；用户报告结果后按对应提交读取一次核实，未核实不写通过。

- [P08-02-2 固定主服务器、选择式封包与安装自动接入任务书](docs/now/P08-02-2-automatic-installation.md)：A 协议、B 后台源码与隔离检查已完成；A–G 源码/设计及针对性检查已交付，正式端不生成日志，现场未验收。固定 4.23，母版集成后台部署与同账本加入，子版自动接入，日常免填连接和账号，统一业务数据备份名称。

- [P08-02-1 Host 接入、开发者数据读取与正式端设置](docs/now/P08-02-1-desktop-host-integration.md)：[Figma 设计](docs/design/P08-02-1-host-desktop-figma.md)及核心源码已接入，[填写说明](docs/verification/P08-02-1-operator-guide.md)已补齐；[Windows 功能检查已通过](docs/verification/P08-02-1-windows-checks.json)，旧节点身份兼容缺口、用户视觉签收与现场验收待完成；覆盖连接导入、任意位置兼容数据读取、独立封包目标、正式端目录保存但不应用、设备登记及现场业务闭环。

2026-10-17已按用户“开始推进02”进入P08-02，前序已启动[P08](docs/now/P08-cutover.md)，唯一执行分支 `stage/p08-cutover`，基线 `aca4ce3`。用户确认无历史订单，历史迁移范围为0；服务连接优先级按用户最新指令规划为192.168.4.23→192.168.4.38，封包母版设置隐藏4.23地址（已接入并通过Windows功能回归，自动主备切换待实现），首批母版1台。协议/身份/备份格式已按源码登记，实际主机运行账户、自启动、目录和设备映射待落实。P07按接续指令转接归档，未补造05/06单独签收或07增补Windows结果；仅母子安装包及其构建准备专项验证跳过；Host 部署、同步、备份恢复、运行与界面等其他验证照常执行。

当前业务基线是两份 Python + Tkinter 脚本：每日汇总母版，以及读取共享 JSON 价格的子版。`master` 基线提交为 `32e164d78643de8fa6cbd21a7ca634e1b318f855`。

- [P01-01运行基线与Windows检查](docs/baseline/P01-01-environment.md)
- [P01-02业务决策、金额示例与权限矩阵](docs/baseline/P01-02-decisions.md)
- [P01-03只读样本采集与部署登记](docs/baseline/P01-03-data-deployment.md)
- [P01-04黄金样本、技术参数与Windows验收](docs/baseline/P01-04-validation.md)
- [P02计算核心与归档任务书](docs/old/P02-calculation.md)
- [P03文件安全归档任务书](docs/old/P03-file-safety.md)
- [P03-01验收记录](docs/verification/P03-01-acceptance.json)
- [P03-02格式契约与本机入口](docs/verification/P03-02-format-contract.md)
- [P03-02 Windows复查通过](docs/verification/P03-02-windows-evidence.json)
- [P03-03设置契约、使用方式与Windows一键检查](docs/verification/P03-03-storage-contract.md)
- [P03-03 Windows本机复查通过](docs/verification/P03-03-windows-evidence.json)
- [P03-04订单备注、作废恢复与Windows一键检查](docs/verification/P03-04-order-contract.md)
- [P03-04 Windows本机复查通过](docs/verification/P03-04-windows-evidence.json)
- [P07转接归档：Tauri界面与追加功能](docs/old/P07-tauri-desktop.md)
- [P06 Rust领域核心归档任务书](docs/old/P06-rust-core.md)
- [P06-01契约与Windows运行步骤](docs/verification/P06-01-core-contract.md)
- [P05数据与服务归档任务书](docs/old/P05-data-service.md)
- [P04-01后台任务契约与Windows入口](docs/verification/P04-01-background-contract.md)
- [P04-01首次Windows失败证据](docs/verification/P04-01-windows-evidence-01.json)及[清理修复辅助检查](docs/verification/P04-01-cleanup-checks.json)
- [P04-01第二次Windows回传](docs/verification/P04-01-windows-evidence-02.json)及[控件修复辅助检查](docs/verification/P04-01-controls-checks.json)
- [P04-01 Windows本机与实际后台Tk联测通过](docs/verification/P04-01-windows-evidence-03.json)
- [P04-02统一读取、增量索引与Windows入口](docs/verification/P04-02-incremental-contract.md)
- [P04-03完整分页、明确图片范围与Windows入口](docs/verification/P04-03-pagination-contract.md)
- [P04-03首次Windows编码失败证据](docs/verification/P04-03-windows-evidence-01.json)及[修复检查](docs/verification/P04-03-encoding-checks.json)
- [P04-03 Windows本机分页/图片及实际母子窗口联测通过](docs/verification/P04-03-windows-evidence-02.json)
- [P04-04同数据性能对照与Windows入口](docs/verification/P04-04-performance-contract.md)
- [文档与计划入口](docs/README.md)
- [优化及迁移主任务书](docs/MASTER_PLAN.md)
- [两份 Python 代码重新审计报告](docs/audit/python-audit.md)
- [业务与数据迁移契约（业务规则v1）](docs/MIGRATION_CONTRACT.md)
- [Rust + Tauri 架构与切换方案](docs/RUST_TAURI_DESIGN.md)

## Change Log

- 订单记录取消沿用详情对象造成的整行高光；全部订单补齐微信号及行分隔，客户视图按真实客户组显示独立卡片、汇总和带表头的订单表。现有 Figma 同步，57 项单测、10 项针对性浏览器回归通过（其中 3 项走真实 Rust/HTTPS 业务）；Windows 实机未验。见[订单列表区分优化](docs/verification/P08-order-records-clarity.md)。

- 按最新要求让已允许的导航不再随业务会话消失；开发者连接弹窗增加“切回本机开发数据”，自动使用启动器当前账本/证书/身份，重连保留当前页面。57 项单测、45 项不同 UI 回归及两条真实原生恢复/离线链通过辅助验证，Windows 现场未验；见[修复证据](docs/verification/P08-02-3-source-navigation.md)。

- Host 注册防火墙核验兼容单值/数组及 TCP 编号，记录真实字段差异，并移到停止后台之前；真实冲突保留拦截。Host 打包逻辑 3 项通过，新增 6 项 Windows 回归尚未执行，4.23 现场待复验；未改开发者本机接入，不处理或轮询 CI。见[修复与验证](docs/verification/P08-02-2-registration-firewall.md)。

- 报价明细隐藏销售单价/K，商品与折扣可拖动排序；价格维护增加“参与折扣”，贯通在线/离线计算、历史冻结及备份恢复。客户匹配改为全部识别字段并直接弹出选择，提交失败提供有效重试/重新核价，无需改面积。Figma 同步更新；112 项相关测试通过，Windows/现场待核实，E 仍暂停，不轮询 CI。见[实现与验证](docs/verification/P08-quote-discount-recovery.md)。

- 修复 Windows 跨盘封包资源丢失盘符：将资源暂存到项目构建目录，以相对 `src-tauri` 的路径交给 Tauri，并统一签名清单的资源基准；本次运行日志补入限量构建错误摘要，收敛签发状态轮询。更新后点击上方“封包母版/子版”创建新任务，旧失败任务保留。见[资源与日志修复记录](docs/verification/P08-02-2-local-signing.md#跨盘资源与构建日志修复2026-10-20)。
- 修复开发者点击封包后立即报 `UNEXPECTED_ERROR`：仅提交封包所需的三个设置字段，避免把保存配置中的业务目录和格式标识送入严格接口；参数拒绝改为可记录的结构化错误，正式端仍禁用诊断日志。回归覆盖真实完整配置及默认/改目录/母子切换；见[修复证据](docs/verification/P08-02-2-local-signing.md#封包按钮请求修复2026-10-20)。
- 本机签发封包：移除开发者“封包授权”前置流程，断开 4.23 仍可在本机签发母版/子版及权限；Host 普通部署包配置验签与固定证书首次接入，保留原账本/8477 证书。加入绑定缓存、离线安装等待和旧协议兼容，Figma 同步移除旧授权页面。见[修订与验证](docs/verification/P08-02-2-local-signing.md)。E 暂停，现场未升级，最终封包专项不执行，提交后不轮询 CI。

- E 前 UI 修整与封包授权诊断：开发者入口重新命名，订单/导出操作与空状态对齐，授权页收拢；连接失败重试保留原升级包，更换材料单独确认；区分 8478 临时绑定与 8477 正式服务失败。构建、48 前端单测、15 UI 回归、2 控制器回归及原生失败保全检查通过，现场与新 Windows CI 待核实，不执行最终封包专项、不轮询。见[实现记录](docs/verification/P08-02-1-implementation.md)。

- 高度与开发连接修复 `c47865e` 的 Windows CI #88 已直接核实通过：四个功能任务成功，Windows release、63 项浏览器回归、真实默认身份与会话续接、实际 Tauri/WebView2 交互和清理通过，最终安装包验证按约定跳过。现场/视觉验收及 E/F/G 继续保留，见[核实记录](docs/verification/P08-02-1-implementation.md)。本次仅补齐证据，不轮询后续提交。

- 修复报价、利润、导出、存储与发行维护随窗口高度伸缩：列表内部滚动、导出分页固定在卡片底部、小窗口操作可达、图表缩放重新计算。开发连接移除账号密码填写，默认/已保存身份自动认证，支持重开和会话续接；一母一开发者一子及母版业务核对的最新范围记入任务书，E 尚未实现。63 项浏览器回归、真实原生 HTTPS 和相关源码检查通过，Windows/现场待核实，不轮询 CI。见[实现与证据](docs/verification/P08-02-1-implementation.md)。

- P08-02-3 D Windows CI #86：直接核实 `5e9af9c` 对应四个功能任务均成功，并读取原生日志确认 37 项 Windows 本机测试、双角色真实 TLS 断网续传及清理通过。D 源码及 CI 验证收尾，E 未启动，F/G 恢复与现场容量/登录生命周期保留。见 [核实记录](docs/verification/P08-02-3-D-ci-confirmation.json)。本轮仅更新证据和状态。

- P08-02-3 D CI #85：三个功能任务通过，原生编译及 37 项 Windows 本机测试通过；余下原生联测被 Python SQLite 检查连接未关闭阻断。统一检查连接的明确释放，保留全部数据与清理断言，增加正常/异常退出回归；完整指纹留报告，控制台仅输出摘要。修复后完整辅助原生 TLS 流程及清理通过，Windows 新结果待核实，见 [修复记录](docs/verification/P08-02-3-D-ci-fix.md)。

- P08-02-3 D CI #84 修复：独占借用满足原生异步 Send 约束，新增可在辅助平台拦截原错误的编译期约束；测试先关闭数据库再删除目录，原业务断言和所有 CI 门槛保留。三个角色本地自动测试及严格分析通过，Windows 修复结果待新 CI，提交后不轮询。见 [修复说明](docs/verification/P08-02-3-D-ci-fix.md)。

- P08-02-3 D：真实登记及 Host apply 后，本机正式单、上传原件和保存回执同事务；重开找回原单，独立原生后台静默上传并拉取授权确认/修改记录，未决改动保全。正式端界面与无问题日志策略保持，无 Figma/最终封包验证。C CI #83 已直接核实成功；D 新 Windows CI 未读取，F/G 恢复及容量门槛保留。见 [D 实施](docs/verification/P08-02-3-D-local-orders.md)及[检查登记](docs/verification/P08-02-3-D-checks.json)。

- P08-02-2 F/G：统一业务数据备份；未完整/失败结果静默，后台短周期探测恢复并补写原快照；开发/独立维护日志有限归并并支持离线关闭授权补偿。按用户最新要求，正式母/子版及随附后台不生成日志文件。见[F/G 实现说明](docs/verification/P08-02-2-FG-implementation.md)，Windows/现场未执行。

- P08-02-2 C/D 与 E 运行界面已接入：选择式发行、母版后台自动加入、两版独立设备接入；见[源码与针对性检查](docs/verification/P08-02-2-CD-implementation.md)及[新操作顺序](docs/verification/P08-02-2-automatic-installation-guide.md)。F/G 待收尾，Windows/现场未执行。

- 创建 P08-02-2 任务书：固定 4.23 主服务器、选择式封包、母版安装集成同账本后台部署、子版自动接入、自动身份与授权、业务数据备份命名和有限日志；A 协议及 B 后台源码/隔离检查已完成，见 [A 契约](docs/contracts/P08-02-2/README.md)；B 的后台能力见 [实现说明](docs/verification/P08-02-2-B-implementation.md)，安装器接入待 C/D；不执行现场升级或已取消的 Windows 母子构建验证。

- P08-02新增同账本主机加入与持续异步同步：manage.cmd菜单8启用现有主机并保留账本/证书升级，9导出一次性加入文件，10在新电脑新目录加入，11查看状态，12撤销节点。服务电脑无需开发者版/SDK或共享业务目录；开发电脑本轮须重新执行npm run package:host。固定主机处理业务，从机保存一致副本；自动故障接管与有序客户端切换仍待实现。Windows双真实TLS节点11组检查、相同产品源码完整桌面回归、14项部署及43个Rust协议测试通过，母子安装包验证跳过；4.23/4.38现场尚未执行本轮升级加入。见[操作说明](deployment/bundle/README.txt)、[协议与边界](docs/verification/P08-02-sync-protocol.md)和[检查证据](docs/verification/P08-02-sync-checks.json)。

- P08-02部署修正：服务电脑只用独立后台包，无需开发者版或Git/Node/Python/Rust SDK。开发电脑执行 `npm run package:host`，任意Windows服务电脑解压后双击 `setup.cmd` 选择本机地址和目录并部署，`manage.cmd` 中文管理，`check.cmd` 检查连接，`collect.cmd` 保留采集；不搬开发数据库/账号。用户确认4.23、4.38均为Windows，运行身份仍需在目标机采集；主备复制与接管待完成。[操作说明](docs/verification/P08-02-deployment.md)。

- 推进P08-02：新增独立Windows后台采集/准备、失败补配、开机任务和正常启停入口 `npm run deploy:host`；正式母版设置对4.23路径显示业务名称，选择/保存保留真实路径，设置与导出页按职责拆分。修复上轮浏览器测试的多按钮定位及Windows路径别名下的部署目录重叠校验。主备复制/自动接管和真实部署未完成，母子构建准备验证不重跑；见[部署说明](docs/verification/P08-02-deployment.md)。

- P08-01新增需求：服务地址优先192.168.4.23、其次192.168.4.38；封包母版设置不展示4.23地址及配置，开发者管理实际配置。任务书登记主备数据一致性、单写入主机和提交结果核查门槛；当前单地址实现保持，本次仅记录需求，未实现自动切换或数据复制。

- 按用户最新指令将P08-01服务主机改回192.168.4.38；普通备份候选仍为 `\\192.168.4.23\共享\backup`。同步任务书、部署登记与当前索引；本次仅调整部署计划，未连接或改动实际主机。

- 启动P08-01并建立 `stage/p08-cutover`：登记无历史订单、主机192.168.4.23及首批1台母版；冻结现有服务/设备/恢复数据协议，列明实际部署资料缺口。P07转接归档并保留原验证边界；本轮仅文档与源码基线核对，未导入数据、封包或部署。见[P08任务书](docs/now/P08-cutover.md)。

- P07-07增补：订单修改记录可展开查看字段/明细位置的前后差异；大范围内部财务报表自动按月及完整订单拆分，各文件标明批次，导出记录可翻页并独立重试。小报表仍生成一份，历史文件不改写；启动仍为 `npm run dev`。母子封包检查继续跳过。详见[实现与边界](docs/verification/P07-07-implementation.md)。

- P07-07本机编辑回传修复：同单查看修改记录后恢复草稿，确认框继续编辑返回工作台，明确放弃才切换；补齐有限前端状态/异常日志并区分预览/保存路由。真实React状态与原生链路已复现并验证修复，连续编辑/历史/客户汇总及重启通过；[证据](docs/verification/P07-07-edit-regression.json)保留边界，待本机复查，不收尾07。

- 按用户19:48指令，P07自动检查默认跳过母版/子版构建与安装包验证；保留订单、Excel、日志及界面检查，不再把本轮封包作为07交付门槛。

- P07-07实施：完成Figma四个主视图及六种状态；客户下多笔独立订单、原单版本编辑/历史成交价、月表日分组Excel、期间内部报表及实际目录跳转、每次启动单独日志目录已接入。账本与数据备份升级v2并兼容v1读取；实际辅助IPC/HTTPS、恢复及旧导入检查通过，Windows功能检查仍在运行，母子构建已按用户要求取消；用户验收待完成。见[实现与使用说明](docs/verification/P07-07-implementation.md)。

- 建立P07-07任务书：可读月/日Excel、淘宝ID/微信号下多订单归集与续编、Figma先行、财务导出目录跳转和每次启动独立集中日志。仅规划，未改业务代码或制作Figma；既有订单/备份保留。

- P07-06修复重新保存备份位置失败：当前普通备份目录缺少`777-backups.json`时，显式保存会按原目录标识补建索引，避免隐藏位置验证成功后整次配置被回滚；旧备份及其他文件保留，现有损坏/身份冲突索引不覆盖。拉取后重新启动，保存备份设置并生成今日备份。

- 开发启动简化为仓库根目录的`npm run dev`（在`desktop`目录执行也可）；继续使用原服务、日志及退出清理流程。Tauri内部和浏览器验证改用`dev:web`启动Vite，避免递归启动桌面。

- P07-06追加运行日志：按用户要求不改UI/Figma，开发运行统一写入项目根目录`logs`；桌面、主机、账本和开发控制记录生命周期、操作结果与文件系统原始错误。重复事件60秒合并，单文件4 MiB、每类保留当前及4份轮转文件；不记录请求/响应业务正文或凭证，不清理备份。Windows验证及用户共享目录复现仍待核对。

- P07-06按用户“任何可选文件夹”要求统一目录规则：本机、UNC、映射盘、移动盘及目录连接可用于数据/备份/输出；已有备份目录不再要求为空，保留文件/属性/权限，封包采用所选位置下唯一子目录，保存在源码目录内的产物也不会干扰后续封包。业务保存页提示同步改为任意保存目录。网络账本改用回滚日志，目录错误明确分类。新增Windows真实SMB、映射盘、Hidden/System与连接目录回归；测试数据目录误随封包输出进入源码目录的问题已修正，a0ad75c Windows三个任务全部通过，含双格式恢复、母子封包安装升级回退及既有业务检查。详见[目录验证记录](docs/verification/P07-06-paths-evidence.json)，未收尾06。

- P07-06源码5662c76的Windows三项检查全部通过：实际双格式/双位置备份、独立恢复读取、失败补写与权限边界，以及母子开发窗口封包/安装升级回退完成。首轮路径误判失败保留；小型证据包哈希与源码指纹已核对。任务书和[最终证据](docs/verification/P07-06-ci-evidence-02.json)已更新，实际Excel/WPS与用户验收待完成，05/06不自动收尾，P08未启动。

- P07-06首轮Windows实际窗口发现短路径与完整路径指向同一备份目录时保存失败；已修复目录身份比较并保留新位置空目录校验。失败证据归档，修复待Windows重验，06不收尾。

- P07-06按实施指令先补Figma每日双格式与导入框，再实现`.qbackup`逻辑恢复+独立Excel、普通/隐藏两处同快照、按日去重与失败补写、开发者私有路径配置及新目录实际恢复。停止新建完整服务包与升级触发备份，旧备份保持。真实原生服务的双位置失败/重试、导入读取及31项HTTPS回归已通过本地辅助检查；Windows与用户验收待完成，05不自动收尾，P08未启动。

- P07-06按用户补充改为每日双格式：软件可导入恢复的数据文件和独立阅读Excel，同一快照在普通/隐藏位置各保存一套。加入实际恢复、兼容导入及不覆盖现用账本的验收；仍不备份程序、不增加历史管理页。本次仅修订任务书，实施待启动。

- 创建P07-06任务书：只保留每日Excel业务备份和开发者预设、母端不可见不可改的隐藏副本；取消拟议滚动/完整服务包/程序文件/备份管理界面。明确独立可读、字段完整性、双位置失败处理及未定时间/留存；本次仅文档，旧备份不动，未启动实现。

- P07-05按任务书先补齐六种Figma状态，再接入开发部署UI、受控目录读取/初始化、备份位置完整恢复验证、数据源草稿隔离和未知请求保护、Windows后台母子真实封包及Job取消。增加真实debug IPC/HTTPS检查与Windows按钮封包CI；区分开发本机文件夹和业务共享目录，空账本通过真实服务能力允许首次价格维护；正式前端排除开发UI，原生能力仅debug存在。f30fa59 Windows三个任务全部通过，真实母子UI封包/安装回退、Windows DPAPI下A/B账本读取与备份恢复、33项前端/26项浏览器及既有业务回归均通过；本次仅追加文档记录。用户视觉/交互签收待完成，P08未启动。

- 按用户要求先建立[P07-05任务书](docs/old/P07-tauri-desktop.md#当前追加任务p07-05-开发者存储与一键封包-ui)，明确Figma先行、开发版存储/备份路径设置及真实读取、母子真实封包、失败/草稿/未知请求保护和验收清单；同步now及P08前置。原01至04验收保留，本次只改文档，尚未修改UI/原生能力或开始P08。

- 按用户“P07-04收尾”登记[04验收](docs/verification/P07-04-acceptance.json)和[P07阶段交接](docs/verification/P07-acceptance.json)，归档任务书并修复入口链接。最新Windows三项CI全过，母子实际安装/升级/卸载/兼容回退及登记通过；目标环境实机观察保留交P08，本轮未启动P08或切换真实数据。

- 修复P07-04母子登记脚本在Windows找不到`Get-FileHash`而中止的问题：使用系统.NET流式SHA256，保留交付文件校验、逐设备登记和profile保护；新增Windows回归并前置到安装CI。首轮两种NSIS已构建，后续安装生命周期待重跑，[失败与修复证据](docs/verification/P07-04-ci-evidence-01.json)。

- P07-03按用户指令收尾并启动04：新增固定manager/sales的Windows NSIS封包、公开连接导出/单设备登记、独立安装标识和稳定凭证/草稿目录、交付哈希清单、升级卸载及兼容回退门槛。沿用现有依赖，[命令与验证边界](docs/verification/P07-04-packaging-contract.md)；实际Windows与目标机验收待完成，P08未启动。

- 核对并登记当前Figma价格页版本的Windows CI通过：29项工具回归、24项前端测试、26项浏览器检查、16项业务协议及12项设备协议，母子原生入口、完整报价图和自然关闭通过。[证据与范围](docs/verification/P07-03-ci-evidence-03.json)。P07-02原验收保持，继续03；物理缩放/多屏及用户视觉待验收，04/P08未启动。

- 按已确认Figma四状态稿接入价格维护：双层表头、右侧独立售价、右上添加/自动聚焦、紧凑发布确认；切换成本×K保留尚未发布的手填值。沿用原精确预览/发布接口；[设计与验证](docs/design/P07-price-maintenance-figma.md)，新版Windows与运行界面验收待完成。

- 重做价格维护：成本/K在左、最终销售单价独立在右，支持手填或勾选成本×K，避免售价再次乘K。报价页直接加行、行内下拉换商品，表头/数值使用统一列与边距。旧价格和历史订单保留原算法/金额；新模式贯通Rust、Python独立核对及销售过滤。[规则与验证](docs/verification/P07-03-price-editor-checks.json)。同一P07-03继续执行，待新版Windows CI/用户观察，04/P08未启动。

- 按最新截图移除所有页面提醒条；操作失败改为无条形样式的文字，原请求核查/重试移入报价操作区。利润分析补齐柱状图、折线图、饼图、K线图切换，共用当前时间筛选与汇总；K线由服务计算累计利润开高低收，饼图明确标出亏损。[口径与检查](docs/verification/P07-03-chart-checks.json)。同一P07-03继续执行，待新Windows CI/用户观察，04/P08未启动。

- 按用户确认把利润快捷时间改为近1天/1周/1月/1年，以当前北京时间向前回推；独立选择图表日/周/月/年分组，快捷刷新跟随当前时刻，自定义范围保持固定。服务精确过滤起止时刻，兼容旧整日查询；月底/闰年校正。[规则与回归](docs/verification/P07-03-time-range-checks.json)，03继续执行，04/P08未启动。

- 根治开发启动后`Cargo.toml`反复变脏而阻止拉取：显式补齐Tauri CLI自动插入的`tauri-build.features = []`。实际锁定启动器复现旧版改写，修复后dev/build对LF和CRLF均不再改写；Node22/24各19项通过，锁文件与依赖版本保持。[根因与回归证据](docs/verification/P07-03-manifest-checks.json)。已有本地改动仍先保存一次；本次Windows CI待核对，03继续执行。

- 按用户截图调整P07-03：[两条提示移除、母版共享目录弹窗、导出记录说明及独立利润图表](docs/verification/P07-03-business-ui-contract.md)。利润按日/周/月/年聚合全部有效订单，作废/恢复与旧价快照保持；子版目录只读继承。原6ad35ce的[Windows CI完整通过](docs/verification/P07-03-ci-evidence-02.json)已核对归档；本次新增行为待新Windows CI/用户验收，03不收尾，04/P08未启动。

- 修复P07-03开发启动因首次字体下载超时而卡住：启动只核验本地字体，缺失时显性使用系统字体并继续；完整构建仍严格准备字体，新增显式`fonts:prepare`和清楚的取消/失败提示。[辅助检查](docs/verification/P07-03-development-fonts-checks.json)中Node22/24各15项、构建及无缓存/禁止字体联网的真实Vite启动通过；Windows原生仍待验收。

- P07-03首轮Windows CI在字体测试的Node 22输出解析处失败；29项Python和前端构建通过，Rust/原生新门槛尚未执行。[原报告与修复证据](docs/verification/P07-03-ci-evidence-01.json)保留。字体测试改为独立收集并核对中文日志，普通开发/构建提示保留；同版Node 22.23.3辅助12项及构建通过，Node门槛/依赖锁/完整CI不变，待Windows复验，03不收尾。

- 按用户确认[收尾P07-02](docs/verification/P07-02-acceptance.json)，同一07分支接续[03界面/资源与退出协调](docs/verification/P07-03-presentation-contract.md)：窄窗口、长单滚动、键盘焦点和离线字体/原图标回退已实现；修复开发窗口结束连带终止服务，18477/29346、证书与开发数据保留。Python/Rust/前端/呈现辅助检查通过，新增Windows母子40行报价图片及慢连接关闭入口；原生、多屏和用户视觉待验收，04安装器/P08部署未启动。

- 按用户要求将桌面开发页端口统一为`29346`：同步Tauri、Vite、开发启动器、浏览器测试及fixture CORS。启动命令仍为`npm --prefix desktop run tauri dev`；固定Rust HTTPS服务继续使用`18477`及已有证书/开发数据。

- P07-02修正原生检查的提交后等待：[第二轮CI](docs/verification/P07-02-ci-evidence-02.json)已通过SQLite清理及12项Windows设备协议，失败为详情页等待不存在的“重新读取”按钮。现在检查真实详情控件及空闲状态，全部完成后才写交互成功报告；母子详情与忙碌/禁用状态的3项浏览器回归通过，仍待Windows完整自然退出验收。

- P07-02修复Windows检查清理失败：[原CI及定位](docs/verification/P07-02-ci-evidence-01.json)确认脚本未关闭SQLite连接导致WinError32；设备验证的三处连接与开发初始化连接现在显式释放，写入仍按事务提交。原始失败保留，新增初始化成功/异常释放回归；Windows无登录母子入口待重跑验收。

- 用户收尾P07-01并启动02：[01验收](docs/verification/P07-01-acceptance.json)保留旧证据；[02自动连接/设备契约](docs/verification/P07-02-auth-contract.md)交付固定本机开发服务与指定账号、原生母子模式、一次性设备登记/自动会话/撤销、销售隔离和v5完整恢复。`npm --prefix desktop run tauri dev`自动启动固定本机服务，无需再填地址/证书/密码。辅助通过，待Windows实际母子无登录窗口验证；未部署真实主机，03/04/P08未启动。

- P07-01导航按用户标注调整：价格维护、利润分析、报表与图片任务、存储与备份移至顶部主导航，当前项高亮；退出登录保留右上角账户菜单，角色可见范围保持。前端构建及模拟IPC浏览器导航/布局检查通过；本次Windows实机视觉待确认，未启动02。

- 按用户确认重排[P07任务书](docs/old/P07-tauri-desktop.md)与[P08交接](docs/now/P08-cutover.md)：开发版保留配置，封包明确母版/子版，正式版部署授权后无登录直达业务；02交付设备授权/自动会话及权限，03核对界面，04交付两种安装包。稳定actor与目录继承规则保持，新增要求待实现；本轮仅文档，原01自动证据保留，未收尾或启动下一项。

- P07-01自动门槛通过：[Windows CI](docs/verification/P07-01-ci-evidence-06.json)56项指纹匹配76934b4，24工具/52 Rust/9前端/10协议/7浏览器及真实Tauri交互、自然退出/清理全部通过，含提权WebView2 153 API启动。[本机05](docs/verification/P07-01-windows-evidence-05.json)非提权WebView2 155也通过：0.047秒自然退出、临时占用等待2.359秒后完整清理，无强制终止；原始日志保留，本机dirty状态不推定为干净源码。代码不改、无需重跑；01待用户视觉/交互确认，02至04/P08未启动。

- P07-01 CI原生启动修复：[cf9d0a8原CI](docs/verification/P07-01-ci-evidence-05.json)53指纹匹配，24项Windows工具回归、完整构建/协议/7项浏览器通过，原生CDP未连上；环境覆盖不足及异常被吞已定位。验证模式改用WebView2 API设置固定回环端口/临时UDF，保留普通发行入口；记录运行时/提权、底层连接错误与清理前窗口。微软Runtime150提权策略与现象一致，原CI未记录版本/提权，保留为推断。[辅助检查](docs/verification/P07-01-cdp-checks.json)通过，待新Windows CI/本机06，01未收尾。

- P07-01临时目录清理修复：[本机04](docs/verification/P07-01-windows-evidence-04.json)确认真实交互和主窗口自然退出通过（0.031秒/码0/无强制终止），剩余失败为删除WebView2 BrowserMetrics文件时WinError5。现仅在本轮已标记临时根内等待/重试占用释放，限20秒，目录实际删除才通过；分项诊断保留，清理错误不覆盖原流程错误。[专项检查](docs/verification/P07-01-cleanup-checks.json)保存，22项辅助通过、2项Windows专属留新CI；本机用新05目录复验清理，01不收尾。

- P07-01原生关闭工具修复：本机03已确认生产页面和10项协议通过，交互命令返回0后关闭超时；旧工具误向所属PID全部顶层窗口发送WM_CLOSE，包含Tao事件辅助窗口。现唯一定位主窗口、核验投递/自然退出，日志文件与进程等待分离；失败保留交互、关闭及强制清理的独立结果。[原回传](docs/verification/P07-01-windows-evidence-03.json)和[修复检查](docs/verification/P07-01-close-checks.json)保存。辅助18项通过、1项真实Win32夹具待新Windows CI；新CI同时执行实际Tauri/WebView2交互与自然退出，原release修复[CI已通过](docs/verification/P07-01-ci-evidence-03.json)，本机用新04目录复验，01不收尾。

- P07-01 release页面修复：用户定位实际exe仍加载127.0.0.1:1420，原构建未启用Tauri custom-protocol，release优化本身不切生产模式。现默认/显式生产特性、Windows release拒绝开发模式；CI新增执行实际exe核对index/JS/CSS内嵌资源，原生脚本先核对tauri.localhost来源并保存失败证据，再等登录控件。Tauri CLI默认dev仍移除该特性并使用Vite。11项工具回归、48 Rust、6前端测试、10协议/7浏览器辅助通过，[证据](docs/verification/P07-01-release-checks.json)保存；原两次Windows CI成功范围不冒充原生页面验收，待新CI及本机03复验，不启动02或生产替换。

- P07-01本机入口修复：用户回传KeyboardInterrupt并报告CPU满载；原脚本隐藏全部子进程输出，且本机重复整套debug检查/release编译，Clippy/test未限并发。现先预检固定工具链/MSVC/SDK/WebView2，显式下载Cargo.lock依赖，默认单任务/低优先级编译；本机只构建所需release并做真实协议/原生窗口，完整检查留CI。实时日志与步骤报告落盘，中断仅清理所属进程树、保留partial报告。[回传及证据](docs/verification/P07-01-runner-checks.json)保存，10项回归及Node 22.12完整辅助通过；原adfbf62的[Windows CI成功](docs/verification/P07-01-ci-evidence-01.json)有效，应用业务/Rust领域/Cargo.lock不改，前端manifest/lock仅校正Node门槛为22.12+，待工具新CI与本机窗口复验。

- 用户“开始P07”：从P06收尾7a243d5建立唯一stage/p07-tauri-desktop，任务书new→now；读取本仓库Figma@c517d8b当前稿，交付React/TypeScript + Tauri真实Rust HTTPS桌面链路、角色投影、完整分页详情、未知提交核查与原生输出任务。改动价格/输入立即失效；提交后刷新失败明确已保存，提交期间新编辑草稿保留。实现/辅助结果与初期失败见[P07-01契约](docs/verification/P07-01-desktop-contract.md)和[证据](docs/verification/P07-01-checks.json)，Windows-only CI与本机隔离入口已交付；Windows原生窗口、用户视觉交互尚待验证，02至04及P08未启动，未替换生产。

- 用户“收尾04”：登记[P06-04验收](docs/verification/P06-04-acceptance.json)及[P06阶段验收](docs/verification/P06-acceptance.json)，四项交付完成，任务书now→old；Windows CI/本机原报告与全部历史资料保持，无需重跑通过检查。本轮仅收尾，P07/P08待授权，后续界面/安装/真实部署与生产迁移交接保持。

- P06-04 Windows CI及本机隔离核对通过：128项源码指纹、212专项/43 Rust/561精确对照一致，原母子窗口、原生DPAPI/ACL/系统CJK图片及v4完整恢复通过。[原报告与核对](docs/verification/P06-04-windows-evidence-01.json)按字节保存；200单计算/查询p95分别49.31→8.08ms、13.60→7.27ms，采样主进程resident约38.0→11.2MB。已通过检查无需重跑，P06具备收尾条件待用户确认，P07/P08未启动，真实部署/安装与历史切换留后续。

- P06-04第四次CI的原生崩溃恢复已通过，新增生命周期测试误将Windows CRLF提示行按LF断言，212项中211成功/1项的2子项失败；[原报告与修复](docs/verification/P06-04-ci-evidence-04.json)保留。测试现在接受精确提示行的LF/CRLF，真实子进程覆盖两种换行和17/18退出码；旧断言复现相同失败，修复后5项辅助回归通过。产品代码和严格门槛未改，Windows CI及本机验收仍待完成。

- P06-04第三次Windows CI通过权限/固定旧工具及43 Rust/561对照，207专项中两项崩溃恢复在已关闭的stdin上触发EINVAL；[原报告与修复](docs/verification/P06-04-ci-evidence-03.json)保留205成功/3错误事实。验证夹具与资源入口统一使用communicate完成管道关闭和回收，保留退出码/超时检查；新增5项生命周期回归，11专项及完整协议恢复/双宿主小规模清理辅助通过，212项由新Windows CI复查，04仍待验收。

- P06-04第二次Windows CI的严格构建、42 Rust与561对照通过，权限读回及浅克隆缺旧源码导致专项167运行/97错误；[原报告与修复](docs/verification/P06-04-ci-evidence-02.json)保持。Rust/Python从原生ACE读取完整SID进行精确白名单核验，避免SDDL显示缩写误判；CI仅获取固定223e86e旧源码，保留真实离线兼容构建。新增身份/越权/释放回归，16专项/43 Rust及浅克隆归档通过；128指纹，推送触发新Windows CI，04未验收。

- P06-04首次Windows CI在目录校验的Windows专用分支被Clippy `needless_return`阻断，尚未执行协议/恢复验收；仅改为等价尾表达式，严格检查门槛保持。[原报告与核对](docs/verification/P06-04-ci-evidence-01.json)保留，辅助fmt/Clippy通过；推送触发新CI，本机Windows及用户验收仍待完成。

- 用户“收尾03 开始04”：登记[03验收](docs/verification/P06-03-acceptance.json)，同一分支交付[04独立Rust HTTPS宿主](docs/verification/P06-04-host-contract.md)，鉴权/查询/原生输出/v4恢复与原协议、单写账本兼容；127指纹、195专项/656完整辅助、42 Rust/561对照通过。[证据](docs/verification/P06-04-checks.json)保留初期失败与资源结果，辅助查询尾延迟仍待Windows核对；Windows-only CI已配置，本机原窗口/DPAPI/ACL/系统字体及用户验收待回传，P07/P08未启动。

- P06-03 Windows核对通过：fee8ea3干净源码的98项指纹、165项Python/32项Rust/561项对照与完整日志一致，原生Excel/DPAPI回执/HTTPS/v3恢复/目录权限通过；[原报告与独立核对](docs/verification/P06-03-windows-evidence-01.json)按原字节归档。03具备收尾条件待用户验收，无需重跑；04未启动，原辅助及历史证据保持。

- P06-03：Rust原始数字OOXML读取/新四表文本报表接入导入与输出，全字段/样式及原Plan/SHA/回执保持；未知/有损/公式源清楚复核。旧v3执行文件明确格式桥接，财务仍原生单写。165专项/626完整辅助、32 Rust/561对照及旧包/辅助HTTPS恢复通过，[本项Windows入口](docs/verification/P06-03-excel-contract.md#验证与windows入口)待复查；02已验收，无需重跑旧入口，04未启动。

- 用户“收尾02开始03”：登记[P06-02验收](docs/verification/P06-02-acceptance.json)，原Windows83指纹/65专项/25 Rust/561对照及原生恢复证据保持；同一stage/p06-rust-core从223e86e开始P06-03 Excel适配，无需重跑02，04未启动。

- P06-02第二轮Windows完整核对通过：bf18f45的83项LF指纹、65个专项ID/成功日志、25项Rust测试/构建及561精确比较匹配，逐项独立重算Python期望；原生DPAPI未知提交/原回执、旧HTTPS/角色投影、v3原生恢复/旧会话撤销与Hidden/System/ACL及清理通过。[原报告与独立核对](docs/verification/P06-02-windows-evidence-02.json)按原字节保存，首轮失败及修复辅助证据保持。02具备收尾条件待用户验收，无需重跑；03/04未启动，没有GUI/安装或真实数据切换。

- P06-02 Windows首轮：83指纹/65测试ID、Rust25项与561精确对照匹配，专项63通过/2处验证代码错误；[原报告与独立核对](docs/verification/P06-02-windows-evidence-01.json)保留。修复schema夹具SQLite连接关闭及平台模拟Path错误，65专项辅助回归全过；[第二轮Windows入口](docs/verification/P06-02-storage-contract.md#windows隔离检查)使用新02目录，原生DPAPI/ACL/备份恢复待验证，02不收尾、03未启动。

- P06-02：交付同schema的Rust事务账本/精确指纹重放、原生备份与内存导入计划、保持既有认证HTTPS的领域适配及离线后端选择；完整包v3保留worker/许可/输出队列，旧v1/v2兼容。65专项/594完整辅助、Rust25项与561精确对照通过；待Windows隔离验证，未切换真实数据或启动03。

- 用户“收尾01开始02”：登记P06-01验收，保留Windows32指纹/21项Rust/58项Python/561对照原证据；同一stage/p06-rust-core开始P06-02，保持ledger-v1与已确认HTTPS/角色协议。

- P06-01 Windows完整核对通过：32项LF指纹匹配ebf1a2c，原生MSVC固定Rust1.97.1的fmt/Clippy/test/release构建通过，Rust21项/Python58项零失败/跳过；561/561对照逐例请求与双方结果SHA独立重算一致，含原黄金53/53。原报告和比较文件按字节归档，[核对证据](docs/verification/P06-01-windows-evidence-01.json)已保存；具备收尾条件待用户验收，无需重跑，02未启动。

- P06-01：从P05收尾7710132建立唯一stage/p06-rust-core，任务书new→now；交付独立精确Rust金额/配置/草稿核心、锁定依赖许可与Python/Rust影子核对入口。黄金与Python生产链保持；53/53黄金在561/561精确对照中通过，Rust21项/Python58项与fmt/Clippy/release构建辅助通过，待Windows原生构建/用户验收；未启动02或Tauri。

- 按用户“收尾P05-04开始P06-01”登记04验收与P05范围交接，P05任务书now→old；52/52 Windows和原报告保持，真实部署及历史切换交接后续，授权建立唯一P06阶段分支。

- 登记[P05-04第二次完整Windows核对](docs/verification/P05-04-windows-evidence-02.json)：38项LF源码指纹/52测试ID及成功日志匹配959d5d6，52/52零失败/错误/跳过；实际排他文件锁/解锁原任务同SHA、订单不变、HTTPS/DPAPI回执、母子Tk的Excel/PNG/私有明细与只读继承、搜索统计、完整v2维护恢复、权限/关闭/清理全部通过。3单5明细、revision4、金额9200/4000/5200分一致；[原报告](docs/verification/P05-04-windows-report-02.json)按字节保存，原GBK失败、50/527及编码52项辅助证据保持。04具备收尾条件待用户验收，无需重跑，P05继续留now、P06未启动；真实部署与历史切换留后续。

- P05-04首次[Windows启动失败](docs/verification/P05-04-windows-evidence-01.json)：UTF-8清单误用默认GBK解码，尚未进入测试/原生流程、未产生报告。诊断清单/临时配置及新测试文本读写显式UTF-8，旧函数默认GBK复现；新增2项GBK读取/报告读回回归，[52/52专项](docs/verification/P05-04-encoding-checks.json)通过。业务/核心/账本和原50/527证据不改，使用新的windows-02目录复验，04不收尾、P06不启动。

- 按用户“收尾03开始04”登记[P05-03验收](docs/verification/P05-03-acceptance.json)，同一stage/p05-data-service实现P05-04：[账本报表/报价PNG、持久任务/补导出与完整v2恢复、认证搜索/签名分页和审计增量统计](docs/verification/P05-04-output-contract.md)，共用目录只发布报价字段，内部成本报表私有，原ledger-v1 DDL/财务revision和计算规则不改。原请求跨回执核查、文件失败/中断不撤销订单、未知同名不覆盖；[跨语言样例](docs/verification/P05-04-protocol.json)保留精度/版本/权限/备份v1兼容。[50专项/527完整辅助](docs/verification/P05-04-checks.json)通过，38项实现指纹；待本轮Windows排他锁/Tk/CJK/权限/完整恢复验收，P05留now、P06未启动，不切换真实数据或部署。

- 登记[P05-03完整Windows核对](docs/verification/P05-03-windows-evidence-01.json)：41项LF指纹/50测试ID及全部成功日志匹配5a791d6，50/50零失败/错误/跳过；原生只读预演/原子导入、重复批次、原字节与映射、完整备份/独立主机恢复、Hidden+System受保护DACL和清理通过。2单3明细1备注、revision5、有效金额7500/3000/4500分一致；[原报告](docs/verification/P05-03-windows-report-01.json)按字节归档，源码和50/477辅助证据不改。03具备收尾条件待用户验收，04未启动，无需重跑已通过检查；真实历史及现场部署留后续。

- 用户“继续R5-03”按当前777任务书推进P05-03，同一stage/p05-data-service基线6a041f4；[P04收尾](docs/verification/P04-acceptance.json)和[P05-02隔离收尾](docs/verification/P05-02-acceptance.json)依据已通过原生报告与接续意图，真实主机/E盘/部署交接保持待办。交付[只读识别/预演与原子幂等导入](docs/verification/P05-03-import-contract.md)：identified/tagged/26列/别名重排/JSON，源行与稳定ID、备注/作废/原时间/价格/事件和原文件字节可追溯；业务核心逐行重验、差异/公式/歧义隔离，不自动改历史金额、现价或目录。管理员本机入口持有主机锁，先核验完整维护备份，原SHA/归属绑定及未知结果按原批次核查；原ledger-v1 DDL保持。环境缺少旧服务依赖导致首次全回归3组未启动，补齐既有锁定版本后[50专项/477完整及主机恢复辅助](docs/verification/P05-03-checks.json)通过，历史失败保留，原60项P05-02/43项P04源码指纹不改。Windows新隔离入口待回传，真实数据未导入，P05-04未启动。

- [P04正式06核对通过](docs/verification/P04-04-windows-evidence-06.json)：[原报告](docs/verification/P04-04-windows-report-06.json)2259815字节及SHA256 fd3c7cb14b54fdc736ce98e87c8b5583f71c968f0a9ad2abb16794ccde49fca8按字节归档，43项LF指纹/37测试ID匹配824ffe7。实际Windows本机/UNC各55进程，全档各5轮与旧版小档配对完成，450当前阶段全部达标；独立重算18080个原始间隔及全部轮次汇总。本机最差阶段p95/最大98.2681/144.1439ms，共享97.1443/145.6611ms；金额/完整页/末行/冷每文件一次/暖0/关闭/清理通过。打开中、大档目录明细的20个阶段各额外解码1文件如实保留，符合既有缓存契约；旧失败与563ms不撤销。P04正式共享待办已完成，整阶段具备收尾条件待用户确认，已停用明日重复验证提醒；程序/门槛不改，无需重跑，当前唯一P05分支及03/04未启动状态保持。

- 核对并按字节归档[P05-02完整Windows报告](docs/verification/P05-02-windows-report-01.json)：22811字节、SHA256 dbcb149a1da4b5a96b7b909fcc4f6cab529b62fc2f4a31de0ec0f5e180f74020，884c8cb的60项LF指纹和全部42测试ID一致，42/42零失败/错误/跳过，原生联测与前次控制台完全一致；[核对记录](docs/verification/P05-02-windows-report-verification-01.json)补齐隔离证据，旧摘要和历史JSON保持。用户授权[P04立即正式复验06](docs/verification/P04-04-resume-06.json)，不再等待原14日执行日期；当前唯一stage/p05-data-service无新分支，原42项P04源码指纹和门槛不变，原收集器额外记录P05显式适配文件后共43项。按原全档各5轮/小档旧版配对测本机和UNC合成临时目录，结果待本机回传；不重跑其他已通过任务、不声明共享性能或真实服务部署已通过。

- 登记[P05-02首次Windows控制台回传](docs/verification/P05-02-windows-evidence-01.json)：拉取至884c8cb并成功安装固定服务依赖，42/42零失败/错误；实际TLS1.3环回HTTPS、DPAPI原请求恢复、母子Tk提交/查询/只读目录、受保护Hidden+System目录、完整备份独立恢复和清理通过。3单5明细、revision4、收入/成本/利润11200/4800/6400分与隔离样例核对一致。仅收到控制台摘要，原report.json、60项源码指纹与完整测试清单尚未归档核对；不要求重跑。另登记[共享目录元数据](docs/verification/P04-04-shared-directory-observation-01.json)：目录可访问，Hidden/Directory，无显示的链接类型或目标；不替代P04共享性能验收，2026-10-14复验保留。程序和历史证据不改，真实服务部署及03/04尚未执行。

- 用户“收尾01开始02”：依据P05-01已通过的第三次Windows42/42及原生权限/恢复[收尾01](docs/verification/P05-01-acceptance.json)，同一stage/p05-data-service从84b881c交付[P05-02服务边界](docs/verification/P05-02-service-contract.md)。HTTPS证书链/主机名/指纹验证、scrypt账户与持久会话/epoch撤销、主体来源与角色允许字段、本人订单/备注/回执、CAS价格/目录和未知提交原请求查询重试；显式母子Tk服务入口复用原布局，提交/查询改走服务，子版输出目录只读自动继承，无共享成本读取或裸写Excel。主机私有目录与完整服务备份（账本/账户ID/设置/TLS）、独立维护恢复及旧会话/凭证失效、备份计划/本机失败状态已交付。[42专项/427完整辅助](docs/verification/P05-02-checks.json)通过真实TCP HTTPS双客户端和恢复、头部/JSON/角色与过期控制、原请求不重复和主线程交付；原20项P05-01及42项P04实现指纹保持。当前Windows隔离GUI/DPAPI待回传，未安装真实服务、移动旧账本或开启03/04；P04共享复验继续保留。

- 登记P05-01[第三次Windows通过证据](docs/verification/P05-01-windows-evidence-03.json)：20项LF源码指纹及全部42测试ID匹配9ce9f16，42/42零失败/错误/跳过；原生本机SQLite/幂等回执、备注/作废恢复、一致备份与独立恢复通过，恢复收入/成本/利润分别3600/1600/2000分。Hidden+System、3个允许主体的受保护DACL、额外Everyone授权移除、原生锁及临时清理全部通过；[原报告](docs/verification/P05-01-windows-report-03.json)按字节保存。前两次失败及385项辅助证据保持，程序代码未改，已通过检查无需重跑；P05-01具备收尾条件，02/03/04未启动，真实主机/E盘服务身份与多客户端部署留后续，P04共享复验继续保留。

- P05-01[第二次Windows回传](docs/verification/P05-01-windows-evidence-02.json)：20项LF指纹、40测试ID及schema匹配877e8af，32通过/8错误；前次DACL/连接清理错误消失，8处均为新快照只读rb句柄调用fsync导致EBADF，[原报告](docs/verification/P05-01-windows-report-02.json)按字节保存。仅将该应用新建快照改为不截断的r+b句柄，保持真实刷盘和失败阻断；新增受限句柄回归在旧实现复现同类失败，修复后内容不变/独立恢复通过，刷盘失败保留最近成功包、原订单和幂等回执。[42专项/385完整辅助](docs/verification/P05-01-fsync-checks.json)通过，现有P05分支拉取后用windows-03复验；原权限保护/计算/DDL/P04实现与历史证据保持，01及整阶段尚未验收。

- P05-01[首次Windows回传](docs/verification/P05-01-windows-evidence-01.json)：19项LF指纹、31测试ID与schema指纹匹配94f4d89；21通过/10错误，其中9处备份DACL核验、1处测试数据库未关闭导致WinError32，[原报告](docs/verification/P05-01-windows-report-01.json)按字节保留。新建专属目录改用原生SetNamedSecurityInfoW完整替换受保护DACL，读取核验精确主体、完整权限与子目录继承；测试/内存schema连接显式关闭。新增权限策略/原生调用边界及失败摘要回归，Windows联测增加额外Everyone显式授权移除验证；[40专项/383完整辅助](docs/verification/P05-01-security-fix-checks.json)通过，原计算/DDL/黄金与P04实现保持。现有P05分支拉取后用windows-02复验，未验收01或开始02/03/04。

- 用户确认P04正式05共享预检查失败原因为停电，授权先推进P05并保留明日共享复验；[转接记录](docs/verification/P04-04-deferral.json)保留P04整阶段未验收事实，P04执行计划移old且注明延期，P05唯一stage/p05-data-service从31c8784启动。P05-01新增quote_ledger本机SQLite v1结构/索引/版本指纹，订单重算复用既有核心，整数分与原文/规范化高精度参数持久化；request_id幂等、不同负载冲突、原子整单/审计、价格CAS、只追加备注与revision、作废/恢复和未知提交查询。新增一致性备份/独立恢复、只清理清单内过期备份、最近成功副本及维护备份保留、单身份调度入口；新建Windows备份目录设置并核对Hidden+System与服务当前身份/SYSTEM/管理员DACL。[31专项/374完整辅助](docs/verification/P05-01-checks.json)通过，真实SQLite进程退出/并发/53黄金入库或拒绝及数据不变检查；Windows属性/ACL与隔离恢复待[本机入口](docs/verification/P05-01-ledger-contract.md)回传。无服务安装、真实E盘/共享修改或客户端切换，P05-02/03/04留后续。

- P04-04[正式05回传](docs/verification/P04-04-windows-evidence-05.json)：42项LF指纹及37测试ID匹配55f359e，37本机检查通过；SHARED_ROOT_MUST_BE_EXISTING_DIRECTORY_WITHOUT_LINK发生于共享根预检查，本机/UNC零性能轮次，原报告按字节保存。不记为性能超限或通过；共享父目录元数据检查曾尝试，未读写生产文件。现有组合报错没有目录属性或底层WinError，无法区分不可访问/不存在与链接/联接点。先Get-Item只读核查指定根，确认真实可访问普通目录后再新建windows-06输出；不放宽路径门禁、不修改程序或重复已通过辅助测试，短诊断02十阶段及343项辅助仍有效，P04待正式证据，P05未启动。

- P04-04[短诊断02](docs/verification/P04-04-windows-latency-evidence-02.json)：f40e72b的42项LF指纹及37个测试ID一致，本机37项通过，母子10000行各一轮、10阶段心跳全部达标，最大124.7948ms；金额/完整明细/冷一次暖0/关闭/清理正常，1028次让步均为读线程事件。原报告按字节保留，全部原始心跳与重叠重新核算；两次独立合成运行工作簿哈希不同，不宣称严格配对改善百分比或统计因果。本次首读11.2308/11.1528秒、查看1.0814/1.2531秒，响应达标但总耗时有增加。[程序与343项辅助证据](docs/verification/P04-04-cooperative-checks.json)保持，无额外重测或继续调参；下一步正式本机及UNC全档各5轮，输出reports/p04-04-windows-05。单轮诊断不关闭P04，旧57个失败结果不改，P05未启动。

- P04-04[短诊断01](docs/verification/P04-04-windows-latency-evidence-01.json)：41项指纹/33个测试ID匹配07e5956，母子10000行各一轮完成，金额/冷一次暖0/完整分页/清理通过；首读p95 143.6565/128.1208ms、查看143.1392/141.6649ms，最大255.2839ms，原报告完整保留。长间隔集中于后台脱离单元格/汇总/视图构造，GC只解释部分时间重叠；据此新增Windows读取通道8ms预算/1ms暂停，线程本地且异常还原，写通道/主线程不启用，不保证原生解码或GC硬时限。分段记录真实cooperative_pause，不修改金额/读取/原始心跳或回收设置。[37项专项及完整343项辅助通过](docs/verification/P04-04-cooperative-checks.json)，包括真实1000行各端视图/末行筛选及Tcl五阶段；实机效果待短诊断02，暂不重跑全档、不收尾P04。

- P04-04第四次[Windows/UNC回传](docs/verification/P04-04-windows-evidence-04.json)：41项LF指纹匹配f728c99，26/26检查通过，110个进程全完成；两位置全档5轮/金额/完整明细/冷一次暖0通过，原/新版均记录1ms调度。翻页组本轮全部达标，但首读/查看仍有57个阶段p95超限，本机/UNC最大256.2393/256.2310ms，[原报告](docs/verification/P04-04-windows-report-04.json)保持。停止推测瓶颈，新增本机母子10000行各一轮的分段/线程CPU/GC与心跳重叠[短诊断](docs/verification/P04-04-performance-contract.md)，明确不作验收，不再安排第五次全档；钩子失败恢复、事件截断显性及普通验收5轮门槛有回归，[33项/339项辅助通过](docs/verification/P04-04-trace-checks.json)。应用/数值/事务及门槛保持，P04留now，P05未启动。

- P04-04第三次[Windows/UNC回传](docs/verification/P04-04-windows-evidence-03.json)：41项LF指纹匹配2cd9887，23/23检查通过，110个进程全完成、两位置当前全档5轮及原版小档完成；金额/完整明细/冷一次暖0通过，子版零超时、样本不足归零。450个当前阶段中60个p95超限、最大283.7558ms，[原报告](docs/verification/P04-04-windows-report-03.json)保留。Windows应用使用最多1ms解释器切换间隔，配对诊断原/新版一致且记录实值；仅为调度优化，不宣称已证明卡顿根因。分页复用未变列配置、每200行一次Tcl列表数据传递，保留用户列宽和原行身份，脚本样式文本不执行。[26项/332项辅助通过](docs/verification/P04-04-latency-checks.json)，待第四次实机性能复查，金额/写入/解析/缓存及门槛保持，P04不收尾、P05未启动。

- P04-04第二次[Windows/UNC回传](docs/verification/P04-04-windows-evidence-02.json)：41项LF指纹匹配145c223，20/20本机检查通过；母版/原版80个进程及340个阶段完成，6个子版进程超时，当前239个阶段心跳样本不足、17个样本充足阶段p95超限，最大428.6243ms。输入未改、临时清理正常，[原报告](docs/verification/P04-04-windows-report-02.json)全部值保留。修复子版刷新误调母版汇总控件，真实缺失控件纳入回归；新旧启动300ms回调在空目录中完成，实际采够20次回调且至少1.1秒，异常交付立即报阶段/原因并保留超时日志。[23项/完整329项辅助通过](docs/verification/P04-04-sampling-checks.json)，金额/写入协议及旧后台样本保持；待第三次本机/UNC实测，门槛不变，04及整阶段不收尾，P05未启动。

- P04-04首次[Windows回传](docs/verification/P04-04-windows-evidence-01.json)：41项LF指纹匹配b84d774，17/17检查通过；本机和UNC各11个窗口进程在页面定位时退出，0个性能阶段完成，输入未改且临时目录清理正常。[原报告](docs/verification/P04-04-windows-report-01.json)保留全部字段。诊断现直接选择既有excel_page，预演执行新旧四份入口实际标签配置，保留异常链/完整stderr，并区分请求全档与实际完成。旧实现可复现原错误，修复后[20项/完整326项辅助通过](docs/verification/P04-04-startup-checks.json)；业务源码/旧样本不改，待Windows第二次复查，100/500ms门槛不变，04和整阶段不收尾，P05未启动。

- 用户“开始04”：沿用已通过的Windows23项/实际母子Tk16项[收尾P04-03](docs/verification/P04-03-acceptance.json)，同分支交付[P04-04自动性能入口](docs/verification/P04-04-performance-contract.md)。9种工作负载各5轮辅助计数通过，冷读每文件一次、暖刷新零解码，金额和全部明细正确；新增17项/完整323项辅助通过及最终指纹另存。实际Windows阶段心跳及UNC性能待测；原563ms、最大500ms门槛和既有报告保留，业务源码不改，P04留now，P05未启动。

- 登记[P04-03第二次Windows回传](docs/verification/P04-03-windows-evidence-02.json)：37项LF指纹匹配3c614c7，23/23本机检查与实际母子Tk联测16项全过。两端10000明细完整可达（母版含6行表头/汇总等，共51页；子版50页），筛选/跳转/返回定位与后段备注保留选择及金额；实际完整报价图母版42条/2张、子版1条/1张全覆盖。当前设备HWND截图及遮挡前后完整报价图一致通过，无回调错误，关闭/线程退出/临时清理正常。[原报告](docs/verification/P04-03-windows-report-02.json)按原值保存；440个短会话心跳样本、最大563ms留待P04-04核对，不登记规模/SMB性能通过。首次失败、两份306项辅助及业务代码保持，03待用户验收、无需重跑，04未启动，P04留now。

- P04-03编码修复：首次Windows回传的37项LF指纹匹配1b03eb0，20/23通过、3处UTF-8清单被默认GBK解码，实际Tk未运行；[原报告](docs/verification/P04-03-windows-report-01.json)保留。诊断及测试6处清单读取现显式UTF-8，23项在GBK默认下/完整306项辅助通过，见[修复证据](docs/verification/P04-03-encoding-checks.json)。原3错误和母子控件同类问题可在旧实现复现，修复后通过；应用实现/金额/历史报告保持，03待第二次Windows复查，04未启动。

- P04-03：两端共用200行分页/搜索/订单筛选，移除母版300行/36列限制，刷新和换文件保留选择/位置；分页不影响金额及Excel输出。区分窗口截图与冻结全单报价图，长文字换行、连续多张/全单合计、销售图片不含成本利润；独占UUID目录和原验证发布，部分失败保留已完成图片并提示。新增23项及完整306项辅助通过，[契约与Windows一键入口](docs/verification/P04-03-pagination-contract.md)交付，待实际Tk/HWND复查；金融核心/黄金/事务与历史报告保持，04未启动。

- 用户“收尾02开始03”：依据既有Windows22项/实际母子Tk联测11项[收尾P04-02](docs/verification/P04-02-acceptance.json)，复用唯一stage/p04-performance开始P04-03完整分页/筛选、保留选择定位及明确附件范围。原报告和业务实现不改，已通过检查无需重跑；04未启动，P04留now。

- 登记[P04-02 Windows回传](docs/verification/P04-02-windows-evidence-01.json)：fe0c276的30项实现LF指纹匹配，22/22本机检查及实际母子Tk联测11项全部通过。4文件冷读4次、暖刷新0次，暖刷新源读取次数/字节数不增加；外部改单一次解码、删除零解码，真实备注写入仅重读目标，视图与精确金额通过。无回调错误，后台线程退出后清理正常，[原报告](docs/verification/P04-02-windows-report-01.json)按回传原值保存。67个短会话心跳样本、最大110ms仅作诊断，缓存计数不含事务/CAS必需读取；原283项辅助、计数样本及业务代码保持。02具备收尾条件，本次无需重跑，03/04未启动，P04留now。

- P04-02：基于01收尾796d74d复用同一分支；普通工作簿一次解码/每源Sheet一次遍历，摘要/分组/身份/历史及母子视图共用脱离句柄快照。双层有界索引（摘要2048文件/估算16MiB，完整视图64文件/估算64MiB）、文件身份/写入与变更时间/parser版本失效、不可信元数据回读、并发合并、目标写前后失效、目录切换/删除检测及变动金额差额；当前外部改变视图自动重读，删除撤销旧租约。新增22项/完整283项辅助通过，[计数样本](docs/verification/P04-02-read-profile.json)冷5/暖0/改单1/删除0、20/40行XML各1；[契约与Windows一键入口](docs/verification/P04-02-incremental-contract.md)交付，实际Tk步骤已用替代控件预演，待Windows复查。财务核心、53黄金、事务/CAS/回执与历史机器报告未改；03/04未启动。

- 用户“收尾01开始02”：依据既有Windows24项及实际母子Tk联测7项[收尾P04-01](docs/verification/P04-01-acceptance.json)，已通过检查无需重跑；在唯一stage/p04-performance复用已验收实现和9f25629证据提交，开始P04-02统一Excel解析、共享视图及按变更增量刷新。原报告/业务代码在收尾提交中不改，03至04未启动。

- 登记P04-01第三次Windows回传：cbaf87e的24项实现LF指纹匹配，24/24本机检查及实际母子Tk启动恢复、真实导出按钮、备注/作废恢复金额、销售视图、慢扫描编辑/心跳/取消、读关闭与写关闭原回执交付7项全部通过。无回调错误，后台线程退出后临时数据清理正常，[原报告](docs/verification/P04-01-windows-report-03.json)按原值保存。短会话54个心跳样本、最大125ms不冒充P04-04性能验收；原261项辅助、两次失败及业务代码均未改。01具备收尾条件，已通过检查无需重跑，未自动启动02或归档P04。

- P04-01导出控件修复：2d14df9的Windows本机22/22通过，24项LF指纹匹配，临时文件清理与实际Tk启动恢复通过；GUI随后因子版没有保存calc_export_button引用而失败，[原报告](docs/verification/P04-01-windows-report-02.json)保留。子版现保存原导出按钮引用，原布局/命令保持；联测要求启用按钮点击产生新写任务、按所属窗口等待，作废/恢复分别核验状态和金额。新增2项当前页面构造/实际命令及禁用/旧任务拒证据回归，修复前可复现子版缺失引用，修复后后台24项/完整261项辅助通过。待Windows第三次实际Tk复查，01不收尾、02不启动。

- P04-01 Windows清理修复：回传a4194b9的20项检查出现5个WinError 32，均在临时storage.json删除；无业务断言失败，实际Tk联测尚未运行。[原失败报告](docs/verification/P04-01-windows-report-01.json)按原值登记，24项LF指纹匹配。诊断清理先关闭队列并等待所属读线程真实退出，窗口读关闭仍不等待原生I/O；新增2项持有文件/退出回归，原夹具可复现预期失败，修复后后台22项/完整259项辅助通过。原20/257辅助证据保留；待使用新文件名进行Windows复查，不收尾01或启动02。

- P04-01：从P03收尾823a487建立唯一stage/p04-performance，任务书new→now；两版默认后台恢复连接/读取价格、共享检查、扫描、Excel视图/发布及配置/请求操作。2条读通道/4项等候与单写通道；主线程快照/after交付，按代次隔离旧结果，分批呈现，取消/超时不伪终止I/O，读关闭不等共享盘、写关闭保留原提交结果，失败备注保留。新增20项及完整257项辅助通过，[契约与Windows入口](docs/verification/P04-01-background-contract.md)、[证据](docs/verification/P04-01-checks.json)已交付；待Windows复查/用户验收，02至04未启动。

- 用户“开始P4-01”：依据既有Windows回传[收尾P03-04](docs/verification/P03-04-acceptance.json)，四项完成，[P03阶段验收](docs/verification/P03-acceptance.json)登记并将任务书now→old；原实现、黄金与历史报告不改。P04-01已授权，从本收尾提交建立唯一阶段分支，后台I/O/取消与关闭按任务书执行。

- 登记[P03-04 Windows回传](docs/verification/P03-04-windows-evidence.json)：22/22本机检查、21项实现LF指纹匹配02b62f0；实际母子Tk备注历史/草稿分离、取消零写、原因确认与作废恢复按钮、原金额/备注/输入/价格保留及销售视图恢复通过，无回调错误，关闭与清理正常。原报告按回传保存，辅助237项证据不改；04具备收尾条件，已通过检查无需重跑，P03继续留now，未自动启动P04。

- 按用户“开始04”[收尾P03-03](docs/verification/P03-03-acceptance.json)，同分支实施P03-04：稳定订单备注/操作历史、追加更正与逐单草稿、原因必填及取消确认、作废恢复不重复金额；确认期间换单/外部写入拒绝，关联输入检查补订单/请求，异常关联拒写，未知请求核查与保存后刷新失败提示。新增22项及完整237项辅助通过，[契约与Windows入口](docs/verification/P03-04-order-contract.md)、[证据](docs/verification/P03-04-checks.json)已交付；04待Windows复查/用户验收，整阶段留now，P04未启动。

- 登记[P03-03 Windows回传](docs/verification/P03-03-windows-evidence.json)：23/23检查通过，20项实现指纹匹配b868f2b；母子Tk联测、真实新窗口恢复设置、首次连接、旧单价格快照保留及同时间PNG唯一命名通过，无回调错误，关闭与清理正常。原报告按回传保存，辅助215项证据不改；03具备收尾条件，已通过检查无需重跑，04未启动。

- 按用户“开始03”[收尾P03-02](docs/verification/P03-02-acceptance.json)，同分支实施P03-03。本机连接按角色存入用户AppData，母版单独发布storage.json，子版只读继承输出位置，启动去掉旧E盘/UNC隐性fallback。目录/价格保存互不改写，坏配置禁覆盖，唯一目录写测；新单追加完整价格快照，PNG唯一命名和验证发布/未知查询。新增23项、完整215项辅助通过；[契约及Windows入口](docs/verification/P03-03-storage-contract.md)、[证据](docs/verification/P03-03-checks.json)已交付。03待本机复查/用户验收，04未启动；备份目标只登记，隐藏属性和自动调度留P05/P08。

- 按用户确认将P03-01登记为验收通过，简化任务书/索引为直接通过状态。登记[P03-02 Windows回传](docs/verification/P03-02-windows-evidence.json)：21/21格式检查及母子Tk联测通过，18项指纹匹配9be33a8，无回调错误，关闭与清理正常。原始检查结果保留，诊断报告移除与本次检查无关的历史状态描述；03/04尚未启动。

- 按用户“推进02”[收尾P03-01](docs/verification/P03-01-acceptance.json)并实施P03-02，继续唯一stage/p03-file-safety。共用完整列映射、旧别名及只读边界；合法零/缺摘要/失败状态分开，公式只读缓存并核对，历史分组歧义提示，部分统算显性标注；新字符串强制文本、模板禁止清空已有数据、写后核对失败不发布。两端全部列重排后的追加和旧身份保留通过，新增21项、完整192项辅助检查通过，见[证据](docs/verification/P03-02-checks.json)及[契约](docs/verification/P03-02-format-contract.md)。既有黄金/P01/旧报告保持原值；当时待本机复查，最新通过结果见上方登记，03/04未启动。

- P03-01验证安排经用户确认，保留Windows本机32项/母子GUI及辅助171项证据、诊断工具和参考方案。当前验收结论见[P03-01确认](docs/verification/P03-01-acceptance.json)。

- 新增[共享诊断入口](tools/p03_shared_check.py)及[参考步骤](docs/verification/P03-01-shared-test.md)：UUID临时目录、标记/指纹/UNC校验、共享持锁拒写及同请求重试、只读核对订单/回执/金额。[新增6项、完整171项辅助检查](docs/verification/P03-01-shared-tool-checks.json)通过，正式配置和账本不改。

- 登记[P03-01 Windows回传](docs/verification/P03-01-windows-evidence.json)：两份报告匹配151efe8及各12项指纹，32/32本机事务检查与母子GUI联测通过，无回调错误，关闭/清理正常。原分支切换失败后pull快进到正确代码，检查结果有效；辅助一次性单分支克隆复现，补remote.fetch登记和显式跟踪/失败停止命令。无需重跑已通过检查，实际共享双机/占用/只读/断网与用户验收仍待完成，01不收尾/02不启动，源码和原报告不改。

- 接续下一项P03-01，唯一阶段分支stage/p03-file-safety基于P02收尾96735ad，任务书new→now。共用文件锁/哈希检查/临时校验/写前备份/替换回读与请求回执，Excel追加/备注/作废和配置保存接同一事务；新单稳定编号与版本、重复点击幂等，母版旧页面冲突拒写，作废保留原金额并移出有效汇总，子版新单分组按订单身份。整文件删除停用，旧无身份订单只读，未知/未支持格式禁止模板重置。见[P03-01证据](docs/verification/P03-01-checks.json)及[恢复说明](docs/verification/P03-01-file-protocol.md)。新增35项，完整165项辅助回归通过；Windows/双机SMB与真实网络故障仍待验证，P03不收尾，不启动02至04/CI。

- 用户明确确认本轮通过并收尾04；登记[04验收](docs/verification/P02-04-acceptance.json)及[P02阶段验收](docs/verification/P02-acceptance.json)，P02四项全部验收，任务书now→old。最新Windows结论来自用户确认，无新附件，不编造逐项运行数据；原Windows问题/辅助130项证据保留。“05”在P02任务目录中不存在，已告知按下一项P03-01接续，P05不跳过P03/P04前置。

- P02-04复查修复：登记[原Windows回传及人工问题](docs/verification/P02-04-windows-evidence.json)，原119项117通过/2项既有跳过，控制台有JSON未捕获的关闭后Tcl回调错误。补母版计算页Excel按钮、接通共享Excel/截图目录的保存与加载，子版目录显示只读、启动/刷新/输出自动继承；共享配置下位置发布为相对路径，避免把母版E盘当子版本机E盘。修复摘要成本被表头覆盖、取消关闭后任务并捕获bgerror，增加母子共用临时目录联测。新增11项、完整130项辅助通过，见[修复证据](docs/verification/P02-04-directory-checks.json)。[新Windows入口](docs/old/P02-calculation.md#p02-04-windows隔离验收入口)待复查，P02仍留now，未启动P03。

- P02-04：两版原入口接回quote_core/QuoteSession，共用[窗口适配](quote_app/integration.py)，删除重复浮点计算/解析/默认价fallback；Tk输入与增删立即失效，价格变化显式差异/重算/确认，Excel与截图共用当前门槛，关闭不自动改写价格。新增23项与完整119项辅助检查通过，两端53例一致；Excel取冻结整数分/身份，金融单元格精确文本，新增行类型扩展避免商品名被当汇总。原始源码按原manifest归档，P01诊断继续复现原行为，历史报告不改。见[04证据](docs/verification/P02-04-checks.json)和[Windows检查入口](docs/old/P02-calculation.md#p02-04-windows隔离验收入口)。04待Windows/用户验收，P02留now，P03未启动。

- 用户“如果没问题收尾03开始04”：核对[Windows日志](docs/verification/P02-03-windows-evidence.json)匹配2248774及96项清单，94通过/2项既有权限跳过、新增18项全过，登记[03验收](docs/verification/P02-03-acceptance.json)。同一stage/p02-calculation启动04窗口接入，P02继续留now。

### 2026-10-11

- P02-03：从02e76e0收尾登记继续实现QuoteSession、冻结状态/计算请求/输出载荷、单调revision及旧工作丢弃；输入/身份/价格/读取状态变化清空结果，显式刷新重算并确认。正式Excel/报价图/截图共用门槛，错误/陈旧/离线/未校价无写入回调；18项新增及完整96项辅助检查、53例黄金通过。两版原A04隔离复现仍会导出部分订单，新门槛对同一写入函数零调用、临时文件指纹不变；有效Excel载荷1+1=2分及前导零通过。见[P02-03证据](docs/verification/P02-03-checks.json)。原脚本/历史资料不改，窗口接入留04，本机复查/用户验收待完成。

- 用户“开始03”：登记[P02-02验收](docs/verification/P02-02-acceptance.json)，绑定fc12c4b材料、ed47a29实现及Windows76通过/2项既有权限跳过、新增18项配置全过；历史证据保留，无需补跑。复用stage/p02-calculation启动P02-03计算revision、陈旧/价格来源状态和正式输出门槛，窗口接入留04，没有新建分支。

- P02-02 Windows本机复查通过：成功快进至stage/p02-calculation@ed47a29，78个测试ID与实现清单一致，2.193秒，OK (skipped=2)，76通过、无失败/错误；新增18项配置检查和既有18项核心/适配全过，53例黄金通过。两项既有symlink权限跳过原样登记，见[本机通过证据](docs/verification/P02-02-windows-evidence.json)。P02-02具备收尾条件、无需补跑，待用户验收；原代码和历史报告保持，P02整阶段留now，03/04未启动。

- P02-02：在P02-01收尾8c6b78c继续实施旧/新JSON整份候选校验；数字token不经float、single/qty_only严格布尔、重复/保留商品名及未知/坏项拒绝，显式旧单件名单，固定line_kind。纯配置刷新仅全量成功替换，错误保留上次有效对象及原文，无默认价格fallback。新增18项及完整78项辅助回归通过、黄金53/53不变；[P02-02证据](docs/verification/P02-02-checks.json)。原两份脚本和历史资料不改，实际配置/窗口接入留04；本机复查/用户验收待完成，03/04未启动。

- 用户“收尾01开始02”：登记[P02-01验收](docs/verification/P02-01-acceptance.json)，保留原检查及Windows回传证据，P02整阶段继续留now；复用stage/p02-calculation启动P02-02统一数字/折扣与旧、新JSON配置schema校验，不创建第二条阶段分支。P02-03/04未启动。

- P02-01 Windows核心复查通过：已切到stage/p02-calculation@2d8006e，60项清单与仓库一致，2.052秒，OK (skipped=2)，58通过、无失败/错误，P02新增18项全过；53例黄金通过，前次六处GBK错误对应检查均通过。两项既有symlink权限跳过原样登记，未冒充Windows链接保护通过；见[本机通过证据](docs/verification/P02-01-windows-evidence.json)。P02-01具备收尾条件、无需补跑；原业务代码及历史报告不改，P02整阶段留now，02至04未启动。

- P02-01本机复查修正：回传切分支失败、仅运行原42项且6处UTF-8/GBK读取错误、2项symlink权限跳过；不登记为P02通过。采集测试显式UTF-8并加入GBK默认编码替身，修前复现同名六错误，修后辅助60项通过。已复现单分支跟踪缺少P02引用，更新补充跟踪与失败停止命令；见[本机原始回传与兼容检查](docs/verification/P02-01-windows-compatibility.json)。本机P02检查待复查，P01验收及领域核心/原脚本不变，未启动下一项。

- P02-01：从P01收尾7099303建立唯一stage/p02-calculation，任务书new→now；交付无UI/I/O依赖的Decimal领域核心、不可变快照和母子输入适配，金额以整数分权威保存、除法精确HALF_UP、错误/溢出无部分结果。53例静态黄金、200组独立对照和60项回归通过；两版原类隔离输入的两行半分由新核心结算为0.02。原窗口/导出接入留P02-03/04，配置完整schema留P02-02，原脚本与真实数据未改；P02-01待用户验收，未启动下一项。

- 用户授权按建议收尾P01、开始P02-01；确认numeric-v1及performance-v1，保留候选/黄金/历史报告原值并登记批准哈希。P01任务书now→old，Windows黄金53/53、格式18/18及规模结构检查证据齐全，无需补跑；业务修复和真实部署验收留后续，P02将从本收尾提交建立唯一阶段分支。

- 登记P01-04 Windows格式复查：stdlib XML后端18/18通过、无失败，5项诊断材料指纹匹配68bc256，两份源码仅CRLF差异。新证据保留回传字段和值，结合原报告确认53/53黄金及全部规模结构检查通过，原GUI/性能证据继续有效；本次跳过项目不覆盖前次结果，无需重跑。技术建议采纳及阶段材料验收仍待完成，P01留now，未进入P02。

- 登记P01-04 Windows回传：黄金53/53、全部规模通过，两版GUI无回调错误，原心跳最大间隔555/3085ms；格式17/18使诊断未通过。辅助stdlib XML后端复现缓存样本因空标签写法不同未写缓存，改为结构化XML写入并严格校验缓存2；两种后端分别42项回归与18/18格式通过。新增格式单独复查入口和摘要失败明细，原Windows报告保持，待Windows仅重查格式，原业务源码未改。

- P01-04：交付53例静态黄金目标、18种合成格式、数值容量/除法建议、全规模数据生成及受限原方法/Windows心跳测量入口。53/53、18/18、3档明细与3档文件核对通过，39项诊断回归通过；辅助小档复现母版10文件50次打开、子版100明细107次XML源打开。A09补充有摘要时成本被表头覆盖为0的证据，纳入P03-02。原源码和真实数据未改，技术参数采纳、Windows诊断及P01阶段验收待完成，未进入P02。

### 2026-10-10

- 基于 `master@32e164d` 新建 `plans` 文档分支，建立 `docs/new`、`docs/now`、`docs/old` 计划生命周期。
- 完成两份脚本的源码审计与隔离样本复现，建立问题到任务、验收与恢复方式的对应关系。
- 规划 P01–P08：基线契约、计算准确性、文件安全、性能、结构化存储、Rust 核心、Tauri 界面和迁移验收；各开发阶段均待授权启动。

- P01-01：在唯一阶段分支stage/p01-baseline登记依赖/资源和源码指纹，提供临时目录内的Windows双GUI检查；7项诊断工具安全回归通过，Windows实机验收待完成。
- 修正P01-01检查及审计复现入口对Windows CRLF换行的指纹误报；保留真实改动拦截与原业务源码。10项工具回归通过，已登记用户回传环境；拉取后用新报告名重跑GUI检查，详见运行基线说明。
- 登记用户回传的Windows母子版隔离GUI自动检查通过结果：启动、样例计算、关闭和临时目录清理均成功；P01-01继续等待人工界面确认及部署/打包现状登记。
- 登记两版人工窗口会话已完成、启动和临时目录清理正常；下一步仅需回传界面观察及部署/打包现状，无需重复运行已完成的检查命令。
- 用户确认两版页面切换、文字控件和关闭均正常，P01-01已验收收尾；源码入口与Git内打包资源缺失按仓库事实登记，后续Rust + Tauri Windows安装包由P07-04交付。
- 启动P01-02，核对两版金额/价格/权限行为，形成D01–D06候选规则及角色/直接调用权限矩阵；16个合成示例复核两版原计算结果一致，12个可算候选例金额链一致。业务决策待用户确认，契约v1未冻结，原业务脚本未修改。
- 用户确认“采用推荐方案”，D01–D06全部采纳，冻结业务规则business-v1并收尾P01-02；新增确认记录绑定原方案提交及16例历史输出，原脚本保持基线，P01-03/04待启动。
- 启动P01-03，登记母版E盘/子版UNC路径及JSON/Excel格式，发现母版保存export_dir但启动未读取；提供显式文件选择的只读副本/脱敏JSON采集工具。16项合成安全检查及CLI检查通过；真实样本、目录同源、写端/备份/运维和服务主机待登记，尚未验收或部署。
- 登记P01-03用户回传的Windows子版配置脱敏样本及采集报告：9个商品（6面积/3单件），价格/K均可解析为有限非负数，未见形状复核项；原件哈希和只读副本依据采集报告登记。共享目录列出利润明细_20260529.xlsx，内容尚未回传；仓库只记录附件指纹、结构统计与证据边界，不提交实际商品/价格记录。P01-03继续执行中，业务源码和采集工具未改。
- 登记P01-03第二批回传：共享账本含利润明细/输入问题/价格设定3表，当前26列表头位于第6行，明细为0条；9项价格快照与同批配置字段/单件标志一致，配置指纹与第一批相同。无报告的未知表、公式、外链、宏或截断；该空账本仅提供格式证据，不构成真实成交金额对账。P01-03继续等待母版/其他历史样本或不存在说明及实际部署登记；原脚本与采集工具保持不变。
- 用户确认母子目录同源、母版1～2台/销售台数未定、192.168.4.38长期在线，并要求可见目录设置、取消旧E盘业务路径隐性固定、E盘根隐藏备份。按授权以源码/后续合成候选登记未提供的旧格式，不伪造不存在或真实金额验收；P01-03登记范围已验收收尾，目录设置纳入P03/P07，集中一致备份/权限/恢复纳入P05/P08。业务源码和用户目录未改，P01-04待启动。


P08-02-1 追加：[选择式封包与正式端静默界面](docs/verification/P08-02-1-package-permissions.md)。母版/子版可勾选功能，正式端无登录退出和技术连接提示；首次设备身份由 `install.cmd` 部署入口准备。
