# P01-01 运行基线与检查说明

状态：检查工具与材料已完成，**Windows 实机验收待完成**。当前只授权P01-01；P01-02至04未启动。阶段分支 `stage/p01-baseline`，创建基线 `plans@78a1e1d9d8b10c198be2338a7dc61328535d7655`；业务源码仍为 `master@32e164d`。阶段记录：[P01任务书](../now/P01-baseline.md)。

## 1. 核对结果

两版文件名、Git blob、SHA-256、行数、导入清单见 [manifest.json](manifest.json)。这份manifest固定仓库内原始LF源码；检查工具同时报告工作区原始哈希和仅将CRLF转换为LF后的哈希。完全一致标为`baseline_match_kind=exact`，仅换行不同标为`line_endings_only`；两者均为`baseline_matches=true`、`status=ok`。实际内容变化仍拒绝GUI启动，不删除空格、注释、BOM或忽略其他修改，不重写源文件，也不更新原始指纹来绕过检查。

| 能力 | 当前仓库事实 | 当前辅助环境实测 | Windows本机 |
| --- | --- | --- | --- |
| Python | 未声明最低/生产版本 | 3.12.14，64位 | 用户回传Windows 10 / AMD64、Python 3.12.10、64位；生产解释器是否同一份待确认 |
| tkinter / Tcl / Tk | Python随附模块，启动必需 | 导入可用；Tcl 9.0.4；编译Tk 9.0；未创建窗口 | 导入可用；Tcl 8.6.15、编译Tk 8.6；实机窗口待验证 |
| openpyxl | 原代码可选导入；Excel功能实际必需 | 3.1.5导入可用 | 3.1.5导入可用 |
| Pillow / PIL.ImageGrab | 原代码可选导入；截图功能实际必需 | 12.3.0导入可用；未实测截图 | 11.2.1导入可用；未实测截图，无需为本次修正升级 |
| PyInstaller | 不是源码启动依赖；代码仅有资源路径适配 | 未安装，未构建 | 检查环境已安装6.20.0；原应用打包流程/使用版本仍待登记 |
| app.ico | 子版配置相对文件名；仓库不存在 | 缺失，原逻辑静默跳过窗口图标 | 如需要原品牌图标，保留并提供已有资源；本任务不另画图标 |
| config.json | 外部价格配置；仓库不存在 | 隔离检查生成单个合成价格项 | 真实配置属P01-03采集范围 |
| 打包资源 | 无.spec、构建脚本、安装包或锁文件 | 不声称已有可复现打包 | 待登记 |

[requirements-baseline.txt](../../requirements-baseline.txt) 只固定本轮辅助环境已有的两项应用依赖，供隔离环境重现。不是用户生产版本锁，也不是Windows兼容认证。本任务没有安装/升级用户现有环境，没有新增应用依赖，没有安装PyInstaller。

原代码启动方式为直接运行根目录两份Python脚本，`__main__`创建Tk、PriceCalculator并mainloop；母版关闭时自动保存价格配置。母版默认E盘根目录，子版默认UNC共享根目录，在窗口建好前就会尝试目录操作。直接启动原脚本会涉及这些既有路径，因此本任务提供隔离入口，原生部署路径映射和共享可用性待P01-03/相关阶段核验。

## 2. Windows采集与隔离启动

在本阶段分支仓库根目录，用要验证的Python执行；以下 `py -3` 使用Windows已安装的默认Python 3。先检查 `py -3 --version` 是否就是实际要采集的解释器。检查工具需要Python 3.9或更高（本轮辅助验证为3.12）；这不是原应用的最低版本声明。

```powershell
py -3 --version
py -3 tools/baseline_check.py --output reports/p01-environment.json
py -3 tools/baseline_check.py --gui-smoke --output reports/p01-windows-smoke.json
```

第一条采集Python、位数、OS、Tcl/Tk和应用包版本、源码指纹、缺资源状态。默认不创建Tk窗口、不实例化原应用、不访问原共享路径。第二个工具调用会先校验环境，再逐一启动母子窗口，等待事件循环、检查页面数、计算一个合成单件（销售50.00、成本20.00、利润30.00）并关闭。

GUI检查通过必须看到两版 `status=passed`、`close=ok`、`sandbox_cleaned=true`；命令退出码0。只看到依赖available或默认检查退出0不代表GUI通过。Linux/macOS执行GUI选项会明确blocked并返回2，不扩大产品验收平台。

