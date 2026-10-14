# P07当前Figma与组件映射

来源：`uniquenesssta/777`的`Figma@c517d8b3086932abe2dc01908e4dae3209b9f956`；只复制该提交的四份交接/状态/tokens/许可文档，未合并其AGENTS或写入Figma。[当前文件](https://www.figma.com/design/2ek9bkIz5ldyhjZnnvIuNu)，当前页21:2。四份快照保留原字节；本文件登记实现差异。

| 当前设计 | 实现 | 已核对/边界 |
| --- | --- | --- |
| 母版报价21:3 / 子版40:1604 | features/QuotePage.tsx、ui、tokens.css | 紫灰横向工作台、40px客户行、60px商品/折扣行、右侧360px；母版1440×884下主卡x40/y104/h748；销售无成本卡 |
| 管理订单32:96 / 销售40:2145 | features/OrdersPage.tsx | 全量20行分页、搜索/状态、真实签名view、保留页/筛选/滚动；设计日期/创建人静态筛选无对应服务接口，本项不伪造可用控件 |
| 管理详情32:499 / 销售40:1915 | features/DetailPage.tsx | 冻结明细、追加备注、管理作废恢复及原因确认、销售字段投影 |
| 紧凑提交32:818 | QuotePage + Radix Modal | 380×194、客户/订单/总额、96×36双按钮，Escape取消；不加入被撤销的重复信息 |
| Foundations46:727 / 组件47:979 | tokens.css、ui/components.tsx | 复用导出语义token，组件为本仓库React源码；未配置Figma Code Connect，不能把手工映射称自动连接 |
| 价格/利润/任务/设置 | features/ManagementPages.tsx、OrdersPage profit模式 | 服务真实功能，沿用同一token/组件；没有完整独立批准稿，仍需用户视觉验收 |

原始矢量通过Figma实例SVG_STRING只读导出，未重画：22:285→a09ba.svg(14×14)、22:327→09c30.svg(14×14)、22:374→74181.svg(16×16)、22:448→2eb61.svg(16×16)、22:483→7bfb4.svg(13×13)。22:273品牌36×36 PNG直接封装ICO用于原生窗口。临时资产URL返回HTML的失败已排除，提交文件均为实际SVG/ICO，渲染检查核对全部原尺寸。

shadcn CLI info已执行，确认原项目无框架/registry/preset；registry docs请求连接失败，已查官方Radix/shadcn文档。最终采用项目源码组件和Radix Dialog，无shadcn registry组件安装，不宣称完成Code Connect或整套Hallmark流程。

浏览器辅助截图使用显式hash锁定Noto Sans SC测试字体，不安装系统字体；生产目前使用CSS字体回退，精确字体打包与100/125/150/200% DPI留P07-03。测试截图中的客户/商品/订单均为临时合成数据，生产入口无示例数据。Windows WebView2原生视觉与用户确认仍待完成。
