# P03-01 共享盘双机与占用诊断参考

状态：P03-01已按[用户确认](P03-01-acceptance.json)验收通过。以下步骤保留为可选诊断参考，不属于当前补测要求；原始Windows检查记录和写入失败保护保留。P03-02已交付并通过本机复查，当前阶段状态见[任务书](../now/P03-file-safety.md)。

用两台实际Windows电脑，A运行母版，B运行子版。两端都取`stage/p03-file-safety`最新代码，使用Python及原运行依赖。两端统一使用UNC路径；本轮不要混用E盘路径或映射盘。测试工具只在共享盘新建`P03-test-UUID`子目录，价格、Excel、图片均重定向到这里，不使用正式`config.json`或`利润表`，关闭后保留证据。价格及目录不要在测试窗口内修改；修改后工具拒绝继续核对，不重建配置。

## 1. A创建测试目录，两端打开窗口

两台电脑各自在仓库目录先运行：

```powershell
git branch --show-current
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw '更新失败，先停止' }
```

第一条须显示`stage/p03-file-safety`。分支尚未跟踪时使用[当前任务书的切换命令](../now/P03-file-safety.md#windows-复查入口)，已有32项及本机GUI结果无需重跑。

A创建一次：

```powershell
$p03Setup = py -3 tools/p03_shared_check.py --prepare '\\192.168.4.38\14T共享盘\葛宁\PyInstaller' --output reports/p03-shared-prepare.json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $p03Setup.status -ne 'prepared') { throw '准备失败，先停止' }
$p03 = $p03Setup.sandbox
Write-Host $p03
py -3 tools/p03_shared_check.py --launch manager --sandbox $p03 --output reports/p03-shared-A.json
```

把A输出的完整`P03-test-…`路径复制给B。B不要再运行prepare：

```powershell
$p03 = Read-Host '粘贴A输出的完整测试目录路径'
py -3 tools/p03_shared_check.py --launch sales --sandbox $p03 --output reports/p03-shared-B.json
```

窗口标题显示P03共享测试、电脑名和角色，已添加一行“共享测试商品”，数量默认1，单件售价10、成本4、利润6。两端代码不同时，工具在打开窗口前拒绝，先更新代码再新建测试目录。

启动GUI的终端会等待窗口关闭。后面的命令在另一PowerShell终端运行，先用下面一条设置同一目录：

```powershell
$p03 = Read-Host '粘贴本轮完整测试目录路径'
```

报告文件独占创建，不覆盖已有文件；重复运行需换`--output`文件名。测试尽量在同一天做完；持锁步骤仅接受一份当日测试工作簿。

## 2. 双机同时追加及重复点击

商品行始终只留一行、数量1，不加折扣。A依次填订单号`A01`、`A02`、`A03`；B依次填`B01`、`B02`、`B03`。每轮两端先填好订单号、点击计算，然后一起点导出Excel，做三轮。出现价格确认时，核对测试价格并按界面确认。

提示正在由其他写端处理且本次未提交，是可预期的竞争结果；另一端保存完成后，保持原订单和计算结果，只再点导出，直到这一单保存成功。结果不明时先用界面“检查上次写入”或[P03请求查询](P03-01-file-protocol.md#未知提交核查)，不重新计算制造另一请求。两端各对最后一单再点两次导出，应只保留原单；**改订单号或重新计算会产生新请求，不能用于重复点击测试**。

两端暂停写入，在A的第二终端核对：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 6 --output reports/p03-shared-after-concurrent.json
```

预期`status=data_checks_passed`、总单6/有效6/作废0/追加回执6，总收入60.00、总成本24.00、利润36.00。工具按稳定订单ID统计，核对每单明细/总计、原始请求、唯一测试订单号及日汇总；Excel行数不是订单数。一次同时点击无法证明必定重叠，下一步持锁能明确制造跨机竞争。

## 3. 明确验证另一台电脑持锁

B另开终端，设置`$p03`后运行：

```powershell
py -3 tools/p03_shared_check.py --hold-lock --sandbox $p03 --seconds 30 --output reports/p03-shared-lock-B.json
```

等B显示“已持有测试工作簿锁30秒”，A立即把订单号改成`A04`、计算并导出。预期拒绝，提示文件正在由其他写端处理、本次未提交。**在B释放前不要重试**；报告应显示持锁前与持锁期间SHA256相同、`lock_released=true`。不要删除锁文件。

B报告完成后，A保留原计算结果再点导出，应只新增一次`A04`。核对：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 7 --output reports/p03-shared-after-lock.json
```

预期7单、7个追加回执，70.00/28.00/42.00。如果A在明确持锁时仍保存成功，保留两端报告及整个测试目录，停止本轮验收。

## 4. 旧页面冲突、追加备注与作废

A在Excel记录页打开当日文件，选`A01`商品行，保持页面。B新增`B04`并保存。A不刷新，给`A01`添加“共享测试备注”并保存，预期旧页面冲突拒绝；刷新后重新选`A01`，再追加一次备注，应成功。

A刷新，重新选`A01`并确认作废。原行、原金额和备注必须保留，记录状态改为void，日汇总排除这一单；子版刷新后不显示其有效明细。原始8单、有效7单、作废1单，仍是70.00/28.00/42.00，追加回执8、备注回执1、作废回执1：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 8 --expected-voids 1 --output reports/p03-shared-after-edits.json
```

## 5. 用Excel实际占用文件

先暂停应用写入并取得文件路径：

```powershell
Get-ChildItem -LiteralPath (Join-Path $p03 'reports') -Filter '*.xlsx' -File | Select-Object FullName
```

B用桌面Excel打开该测试文件，保持普通编辑窗口打开，不修改、不保存。A新填`OCC01`、计算、导出一次。

- 若Excel阻止替换，应显示写入未确认/占用错误，原文件保持完整。保持Excel打开核对仍是8单/作废1；报告中的SHA256应与after-edits相同。关闭Excel，不保存更改；在应用检查上次写入，明确未提交后直接重试原计算结果，`OCC01`只新增一次。
- 若Excel打开即为只读、未阻止替换，或A仍成功保存，先记录实际提示和请求ID，不把它记成“占用拒写通过”，也不要再次提交同一单。关闭Excel后核对回执及订单；不要用Excel保存已过时的页面。不同Excel打开方式的占用表现须按实测登记，应用锁不能保证任意外部Excel编辑并发安全。
- 结果不明先查请求回执，保留恢复副本，不用重新计算或删除锁来试错。

占用打开期间、A写入被拒绝后核对：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 8 --expected-voids 1 --output reports/p03-shared-while-excel-open.json
```

关闭Excel、核查并重试OCC01成功后，最终原始9单/有效8单/作废1单，80.00/32.00/48.00，追加回执9、备注1、作废1，核对：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 9 --expected-voids 1 --output reports/p03-shared-final.json
```

最后关闭两个测试窗口，生成各自会话报告；再核对一次，会列出两台电脑的主机名及共享`sessions`报告：

```powershell
py -3 tools/p03_shared_check.py --verify --sandbox $p03 --expected-orders 9 --expected-voids 1 --output reports/p03-shared-final-closed.json
```

把两端控制台/本地报告和是否出现预期持锁拒写、旧页面冲突、Excel占用提示发回。`data_checks_passed`只表示订单/回执/金额检查通过，不能自动宣称两台物理电脑并发验收已通过；主机名也不是经过认证的机器身份。

以上命令为可选诊断资料，不属于当前待办；工具不自动清理或恢复，已通过的本机检查无需补跑。
