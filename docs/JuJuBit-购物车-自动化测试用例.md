# JuJuBit 购物车自动化测试用例

> 本文档由 `python_playwright/cart_cases.py` 自动生成，请勿直接修改。
> 修改结构化用例后运行 `.venv/bin/python scripts/sync_cart_case_docs.py` 同步。

## 1. 范围与执行口径

- 共 `15` 个逻辑 pytest 函数；每个函数按 PC/H5 参数化，完整执行生成 `30` 条独立报告记录。
- 所有购物车用例遇到首页优惠弹窗都会先关闭，再继续操作。
- `CART-02` 是唯一发起真实上传和生成任务的逻辑用例；PC/H5 各执行一次时会分别产生一次生成任务。
- `CART-03` 至 `CART-15` 独立清空购物车后复用账号 Gallery 中已有的成功资产，不依赖上一条用例遗留的购物车状态；无可复用资产时明确跳过。
- 涉及 Checkout 的用例只验证进入结算页及订单摘要，不提交订单、不点击支付。
- AB 实验和失效商品不在本轮范围内；角标 `99+` 使用同一 SKU 数量 100 验证。

## 2. 主流程

1. 从 `jujubit.ai` 首页点击 Header 左上角 Create，进入创作页。
2. 上传图片并生成，确认本次 Gallery 结果同时具备真实加载的 2D 图片与就绪的 3D renderer。
3. 从 Gallery 加购生成模型，确认保持在创作页并打开半屏购物车。
4. 从半屏购物车直接进入 Checkout，验证当前商品摘要。
5. 返回 Gallery，经 Header 右上角 Cart 进入全屏购物车。
6. 从全屏购物车进入 Checkout，验证当前商品摘要。

其余用例在该主流程基础上独立覆盖角标、内容完整性、包邮临界值、数量联动、空态、数量上限、视图一致性和失败请求保护。

## 3. 自动化用例

