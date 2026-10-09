# 独立站社区 Inspiration 测试用例

- 需求：[【独立站】社区inspiration页面](https://a9ihi0un9c.feishu.cn/wiki/BdYDwkEwBivBz4kazGJcCx1onzh)
- 技术文档：[Inspiration前端技术文档](https://a9ihi0un9c.feishu.cn/docx/Md4jdDN9Io8obBxVksHcjazFnGe)
- 日期：2026-10-08
- 自动化入口：`python_playwright/tests/test_inspiration.py`，默认不进每日回归，需显式 `--inspiration`

## 主流程

```text
实验组进入站点
  → PC 顶栏 / H5 菜单出现 Inspiration
  → 点击进入 SHOWCASE
  → 分区接口返回可见普通分区（排除 campaign）
  → 首个分区作为默认分区，首屏 Feed 成功
  → 作品卡：非操作区进详情，购物车图标进 SKU
  → Add to Cart 进全屏购物车 / Buy Now 进 Checkout
  → 返回后按 sessionStorage 快照恢复分区和作品位置
详情 + Remix → 复用现有 Edit → Save 后由 History 承接
```

对照组不展示入口，直接访问 Inspiration 路由时不加载实验组 Feed。

## 当前自动化口径

2026-10-08 实测 `https://jujubit.ai/` 的 PC 顶栏和 H5 菜单都没有 `Inspiration` 链接，页面上也没有 `/apps/ai/inspiration-tab-list` 分区。功能未对当前访问者放开时，自动化记为「未完成」，不记业务失败。入口放开后，同一条用例自动改为校验分区、Feed 和作品卡。

购买、Checkout、Remix 保存会改购物车或创建生成记录，本次只写用例，不放进默认可执行脚本。

## 一、功能用例

| 场景 | 前置条件 | 测试步骤 | 预期结果 | 优先级 |
| --- | --- | --- | --- | --- |
| PC 顶栏进入 Inspiration | 实验组；PC 1440×900 | 打开首页，关闭优惠弹窗，点击顶栏 `Inspiration` | 进入 SHOWCASE；首屏 Feed 成功后页面可用；上报 `inspiration_entry_click`，`source=pc_header` | P0 |
| H5 菜单进入 Inspiration | 实验组；H5 390×844 | 打开菜单，点击 `Inspiration` | 使用双列布局进入 SHOWCASE；`source=h5_menu` | P0 |
| 对照组不展示入口 | 固定对照组 | 看 PC/H5 导航，并直接访问 Inspiration 路由 | 导航无入口；直接访问不展示实验组 Feed，不上报成功访问 | P0 |
| 分区来自接口 | 实验组；分区接口可用 | 进入页面，抓 `POST /apps/ai/inspiration-tab-list` | 只渲染返回的普通分区，排除 `campaign`；首个分区默认选中；名称和顺序不由前端写死 | P0 |
| 切换分区 | 至少两个分区有数据 | 依次切换分区 | 选中项为黑底白字；加载该分区首屏；滚动回到 Feed 顶部；分页令牌重置 | P0 |
| Feed 首屏与分页 | 数据超过 20 条 | 等待首屏，再滚近底部 | 首屏成功前有骨架；每页 20 条；用返回的 `pagination.token` 追加下一页，不重复、不自行排序 | P0 |
| PC 作品卡状态 | 有单规格、多规格、不可售作品 | 默认查看，再 Hover | 默认以封面为主；Hover 显示标题、价格、购物车图标。单规格 `$X`，多规格 `From $X`；不可售或售罄只留标题 | P0 |
| H5 作品卡状态 | 同上，移动端 | 直接查看卡片 | 无 Hover，标题和可售信息默认可见；不可售规则与 PC 相同 | P0 |
| 卡片点击分流 | 可售作品 | 点封面非操作区；关闭后再点购物车图标 | 非操作区只进详情；购物车图标只进 SKU，不冒泡打开详情 | P0 |
| PC 作品详情 | Feed 已打开 | 点作品卡，再点关闭 | 居中弹层，背景 Inspiration 仍在；可切换 2D/3D，有 `+ Remix`、关闭、标题、描述、商品条和 `Buy Now` | P0 |
| H5 作品详情 | 移动端 Feed | 点作品卡，再返回 | 上作品、下信息的纵向结构；关闭后仍停留原分类和滚动位置 | P0 |
| 两个入口进同一 SKU | 可售且已配置固定 Product | 分别从卡片购物车和详情 `Buy Now` 进入 | 都进入同一 SKU 区。PC 右侧切换，H5 下方扩展；展示名称、促销、现价、划线价、Size、自定义尺寸、数量、`Add to Cart`、`Buy Now` | P0 |
| Add to Cart | SKU 选择合法且有库存 | 选规格和数量，点 `Add to Cart` | 成功后进入全屏购物车；商品、规格、数量、价格与所选一致；只在进入购物车后上报成功 | P0 |
| SKU Buy Now | 同上 | 点 SKU 内 `Buy Now` | 进入 Shopify Checkout；来源带 `source=inspiration` 和 `post_id`；只在结账流程确认后上报 | P0 |
| 购买后返回 | 已记录分区、分页令牌、作品 ID | 从购物车或结账返回 | 30 分钟内按 sessionStorage 快照恢复到原分区和目标作品；成功后删除快照 | P0 |
| Remix 进入与保存 | 作品可 Remix；Edit 服务可用 | 详情点 `+ Remix`，改提示词或姿势，点 `Save` | PC 为上层编辑弹层，H5 为全屏页；workflow 不可改；保存成功后由 History 承接 | P0 |
| Remix 返回 | 从详情进入 Remix | 点左上角返回 | 回到原作品详情，不产生新的 History 记录 | P1 |

## 二、场景覆盖

| 场景 | 判定点 | 优先级 |
| --- | --- | --- |
| 直接输入路由进入 | `inspiration_page_view.source=direct`；首屏成功才上报访问，失败只上报 `inspiration_feed_error` | P0 |
| 分区切换时旧请求晚返回 | 最终只显示后选分区的数据，选中态和分页令牌不回退 | P0 |
| Feed 与详情两个购买入口 | 购物车图标 `open_source=feed_cart_icon`，详情按钮 `open_source=detail_buy_now` | P0 |
| 购物车和结账分别返回 | 两条返回都恢复进入前的分区、分页和作品位置 | P0 |
| Remix 后购买 | 购买归因 `purchase_route=remix`；直接购买为 `direct` | P1 |
| 同账号刷新、重进、跨页面 | AB 分组保持不变，且不改变原 Create 入口 | P1 |

## 三、边界条件

| 边界点 | 判定点 | 优先级 |
| --- | --- | --- |
| 分区只有 1 个、作品 0/1/20/21 条 | 0 条展示空状态且 `content_state=empty`；20 条不提前请求；第 21 条才使用下一页 token | P0 |
| 快照刚好 30 分钟和超过 30 分钟 | 30 分钟内可恢复；超时、解析失败、站点不匹配都删除快照并走正常首屏 | P0 |
| 数量 0、空、超库存、自定义尺寸边界 | 阻止提交，不发购买请求，不上报成功事件 | P0 |
| 作品曝光 50% 与 1 秒 | 未达 50% 或不足 1 秒不上报；同一次页面挂载内同一 `post_id` 只报一次 | P1 |
| PC 宽、中、窄宽度 | 列数自适应，卡片不重叠；H5 保持双列 | P1 |
| 图片加载失败 | 只替换该作品兜底图，标题、价格和点击仍可用 | P1 |

## 四、异常处理

| 异常场景 | 判定点 | 优先级 |
| --- | --- | --- |
| 分区或 Feed 返回 500、超时、乱序 | 展示空状态，不显示后端错误；上报 `stage`、`http_status`、`error_code`、`tab_id`、`page_token`、`trace_id` | P0 |
| 固定 Product 未配置或无可用 Variant | Feed 和详情仍可浏览，隐藏价格、购物车、Buy Now 和 SKU；上报 `inspiration_product_config_missing` | P0 |
| Add to Cart 或 Buy Now 失败 | 停留原页面并提示可理解的错误；未跳转时删除恢复快照；不上报成功 | P0 |
| Remix 保存失败 | 已填内容保留，不产生错误 History；恢复后重试只产生一条成功记录 | P0 |
| 目标作品在返回时已不存在 | 已恢复的列表保留，定位到列表顶部，不报恢复未命中 | P1 |
| 429 或人机验证 | 用例记未完成，不记业务失败，也不自动绕过验证 | P0 |

## 五、数据情况

| 数据条件 | 判定点 | 优先级 |
| --- | --- | --- |
| 标题、描述含 emoji、多语言和超长文本 | 卡片、详情不串位、不溢出到相邻按钮 | P1 |
| 单规格、多规格、不可售、售罄同时存在 | 每种状态文案和图标严格对应，不串用上一种商品价格 | P0 |
| 作品带 2D、仅 3D、两者都有 | 2D/3D 切换只改变当前作品展示，不触发购买 | P1 |
| 新老登录态和未登录 | 浏览不强制登录；购买沿用现有 Shopify 登录要求 | P1 |
| PC 与 H5 | 同一作品的标题、价格、规格和库存一致 | P0 |

## 六、埋点

| 场景 | 判定点 | 优先级 |
| --- | --- | --- |
| 入口和访问 | 点击报 `inspiration_entry_click`；首屏成功才报 `inspiration_page_view` | P0 |
| 作品曝光 | 字段含 `post_id`、`category`、`position`；同挂载周期去重 | P1 |
| 详情、SKU、Remix | 各自曝光和点击只触发对应事件，`source` 不串 | P0 |
| 购买归因 | 成功进入购物车或结账后才补 `source=inspiration`、`post_id` | P0 |
| 离开页面 | `inspiration_page_exit` 含有效停留秒数、去重作品数和 `route_change/page_leave` | P1 |

## 待确认疑点

1. 实验名、分组存储位置和 Inspiration 最终路由都没有给出。对照组“直接访问如何拦截”因此不能写成具体 URL 断言。
2. 产品要求固定分类 `For You、TRPG、Pop、Anime`，技术文档要求分区完全由接口返回且排除 `campaign`。自动化当前按技术文档，不把四个名称写成硬编码。
3. 产品写每个作品自身的价格和售卖状态；技术文档写所有作品共用一个 Liquid 固定 Product，并忽略 Feed 里的产品字段。价格和售罄断言以实际上线 DOM 为准。
4. 技术文档明确详情到 SKU 的切换动画本期不做，产品仍要求淡入淡出。自动化只验证到达正确区域，不断言动画。
5. `position`、Remix 是否已有旧埋点、购买是否存在 `purchase_route=remix`，技术表中仍是疑问句，未纳入硬断言。
6. 空状态、首屏骨架和售罄的最终文案、视觉尚未在文档中给出。
