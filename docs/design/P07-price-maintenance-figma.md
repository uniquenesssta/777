# P07-03 价格维护 Figma 接入

用户2026-10-15明确“上一个聊天已经弄好了，现在写入吧”，本次在唯一 `stage/p07-tauri-desktop` 从 `154fa0c` 接入已完成的价格页设计。此前未经本稿确认的本地排版尝试没有发布，也不作为本次实现来源。

## 设计依据

沿用文件 `2ek9bkIz5ldyhjZnnvIuNu`、当前页 `21:2`；本次只读设计，没有修改画布或报价/订单页面。四个节点均读取了高保真上下文和截图。

| 状态 | 节点 | 实现 |
| --- | --- | --- |
| [手填售价](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=57-688) | 57:688 | 白底最终售价输入，成本与K保持独立 |
| [成本×K](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=57-689) | 57:689 | 淡紫只读售价，现有Rust精确预览 |
| [新增商品](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=57-690) | 57:690 | 工具栏直接加行、滚动聚焦名称；必填项未填不发布 |
| [发布确认](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu?node-id=57-691) | 57:691 | 380×194弹窗、商品数量、104×40按钮；返回保留修改 |

`PriceItemRow` 58:814、`PriceSaleField` 58:797与既有Button/Badge/TableCell映射到 `PricesPage.tsx`、`prices.css` 和公共UI组件。1360px目录在1440px窗口左右各留40px；双层40px表头、80px商品行、36px成本/K控件、40px最终售价及80px发布栏复用现有紫灰tokens。目录按内容收高，不再使用强制748px空白卡片；添加在右上、发布在卡片右下。表头、分组和数据共用列宽；窄窗口仅表内滚动、支持键盘聚焦。

## 数据与资源边界

- 手填与计算预览各保留当前编辑值；取消成本×K时还原尚未发布的手填值，不用预览覆盖它。发布/重读后以服务当前价格重新建立编辑状态，不引入第二份持久化价格。
- 图中两位小数是示例文案，不新增单价先舍入两位规则；例如0.335×3仍显示精确1.005。实际发布、旧价格兼容和历史订单规则沿用现有Rust接口。
- 原始下拉/删除矢量从实例 `I59:925;58:821` / `I59:925;58:841` 只读导出，保存为 `price-chevron.svg` / `price-trash.svg`；临时下载地址实际返回HTML，未写入产品。两个SVG保留原生20×20与原字节，使用14px/16px容器及等比变换对应Figma实例尺寸；删除透明度已在SVG内，不重复叠加。来源许可沿用[Lucide 0.468.0 ISC](figma-asset-licenses.md)。无临时URL运行时依赖。
- Noto Sans SC用于中文，Inter仅用于数值输入；不把中文表头切到数字字体。现有顶部导航、退出位置、报价及订单流程保持。

## 验证与续接

实现与辅助验证见[本次证据](../verification/P07-03-price-figma-checks.json)。浏览器对照四种状态及1440/1100/720/640宽度，检查数值列文字边距、分组分界、80px行高、控件包含关系、原图标有效尺寸、中文表头、键盘滚动与新增焦点；真实临时Rust HTTPS/桌面验证桥覆盖精确预览、无效输入阻止发布、两模式切换、发布/重读、报价金额与销售隔离。

P07-03继续执行；当前设计采用已获授权，运行界面的用户验收和新版Windows WebView2 CI/实机验证仍分别记录。P07-04/P08未启动；辅助Chromium不代替Windows验收。
