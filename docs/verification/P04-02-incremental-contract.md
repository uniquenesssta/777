# P04-02 统一读取与增量索引

状态：已实现待Windows复查。唯一分支`stage/p04-performance`，实施基线为P04-01收尾`796d74defb9dedbfcd522ad8730cfa06a12e49b5`；[01已按用户指令验收](P04-01-acceptance.json)。当前[22项新增/完整283项辅助检查](P04-02-checks.json)通过；本轮不启动03/04。

## 行为与边界

每个文件先解码为已关闭工作簿的行快照，再从同一快照取得格式/金额、文件说明、订单分组、稳定身份、备注/操作历史和母子查看数据。普通工作簿只调用一次`load_workbook`，每张源Worksheet只遍历一次；随后单元格和行访问只读内存。发现公式时另开一次`data_only`取得已有缓存，独立计数；不执行公式、无缓存继续报错，公式/扩展文件继续只读。原金额核心、黄金材料及完整锁事务/哈希CAS/备份/回执没有修改。

默认窗口使用两层可重建缓存：2048文件/估算16MiB的轻量摘要索引，64文件/估算64MiB的完整行/视图LRU。摘要保留精确金额、可见明细数、格式/失败状态和源哈希；明细淘汰不会让目录暖刷新重新解析历史文件。超过预算的完整视图重新读取，明确计入淘汰/重载，不把缓存当账本或承诺无限内存。这里是估算容量，实际RSS/规模性能在P04-04验证。

键包含规范路径、文件大小/时间/身份及parser版本。Windows只读查询FILE_BASIC_INFO的写入/变更时间、FILE_ID_INFO和文件大小，使用允许读/写/删除共享的短句柄并关闭。不会把Windows创建时间冒充变更时间。驱动不提供可信身份/变更信息或时间过粗时回读字节校验哈希；普通可信暖刷新不逐文件读字节。元数据变化但内容哈希相同也复用模型。读取前后版本不一致最多重试三轮，重试单计；持续变化显示失败，不返回旧缓存成功。

同文件的并发扫描/查看合并一次解码；取消读取不发布半成品。写入前后只失效实际目标文件，包括失败/未知提交，旧在途解析不能回填被失效的版本；目录切换清空当前窗口索引。每次目录扫描检测外部变更和删除，金额/文件状态按变动文件差额更新，未变文件不重复参与金额运算。读取失败/格式不支持分别展示，部分汇总只包括验证成功文件，不把失败变成零金额成功。

扫描后列表和统算共用结果。当前打开文件外部变化时撤销旧编辑租约、复用新模型重读视图；文件移除/失败则停用旧租约并提示。正式修改仍重新读取真实文件并执行CAS，缓存不绕过写前/写后验证。价格读取及目录继承规则保持原协议。母版300行显示限制与完整分页属于P04-03，本轮没有冒充完整查看已完成。

## 实现与验证

| 文件 | 职责 |
| --- | --- |
| `quote_files/documents.py` | 单次解码、脱离句柄的行快照、金额/身份/历史共享模型 |
| `quote_files/metadata.py` | Windows只读版本探测；不可信元数据标记回读核查 |
| `quote_files/cache.py` | 双层有界索引、并发合并、失效代次、变动文件金额差额 |
| `quote_files/reading.py` / `views.py` | 摘要/分组/母子视图复用快照；旧格式/公式错误规则保留 |
| `quote_app/background.py` / `file_reads.py` | 后台复用模型、目标写失效及主线程分批显示/自动统算 |
| `tools/p04_cache_check.py` | 本机新增22项与实际Windows/Tk11步骤；所有文件均在临时目录 |

辅助检查包括源Sheet一次遍历、20/40行各一次XML打开、冷热索引、明细LRU淘汰、单文件变更/删除、同尺寸原位改写且恢复mtime、同尺寸原子替换、弱元数据哈希校验、parser变更、错误修复、公式附加缓存读取、并发合并、在途失效、取消、内存预算、源切换及显示结果不能改坏缓存。当前真实适配器额外验证原导出写入只重读目标、外部变化刷新视图、删除撤销租约；Windows联测的新缓存步骤已用替代控件/Tcl/真实适配器预演，不能代替实际Tk。

[辅助计数样本](P04-02-read-profile.json)为合成数据：5文件冷读5次workbook，暖刷新0次，完整视图LRU只保留2文件仍不重解析摘要；单文件变化1次、删除0次；20/40行XML打开各1次。Linux/Tcl辅助证据与原P01/P04-01机器报告各自保留，不把它们改成Windows或生产SMB实测。

## Windows一键复查

当前已在P04分支，执行：

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '拉取失败，先停止' }
py -3 tools/p04_cache_check.py --gui-smoke --output reports/p04-02-windows-01.json
```

工具检查新增22项，再以当前母子后台Tk窗口复查原生命周期7项及缓存4项：4文件冷读4次、暖统算0次；母子视图复用及销售40行；外部改单文件1次/删除0次；真实备注按钮写入只重读目标文件。报告区分缓存读取次数与完整事务必需的CAS读取，含当前提交/LF指纹、元数据后端、缓存预算/淘汰/回读计数及精确金额。窗口、元数据句柄和后台线程真实结束后才清理临时目录，不访问生产盘或实际屏幕截图。只有实际Windows回传通过后登记本机验收。

依据：[FILE_BASIC_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)、[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)、[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[FILE_ID_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)。依据字段组合及不可信时回读属于本项目缓存策略，不声称所有文件系统都提供相同时间/身份语义。
