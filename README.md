# 记账器 / 报价利润计算器

当前业务基线是两份 Python + Tkinter 脚本：每日汇总母版，以及读取共享 JSON 价格的子版。`master` 基线提交为 `32e164d78643de8fa6cbd21a7ca634e1b318f855`。

本分支 `plans` 交付重新审计结果、Python 优化计划及 Rust + Tauri 迁移准备方案。**本次没有修改两份业务脚本，也没有启动迁移实施。**

- [文档与计划入口](docs/README.md)
- [优化及迁移主任务书](docs/MASTER_PLAN.md)
- [两份 Python 代码重新审计报告](docs/audit/python-audit.md)
- [业务与数据迁移契约草案](docs/MIGRATION_CONTRACT.md)
- [Rust + Tauri 架构与切换方案](docs/RUST_TAURI_DESIGN.md)

## Change Log

### 2026-10-10

- 基于 `master@32e164d` 新建 `plans` 文档分支，建立 `docs/new`、`docs/now`、`docs/old` 计划生命周期。
- 完成两份脚本的源码审计与隔离样本复现，建立问题到任务、验收与恢复方式的对应关系。
- 规划 P01–P08：基线契约、计算准确性、文件安全、性能、结构化存储、Rust 核心、Tauri 界面和迁移验收；各开发阶段均待授权启动。
