# P06-03 Rust Excel读取与新报表生成

用户2026-10-13 23:07:55（Asia/Shanghai）“收尾02开始03”，已登记[02验收](P06-02-acceptance.json)与[03启动](P06-03-start.json)。唯一分支仍为stage/p06-rust-core，从223e86e接续；02原Windows/失败/辅助证据保持，04未启动。

## 选型与边界

[候选验证](P06-03-candidates.json)选择quick-xml0.41.0 + zip8.6.0作有界OOXML读取，rust_xlsxwriter0.99.1生成新文件；calamine0.36.1仅为开发验证依赖。实际Rust用例证明calamine的Data::Float改变9007199254740993.25的原数字表示，选定读取器保留XML原始token。生成库只创建新工作簿，不承担任意旧文件无损编辑。版本、checksum、全部74外部包许可及[完整通知](../../THIRD_PARTY_NOTICES.md)在[依赖登记](P06-03-dependencies.json)固定，原02依赖资产不改。

独立crate为crates/quote-excel，不含财务计算、HTTP、Tk/Tauri、文件发布或数据库。通过既有受校验的rust-ledger-worker.exe私有stdin/stdout处理字节，不新增监听端口、可上传任意路径的API或第二个财务写端。[私有格式契约](P06-03-protocol.json)记录读取DTO、能力协商、容量与错误位置；ledger-v1、legacy-import-v1、777-output-v1、完整包v3和已确认业务/数值规则保持。

## 读取、导入与追溯

先检查源20MiB、ZIP2048成员/64MiB展开、重复成员/CRC/加密、XML编码/实体/深度、标准包根/关系/工作簿类型。工作表最多50000行/64列，每表矩形及整包实际单元格各不超过100万；未知命名空间、异常尺寸/单元格位置、外部关系、宏/图形/扩展拒绝。最多128个合并范围，隐藏的非锚点值拒绝复核；已有公式一律拒绝，即使有缓存，不执行或信任缓存。

读取保留sheet/坐标/状态、数字原文、文本/共享字符串、样式与1904日期纪元。现有字段映射继续识别26列、旧用户/高度/宽度别名、重排、行类型、稳定身份、备注/作废/价格历史及原请求关联。正常旧源与Python参考的完整Plan和review SHA相同，沿用v1批次/原回执，不重新编造订单身份。会丢失精度的旧浮点数值明确给出NUMERIC_TOKEN_REQUIRES_TEXT及sheet/cell；保留原字节，要求在复核副本中提供准确文本，不静默舍入或修改原源件。

Rust后端的导入预演及提交前来源核对使用同一原生读取器；Python只构建已有字段/归属/隔离映射与内存delta，最终仍由Rust重验全账本后一次事务写入。坏源、未认可隔离或变化的review SHA不能提交。CLI apply在同一owner锁内加载已选后端，先复核源绑定，再询问密码、鉴权/保管人及完整维护备份；只读加载后端元数据不写账本。原字节/hash/mtime、销售权限及批次重复语义不变。

旧preview命令保留Python参考读取；需要跟随明确主机的原生格式时加`--host-root`，不请求密码、不写财务：

```powershell
py -3 tools/p05_import.py preview --source '所选副本.xlsx' --host-root '所选本机主机目录' --output reports/p05-preview-native-01
```

此处只说明未来显式操作格式，当前不要求选择真实源件、E盘或主机。客户、原件、完整计划仍保存在private目录。

## 输出、恢复与兼容

已选新Rust后端生成Protocol/Order/Lines/Notes四表；字段/行序、冻结payload SHA、整数分与精确元显示、中文/前导零/公式样式文本、控制字符表示、粗体首行/A2冻结/24列宽与原报表一致。独立Python矩阵验证所有内容，原生读取再次验证生成字节；默认Python参考验证也加强为全字段/文本/样式检查。缓存blob、下载、重试及完整包核对使用所属格式后端；旧缓存内容兼容，不因改价格/备注/状态重新成交或改写原快照。

输出队列、财务revision、原请求、角色过滤和发布目录规则不变：报价Excel按母版发布的export_dir写新UUID文件，内部成本报表留private，仅管理员可下载；销售不能更改位置或下载成本。共享发布名仍为777-order_id-job_id.xlsx，下载建议名仍为job_id.xlsx。发布继续复用临时文件/刷盘/独立校验/排他新建；异常只改变任务状态，不重新入账。

旧v3包携带财务版v1执行文件，没有Excel命令。先验证执行文件hash与账本，再进行明确格式能力协商：新包为rust-excel-v1；已知v1未知命令回复协商为python-v1-compatibility，仅保留旧格式桥接，财务写端仍是该原生执行文件。缺失/校验失败/未知能力形状不协商回退。实际从223e86e导出固定源、离线编译原v1执行文件，验证旧v3的输出/账本/原执行文件可独立恢复；没有覆盖现有worker或生产资源。

仍需退出的桥接明确记录在协议：Python字段/日期映射、旧来源独立备份核对、旧财务版worker格式桥接与PNG渲染；依赖现有openpyxl/Pillow，未引入新Python依赖。完整Rust宿主/资源升级在P06-04完成并验证后退出；旧v3桥接在明确资源升级前保留兼容，不能静默删掉历史可读性。

## 验证与Windows入口

[03检查证据](P06-03-checks.json)记录165专项、32项Rust/fmt/Clippy/release、同一561/561影子对照（原黄金53/53）、完整辅助回归、旧原生执行文件构建日志及开发中发现的问题。覆盖所有P01合成工作簿形状/既有导入回归，中文/前导零/原数字/日期两种纪元/公式缓存拒绝/未知schema/大表及容量、原请求重放、独立读取器/样式、角色/成本/完整恢复。辅助真实HTTPS链路包含内存待核查与11500/4600/6900分恢复，不冒充Windows DPAPI或ACL。

本轮唯一入口已完成且核对通过，保留命令供复现，当前无需重跑：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 tools/p06_excel_check.py --windows-smoke --output reports/p06-03-windows-01
```

沿用已验证的Rust1.97.1/MSVC及现有Python依赖；Cargo按锁定文件获取新Excel依赖，旧v1兼容夹具只用已缓存依赖离线编译。入口核验实际Windows AMD64/MSVC，执行专项/原生库检查及完整比较，再用临时主机、Rust读取/生成、旧HTTPS客户端、DPAPI原回执、原源hash/mtime、母版位置/成本过滤、独立读取器和v3恢复/权限/清理联测。不启动GUI，不访问真实E盘/共享或安装服务，不切换生产。[原报告](P06-03-windows-report-01.json)与[原比较文件](P06-03-windows-comparisons-01.json)已按原字节归档；输出不得覆盖，后续若改动确需复查使用新编号。02及P05已通过入口无需重跑。

[Windows独立核对](P06-03-windows-evidence-01.json)通过fee8ea3的98项LF源码指纹、165项Python/32项Rust/561项对照及原生Excel/DPAPI/HTTPS/v3恢复/ACL；原源hash/mtime、独立读取器文本/精度/样式和旧v3原执行文件兼容通过。03具备收尾条件待用户验收，已通过检查无需重跑；P06仍留now，04/07/08未启动。

用户已于2026-10-14 02:38:15按[03验收](P06-03-acceptance.json)收尾并接续[04独立宿主](P06-04-host-contract.md)。以上本轮03结果为原证据，当前无需重跑。