| ID | 用例名称 | 真实函数名 | 优先级 | 前置条件 | 操作步骤 | 预期结果 |
|---|---|---|---|---|---|---|
| CART-01 | 首页 Header Create 可进入创作页 | `test_cart_tc01_header_create_opens_creator` | P0 | JuJuBit 首页可访问。 | 关闭优惠弹窗，点击 Header 左上角 Create。 | 进入 /products/customize-your-own；创作组件挂载，上传框、Create、Gallery 和 Generate 控件存在。 |
| CART-02 | 上传图片后 Gallery 展示本次 2D 与 3D 结果 | `test_cart_tc02_upload_result_has_2d_and_3d` | P0 | 账号登录态有效且生成服务、账号配额可用。 | 记录 History 数量，上传固定图片，只点击一次 Generate，等待本次任务完成。 | History 增加；2D 图片真实加载；3D renderer 完成并可在 2D/3D 间切换。 |
| CART-03 | Gallery 模型加购后打开半屏购物车 | `test_cart_tc03_gallery_add_opens_drawer` | P0 | 账号 Gallery 中存在已完成且可购买的 2D/3D 资产。 | 清空购物车，从 Gallery 点击 Add to Cart。 | cart/add.js 成功；仍停留创作页；半屏购物车展示商品、SKU、价格、数量 1 和 Checkout (1)。 |
| CART-04 | 半屏购物车可进入 Checkout | `test_cart_tc04_drawer_checkout_opens_checkout` | P0 | 半屏购物车内有 1 件 Gallery 生成商品。 | 记录购物车商品后点击半屏 Checkout。 | 直接进入 /checkout 或 /checkouts/...；页面主体和当前商品摘要可见，不提交订单或支付。 |
| CART-05 | Header Cart 可进入全屏购物车 | `test_cart_tc05_header_opens_full_cart` | P0 | Gallery 商品已加购，半屏购物车内有 1 件商品。 | 记录半屏数据并关闭半屏，点击右上角 Cart。 | 进入 /cart；全屏购物车商品、数量、金额和包邮状态与半屏一致。 |
| CART-06 | 全屏购物车可进入 Checkout | `test_cart_tc06_full_cart_checkout_opens_checkout` | P0 | 全屏购物车内有 Gallery 生成商品。 | 点击全屏购物车 Checkout。 | 进入 Checkout；页面主体和当前商品摘要可见，不提交订单或支付。 |
| CART-07 | Cart 角标覆盖 0、1、99 与 100 | `test_cart_tc07_header_badge_boundaries` | P0 | 同一 SKU 可调整到 100 件。 | 依次验证空车、加购 1 件、输入 99 件和输入 100 件。 | 0 不显示角标；1 和 99 直显；100 显示 99+，且 Checkout 件数同步。 |
| CART-08 | 半屏与全屏购物车核心内容完整 | `test_cart_tc08_drawer_and_full_cart_content` | P0 | 购物车内有 1 件 Gallery 生成商品。 | 分别检查半屏和全屏的标题、关闭入口、包邮区、商品卡、Subtotal、You Save 与 Checkout。 | 实际线上文案和必需控件完整；优惠字段仅在有优惠时显示；两种视图数据一致。 |
| CART-09 | 包邮金额覆盖 98.99、99.00 与 99.01 临界值 | `test_cart_tc09_free_shipping_boundaries` | P0 | 购物车前端组件已加载。 | 向线上购物车组件注入 9899、9900、9901 美分的可控 subtotal 并刷新包邮区。 | 98.99 显示还差 $0.01；99.00 和 99.01 显示已获包邮；进度分别小于 100% 和等于 100%。 |
| CART-10 | 数量加减后购物车汇总实时联动 | `test_cart_tc10_quantity_buttons_update_totals` | P0 | 半屏购物车内同一 SKU 数量为 1。 | 点击 + 到 2，再点击 - 回到 1。 | 数量、角标、Subtotal、包邮提示和 Checkout (n) 同步；数量 1/2 时删除与减号图标正确切换。 |
| CART-11 | 删除最后商品后展示空购物车 | `test_cart_tc11_delete_last_item_shows_empty_cart` | P0 | 半屏购物车内只有 1 件商品。 | 点击数量左侧垃圾桶删除最后一件商品。 | 商品和角标消失；展示 Your Cart is Empty 与差额 $99.00；进度为 0，Checkout 禁用。 |
| CART-12 | 数量输入上限为 100 | `test_cart_tc12_quantity_input_caps_at_100` | P0 | 半屏购物车内有同一 SKU。 | 数量框输入 101 并提交。 | 数量自动回正 100；角标为 99+；Checkout (100)；加号不可用，H5 输入框使用数字输入属性。 |
| CART-13 | 半屏与全屏数据一致且全屏 Close 正确返回 | `test_cart_tc13_views_stay_consistent_and_full_cart_closes` | P1 | 从 Gallery 加购并将同一 SKU 调整为 2。 | 记录半屏快照，关闭半屏后由 Header 进入全屏，再点击全屏 Close。 | 两种视图的商品、SKU、数量、Subtotal 和包邮状态一致；Close 返回原 Gallery，商品不丢失。 |
| CART-14 | Checkout 订单摘要与购物车一致 | `test_cart_tc14_checkout_summary_matches_cart` | P0 | 半屏购物车内同一 Gallery 商品数量为 2。 | 记录商品、数量和 Subtotal 后进入 Checkout。 | Checkout 展示同一商品与数量，页面金额可见；不点击提交或支付按钮。 |
| CART-15 | 失败请求不产生假购物车状态或非法金额 | `test_cart_tc15_failures_do_not_create_false_cart_state` | P1 | 存在可复用 Gallery 资产；浏览器支持路由模拟。 | 分别模拟 cart/add.js 与 cart/change.js 返回 500，并检查页面与服务端购物车。 | 不出现假加购、非法数量、白屏或 NaN/null 金额；失败保持可识别且购物车服务端数据不被错误修改。 |

## 4. 线上最终文案

以下文案保留线上组件实际大小写、标点和占位格式，自动化断言以此为准。

| 场景 | 最终文案 |
|---|---|
| 购物车标题 | `Cart` |
| 空购物车 | `Your Cart is Empty` |
| 小计标签 | `Subtotal` |
| 总优惠标签 | `You Save` |
| 单商品优惠 | `Save $XX.XX` |
| 未达到包邮门槛 | `Add $XX.XX more to enjoy Free Shipping` |
| 已达到包邮门槛 | `You've qualified for free standard shipping` |
| Checkout 按钮 | `Checkout (N)` |
| 100 件及以上角标 | `99+` |

其中当前包邮门槛为 `$99.00`：空车提示 `Add $99.00 more to enjoy Free Shipping`；`$98.99` 提示还差 `$0.01`；`$99.00` 及以上显示已获包邮文案。

## 5. 执行与同步

完整执行首页和购物车 PC/H5 用例：

```bash
.venv/bin/python run_all.py --include-cart
```

只收集购物车用例并确认应为 30 条：

```bash
.venv/bin/python -m pytest -c pytest-playwright.ini --collect-only -q python_playwright/tests/test_cart.py
```

修改 `python_playwright/cart_cases.py` 后同步本文档：

```bash
.venv/bin/python scripts/sync_cart_case_docs.py
```

离线同步测试会精确比对 `CART_CASES`、`test_cart.py` 的真实函数、报告 `CASE_TITLES` 和本 Markdown；任一侧遗漏或名称漂移都会失败。