每个GUI窗口使用临时配置、Excel和截图目录，诊断会话增加目录/文件越界保护（不改原业务源码），结束自动清理；没有向真实订单目录导出。测试用临时价格来自检查工具，不是实际报价价格。报告固定标为部署/用户验收待完成，不能据此宣布完整业务通过。

报告文件采用独占创建，已存在则返回错误，换新文件名或自行保存好旧报告后删除旧文件再运行。`reports/`已被Git忽略；报告可能包含解释器路径，请先检查再回传，不直接公开客户数据/凭证。

如缺依赖，先保留现有Python和原安装包。可在独立环境安装已记录版本做重现，不能把新环境版本冒充原生产版本：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-baseline.txt
.\.venv\Scripts\python.exe tools/baseline_check.py --gui-smoke --output reports/p01-isolated-venv.json
```

如果tkinter缺失，需要修复对应Python安装的Tcl/Tk组件，不通过pip安装同名包替代。安装步骤未在当前Windows实机执行，缺包/安装失败保留错误报告后诊断。

## 3. 人工确认入口

```powershell
py -3 tools/baseline_check.py --launch manager
py -3 tools/baseline_check.py --launch sales
```

两个命令分别打开原母版和子版，窗口标题含“P01-01 隔离检查”；关闭后清理合成目录。人工记录：窗口是否可见、页面切换是否可用、文字/控件是否完整、是否正常关闭、Python/系统版本。手动会话结束只记录manual_session_finished，工具不替用户声称交互验收通过。

P01-01要求干净Windows环境能启动两版；需要至少完成一次该环境的GUI自动检查及人工确认。用户既有部署版/打包资源信息仍须登记。局域网并发、真实金额样本、DPI全面回归和迁移不属于本任务；没有因此开始P01-02/03/04。

## 4. 可复现辅助检查与实际结果

```text
python -m unittest discover -s tests -p test_baseline_check.py -v
python tools/baseline_check.py
python tools/baseline_check.py --gui-smoke
```

本轮在辅助环境执行：修正后10项工具安全回归通过；两版blob/SHA-256及AST语法一致；三项应用依赖导入可用；默认环境检查返回0；GUI检查明确返回2、Windows环境缺失，未运行窗口。详见 [assistant-environment.json](assistant-environment.json)。

原7项回归验证：原源码指纹；变化源码执行前拒绝；运行时所有存储常量进入沙箱且源码不变；缺依赖错误可见；非Windows在加载应用前阻断GUI；已有输出文件不覆盖；人工选择沙箱外工作簿在实际读取前被拒绝。新增3项覆盖用户回传的两版CRLF哈希、CRLF文件中真实改动执行前拒绝、审计复现入口使用相同门槛。这些证据只验证检查工具与基线，不能替代Windows产品验收。

现有 [审计复现入口](../audit/reproduce.py) 使用同一manifest和检查函数，允许仅CRLF换行差异，实际修改仍在加载前拒绝，且仅使用临时合成数据；本轮复现退出码0，原审计观察保持一致。此任务没有新增P01-04黄金业务样本集，没有把已知业务缺陷修成通过结果。

## 5. 当前阻塞与恢复

用户已回传一次Windows检查：[脱敏环境及诊断证据](windows-environment.json)。旧工具将CRLF工作区原始字节与LF仓库blob直接比较，导致两版`status=changed`并在创建窗口前阻断。把原始LF文件逐字节转换成CRLF，得到的Git blob及SHA-256均与回传结果完全相同，确认只有换行差异；这不是用户业务代码发生修改的证据。已修正检查工具与同根因的审计入口，原始业务文件和指纹保持不变。

在`stage/p01-baseline`仓库根目录拉取修正后，用新报告名重新运行（旧报告保留）：

```powershell
git pull --ff-only origin stage/p01-baseline
py -3 tools/baseline_check.py --gui-smoke --output reports/p01-windows-smoke-02.json
```

预期两份源码均为`status=ok`、`baseline_matches=true`，CRLF文件显示`baseline_match_kind=line_endings_only`；之后核对两版GUI的`passed`/`close=ok`/`sandbox_cleaned=true`。当前GUI仍待重跑，不能将依赖导入成功或此处预期记为窗口通过。还缺人工确认、原图标/实际打包流程登记；P01任务书留在now，不归档也不进入P01-02。

恢复方式：本轮只添加诊断工具、清单和说明，原两版源码/外部配置/订单未修改；代码可按本阶段创建基线恢复。报告写失败不覆盖旧报告，临时GUI目录关闭时自动清理。
