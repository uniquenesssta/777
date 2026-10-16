# P01-01 运行基线与检查说明

状态：**P01-01已验收收尾**；Windows双版隔离GUI自动检查通过，用户已确认页面切换、文字控件和关闭正常，仓库运行/打包资源现状已登记。后续任务当前状态见[P01任务书](../old/P01-baseline.md)。阶段分支 `stage/p01-baseline`，创建基线 `plans@78a1e1d9d8b10c198be2338a7dc61328535d7655`；业务源码仍为 `master@32e164d`。

## 1. 核对结果

两版文件名、Git blob、SHA-256、行数、导入清单见 [manifest.json](manifest.json)。这份manifest固定仓库内原始LF源码；检查工具同时报告工作区原始哈希和仅将CRLF转换为LF后的哈希。完全一致标为`baseline_match_kind=exact`，仅换行不同标为`line_endings_only`；两者均为`baseline_matches=true`、`status=ok`。实际内容变化仍拒绝GUI启动，不删除空格、注释、BOM或忽略其他修改，不重写源文件，也不更新原始指纹来绕过检查。

| 能力 | 当前仓库事实 | 当前辅助环境实测 | Windows本机 |
| --- | --- | --- | --- |
| Python | 未声明最低版本；仓库提供源码入口 | 3.12.14，64位 | Windows 10 / AMD64、Python 3.12.10、64位；作为本任务已验证的源码运行基线 |
| tkinter / Tcl / Tk | Python随附模块，启动必需 | 导入可用；Tcl 9.0.4；编译Tk 9.0；未创建窗口 | Tcl 8.6.15、编译Tk 8.6；母子版隔离启动/计算/关闭通过，用户已确认界面正常 |
| openpyxl | 原代码可选导入；Excel功能实际必需 | 3.1.5导入可用 | 3.1.5导入可用 |
| Pillow / PIL.ImageGrab | 原代码可选导入；截图功能实际必需 | 12.3.0导入可用；未实测截图 | 11.2.1导入可用；未实测截图，无需为本次修正升级 |
| PyInstaller | 不是源码启动依赖；代码仅有资源路径适配 | 未安装，未构建 | 已安装6.20.0，仅登记环境；Git内无打包流程或安装包，不因此追加Python打包任务 |
| app.ico | 子版配置相对文件名；仓库不存在 | 缺失，原逻辑静默跳过窗口图标 | 缺失已登记，启动可降级；桌面品牌资源在P07准备 |
| config.json | 外部价格配置；仓库不存在 | 隔离检查生成单个合成价格项 | 真实配置属P01-03采集范围 |
| 打包资源 | 无.spec、构建脚本、安装包或打包锁文件 | 不声称已有可复现打包 | 仓库缺失现状已登记；后续Rust + Tauri交付Windows安装包，见P07-04 |

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

P01-01要求Windows环境能按记录启动两版，已完成实机GUI自动检查及用户人工确认。当前源码入口、已验证解释器与Git中打包资源缺失均已登记；仓库未提供的旧发行包不作为本任务前置。局域网并发、真实金额样本、DPI全面回归和迁移不属于本任务；没有因此开始P01-02/03/04。

## 4. 可复现辅助检查与实际结果

```text
python -m unittest discover -s tests -p test_baseline_check.py -v
python tools/baseline_check.py
python tools/baseline_check.py --gui-smoke
```

本轮在辅助环境执行：修正后10项工具安全回归通过；两版blob/SHA-256及AST语法一致；三项应用依赖导入可用；默认环境检查返回0；GUI检查明确返回2、Windows环境缺失，未运行窗口。详见 [assistant-environment.json](assistant-environment.json)。

原7项回归验证：原源码指纹；变化源码执行前拒绝；运行时所有存储常量进入沙箱且源码不变；缺依赖错误可见；非Windows在加载应用前阻断GUI；已有输出文件不覆盖；人工选择沙箱外工作簿在实际读取前被拒绝。新增3项覆盖用户回传的两版CRLF哈希、CRLF文件中真实改动执行前拒绝、审计复现入口使用相同门槛。这些证据只验证检查工具与基线，不能替代Windows产品验收。

现有 [审计复现入口](../audit/reproduce.py) 使用同一manifest和检查函数，允许仅CRLF换行差异，实际修改仍在加载前拒绝，且仅使用临时合成数据；本轮复现退出码0，原审计观察保持一致。此任务没有新增P01-04黄金业务样本集，没有把已知业务缺陷修成通过结果。

## 5. Windows实机结果与收尾

用户已回传两次Windows检查：[脱敏环境及诊断证据](windows-environment.json)中分别保存`observed_before_fix`和`observed_after_fix`。旧工具将CRLF工作区原始字节与LF仓库blob直接比较，导致两版`status=changed`并在创建窗口前阻断。把原始LF文件逐字节转换成CRLF，得到的Git blob及SHA-256均与首轮回传结果完全相同，确认只有换行差异。已修正检查工具与同根因的审计入口，原始业务文件和指纹保持不变。

用户在Windows执行并回传的第二轮命令（已完成，无需为本次登记重复运行）：

```powershell
py -3 tools/baseline_check.py --gui-smoke --output reports/p01-windows-smoke-02.json
```

实际结果：两份源码均为`status=ok`、`baseline_matches=true`、`baseline_match_kind=line_endings_only`；GUI整体`completed`。

| 检查项 | 母版 manager | 子版 sales |
| --- | --- | --- |
| 启动 / GUI结果 | `startup=ok` / `status=passed` | `startup=ok` / `status=passed` |
| 页面数 | 5：计算主页、输入反馈、利润分析、Excel记录、价格设定 | 3：计算主页、输入反馈、Excel记录 |
| 样例销售 / 成本 / 利润 | 50.00 / 20.00 / 30.00 | 50.00 / 20.00 / 30.00 |
| 关闭 / 临时目录清理 | `close=ok` / `sandbox_cleaned=true` | `close=ok` / `sandbox_cleaned=true` |

这份用户回传报告证明隔离GUI自动检查通过，工具未访问生产路径；不是辅助环境模拟窗口结果。回传内容未单独打印进程退出码，不额外编造该值。截图、真实Excel读写、局域网和生产部署未在本次检查中执行。

用户随后拉取`cdf1ca3`并完成第3节的两个人工窗口会话；两版报告均为`startup=ok`、`manual_session_finished`、`acceptance=requires_user_observation`和`sandbox_cleaned=true`，没有报告工具错误。结果保存在同一证据文件的`manual_launch_observations`中；公共环境/指纹字段合并保存，两个GUI结果分别保留。用户随后明确确认“页面切换文字控件关闭等都正常。”此人工观察单独记录于`user_confirmation`，保留历史工具报告原值。

当前仓库事实已复核：根目录两份Python脚本具有直接启动入口；没有图标、.spec、打包脚本和安装包。缺失即为本次资源登记结果，不要求用户再回答Git可确认的信息，也不声称已验证仓库之外的旧发行包。用户明确的后续Windows桌面安装交付已列入[P07-04](../old/P07-tauri-desktop.md)，当前不新增Python打包任务。

P01-01已验收收尾。收尾时下一项为P01-02业务金额规则与权限确认，其后续执行状态统一见[P01任务书](../old/P01-baseline.md)。P01整阶段尚未完成，任务书继续留在now；无需重跑已完成的检查或补交旧生产安装包来关闭本任务。

恢复方式：本轮只添加诊断工具、清单和说明，原两版源码/外部配置/订单未修改；代码可按本阶段创建基线恢复。报告写失败不覆盖旧报告，临时GUI目录关闭时自动清理。
