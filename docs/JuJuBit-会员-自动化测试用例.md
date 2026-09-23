# JuJuBit 会员自动化测试用例

> 需求来源：内部飞书 wiki 14 篇文档。原文属公司内部资产，只保留在本地
> `docs/requirements/`（已在 `.gitignore` 中，不随仓库分发）。
> 确认后的期望值已沉淀进 `python_playwright/membership_contract.py`，
> 测试不依赖这些原文。

## 设计原则

1. **支付走到拉起即止**：入口 → 选档 → 点 Get → Airwallex 半屏/全屏支付表单可见
   （断言 SDK 加载、卡号输入框出现），**不填卡、不点 Pay Now、不产生真实扣款**。
2. **断言以线上实际文案为准**，不照抄需求文档的拼写（原文有 AVALIBLE/AVAILBLE 等错误）。
3. **不确定的值不猜**：冲突已确认的用确认值，未确认的标 `FIXME` 并跳过。

## 确认的权益表

| 权益项 | Basic | Pro | Premium |
| --- | --- | --- | --- |
| 月付 | $0 | $19.90 | $199.90 |
| 标准年付 | $0 | $238.80 | $2,398.80 |
| 首年年付（8 折） | — | $191.04 | $1,919.04 |
| 每日 Generate | 40 | 100 | 200 |
| 定额券 | — | $20 × 1/月 | $200 × 1/月 |
| 20% 券（封顶 $100） | — | × 3/月 | × 4/月 |

## 分层

| 层 | 条数 | 依赖 | 耗时 |
| --- | --- | --- | --- |
| 契约层（HTML） | 6 | 一次 GET | 约 2 秒 |
| 浏览器层 - 付费墙 | 12 | 无登录态 | 约 3 分钟 |
| 浏览器层 - 支付拉起 | 5 | 登录态 | 约 5 分钟 |
| 浏览器层 - 管理页 | 10 | 登录态（不同档位） | 约 4 分钟 |
| 浏览器层 - 引流入口 | 8 | 登录态 | 约 3 分钟 |
| 浏览器层 - 弹窗与计数 | 6 | 实验开关 | 约 3 分钟 |
| 埋点 | 4 | 网络拦截 | 约 2 分钟 |

---

## 契约层（MEM-C01 ~ MEM-C06）

请求 `/pages/vip-program` 服务端 HTML，不起浏览器。

| ID | 标题 | 断言 |
| --- | --- | --- |
| MEM-C01 | 付费墙包含三档名称 | Basic、Pro、Premium 文案存在 |
| MEM-C02 | Pro 月付价格 | `$19.90` / `19.90` 在 HTML 中 |
| MEM-C03 | Premium 月付价格 | `$199.90` / `199.90` 在 HTML 中 |
| MEM-C04 | 年付价格 | Pro `$238.80`、Premium `$2,398.80` |
| MEM-C05 | Most Popular 标记 | 文案 `Most Popular` 存在 |
| MEM-C06 | Q&A section 存在 | FAQ / Q&A 相关标记存在 |

---

## 浏览器层 - 付费墙页面（MEM-01 ~ MEM-10）

前置：打开 `/pages/vip-program`，无需登录。

| ID | 标题 | 前置 | 断言 |
| --- | --- | --- | --- |
| MEM-01 | Monthly 展示三档卡片 | 默认 Monthly | 三张卡片可见；Basic 标 Free；Pro 标 `$19.90/mo`；Premium 标 `$199.90/mo` |
| MEM-02 | Yearly 展示三档带折扣 | 切到 Yearly | 原价与现价同时展示；Pro 现价 `$191.04`；Premium 现价 `$1,919.04`；标注 `20% OFF` |
| MEM-03 | H5 默认 Monthly-Pro 卡片 | H5 视口 | 默认可见卡片是 Monthly-Pro |
| MEM-04 | 当前方案按钮置灰 | Basic 用户 | Basic 卡片按钮 `Current Plan` 且 disabled |
| MEM-05 | 高于当前按钮可点 | Basic 用户 | Pro 按钮 `Get Pro` enabled；Premium 按钮 `Get Premium` enabled |
| MEM-06 | 低于当前按钮置灰 | Pro 用户 | Basic 按钮 `Included` disabled |
| MEM-07 | 已退订有效期内按钮变 Resume | 已取消但仍在有效期 | 当前方案按钮 `Resume` enabled |
| MEM-08 | Pro 卡片 Most Popular | — | Pro 卡片有 `Most Popular` 推荐标记 |
| MEM-09 | Q&A 展示 | — | 底部 Q&A 可见 |
| MEM-10 | 未登录点 Get 先登录 | 未登录 | 点 Get Pro → 跳登录页 |

---

## 浏览器层 - 支付拉起（MEM-11 ~ MEM-15）

前置：已登录 Basic 用户。边界：**走到支付表单可见即止，不填卡不付款。**

2026-09-20 线上实测：登录态下点 Get **整页跳转**到
`checkout.airwallex.com/pay`，站内半屏容器不出现。用例两种形态都接受，
断言按以下两点避开陷阱：

- `.jjb-membership-checkout` 及其 `__plan` / `__price` 子节点**始终存在于
  DOM**，未拉起支付时也预置了 `Pro Membership`、`$19.90` 这类模板文案。
  必须按可见性判断，用 `count()` 会读到与当前档位无关的假数据。
- 托管页按 locale 渲染：CI 的 Chromium 显示中文（`订阅 …`、`每月 预付结算`、
  `$191.04 USD 今日应付金额`），手工打开常是英文。断言锚点必须语言无关，
  金额取紧跟 `USD` 的那一个——中文把标签放在金额后面，按标签往后捕获会
  抓到小计原价。

| ID | 标题 | 操作 | 断言 |
| --- | --- | --- | --- |
| MEM-11 | Pro Monthly 拉起支付 | 点 Get Pro (Monthly) | 支付表单就绪；套餐含 `Pro Membership`；账期为月付；dropin iframe 已挂载 |
| MEM-12 | Pro Yearly 拉起支付 | 切 Yearly → 点 Get Pro | 今日应付为首年 8 折价 `$191.04`（原价 `$238.80` 减 `-$47.76`） |
| MEM-13 | Premium Monthly 拉起支付 | 点 Get Premium (Monthly) | 支付表单就绪；套餐含 `Premium`；金额由契约层单独追踪 |
| MEM-14 | 支付失败兜底跳全屏 | 模拟 SDK 加载失败 | 自动跳 Airwallex 全屏 Hosted Checkout |
| MEM-15 | 支付失败弹窗文案 | 触发支付失败 | 弹窗文案 `Payment failed. Please try again.`；按钮 `Retry` |

---

## 浏览器层 - Membership 管理页（MEM-16 ~ MEM-25）

前置：已登录，不同档位。

管理页入口是会员页的 MEMBERSHIP 视图（`/pages/vip-program?tab=membership`），
**不是 `/account`**。后者会 302 到 Shopify 托管账户页
（`shopify.com/<shop_id>/account/orders`），那里只有 Profile / Orders，没有
MEMBERSHIP 页签。2026-09-20 线上实测确认。

| ID | 标题 | 前置 | 断言 |
| --- | --- | --- | --- |
| MEM-16 | 会员页视图 Tab 排序 | 已登录 | 会员页 role=tab 顺序 MEMBERSHIP → PLANS |
| MEM-17 | 会员标识-付费期内连续包月 | Pro 自动续费 | `Your plan is active and renews on {date}.` |
| MEM-18 | 会员标识-付费期内已取消 | Pro 已取消 | `Your plan expires on {date}.` |
| MEM-19 | Basic 不展示到期时间 | Basic | 无 Billing Cycle 到期时间 |
| MEM-20 | Primary Button-Basic/Pro 自动续费 | Basic 或 Pro | 按钮 `Upgrade` 可点击 |
| MEM-21 | Primary Button-已取消续费 | Basic/Pro 已取消 | 按钮 `Resume` 可点击 |
| MEM-22 | Primary Button-Premium 自动续费 | Premium | 按钮 `View` 可点击 |
| MEM-23 | Daily Generations 直接展开 | 任意档位 | 展示总额度、已使用额度、重置时间 |
| MEM-24 | Available Coupons 无券空态 | 无可用券 | `No membership coupons available yet.` |
| MEM-25 | Billing History 展开后正确渲染 | 已登录 | 折叠区展开后非空；有记录时每条含金额与日期，无记录时 `No billing history yet.` |

---

## 浏览器层 - 引流入口与 Banner（MEM-26 ~ MEM-33）

| ID | 标题 | 前置 | 断言 |
| --- | --- | --- | --- |
| MEM-26 | Generate 入口 basic 触发 | Basic 在画板 | `Members save $20+` + `Upgrade Now` 可见 |
| MEM-27 | Generate 入口非 basic 不展示 | Pro/Premium | 无引流 banner |
| MEM-28 | Cart 入口-折扣≤$20 取 $20 | Basic，购物车折前 < $100 | `Members save $20` |
| MEM-29 | Cart 入口-折扣>$20 动态 | Basic，购物车折前 ≥ $100 | 文案金额随折前总额动态，上限 $100 |
| MEM-30 | Cart 折扣超 $100 显示 save more | Basic，本身折扣超 $100 | `Members: save more` |
| MEM-31 | Checkout 入口固定文案 | Basic | `Members save $20+` + `Upgrade Now` |
| MEM-32 | 四入口跳付费墙返回原页面 | 各入口进付费墙 | 返回时回到原入口页（entry_page 透传） |
| MEM-33 | 购物车 banner 会员强制展示 | Pro/Premium | 会员用户前端强制展示 banner |

---

## 浏览器层 - Generate 计数与弹窗（MEM-34 ~ MEM-39）

| ID | 标题 | 前置 | 断言 |
| --- | --- | --- | --- |
| MEM-34 | Basic 超限 toast | Basic 当日用满 40 次 | `Daily limit reached. Upgrade to Pro for more generations today, or try again tomorrow.` |
| MEM-35 | Pro 超限 toast | Pro 当日用满 100 次 | `Daily limit reached. Upgrade to Premium for more generations today, or try again tomorrow.` |
| MEM-36 | Premium 超限 toast | Premium 当日用满 200 次 | `Daily limit reached. Please try again tomorrow.` |
| MEM-37 | 会员弹窗标题与权益 | Basic + 实验组 | 标题 `JuJuBit Membership`；6 个权益 icon 文案可见 |
| MEM-38 | 会员弹窗主按钮 | Basic + 实验组 | `Join for $19.90/mo` |
| MEM-39 | 支付失败弹窗文案 | 支付失败 | `Payment failed. Please try again.` + `Retry` |

---

## 埋点断言（MEM-40 ~ MEM-43）

| ID | 标题 | 方式 | 断言 |
| --- | --- | --- | --- |
| MEM-40 | 入口曝光埋点 | 拦截请求 | `membership_entry_view` 含 `entry_page` |
| MEM-41 | 付费墙曝光埋点 | 拦截请求 | `membership_plan_impression` |
| MEM-42 | 已废弃事件不上报 | 拦截请求 | `begincheckout`/`purchase_click`/`activated` **不出现** |
| MEM-43 | 套餐点击埋点 | 拦截请求 | `membership_plan_click` 含 `plan_type`、`billing_cycle` |

---

## 测试环境

### 实验开关注入

```js
localStorage.setItem('_shop_mode', 'test');
location.reload();
localStorage.setItem('_statsig_override','{"show_vip_banner":{"enable":true}}');
```

### 测试支付卡（仅确认表单能接受输入，不提交）

- 卡号：`4035 5010 0000 0008`
- 有效期：`12/30`
- CVV：`123`
- 持卡人：`TEST USER`

### 预览链接

```
https://jujubit.ai/pages/vip-program?preview_theme_id=194830631283&entry_page=header
```

### 后台会员赠送（造测试数据）

内部运营后台的会员赠送页面，地址不写入仓库。需要造多档位测试数据时
向团队索取，或从本地 `docs/requirements/` 的需求原文中查阅。

---

## 不做什么

- 不点 Pay Now（走到卡号输入框即止）
- 不做升级扣费（涉真实按比例计费）
- 不做 dunning（依赖时间推进）
- 不做后端安全测试（幂等、验签、隔离）
- 不做首年 8 折终身一次的验证（不可重复测试）

---

## 线上实跑发现（2026-09-17）

### 真实选择器（不要凭猜写）

线上主题统一用 `jjb-membership-*` 前缀，我第一版凭猜写的 `pricing-card` /
`plan-card` 全部命中 0 个，导致 20 条用例集体失败。实测值：

| 用途 | 选择器 |
| --- | --- |
| 付费墙容器 | `.jjb-membership-paywall` |
| 三档卡片 | `.jjb-membership-card` |
| 卡片标题 / 价格 / 按钮 | `.jjb-membership-card__title` / `__price` / `__button` |
| Most Popular 标记 | `.jjb-membership-card__value-badge` |
| 周期切换 | `.jjb-membership-paywall__toggle` |
| Q&A | `.jjb-membership-paywall__qa` |
| 半屏支付弹窗 | `.jjb-membership-checkout` |
| 支付套餐 / 金额 / 账期 | `.jjb-membership-checkout__plan` / `__price` / `__billing-label` |
| SDK 挂载点 | `.jjb-membership-checkout__mount` / `__payment-form-host` |
| 会员开屏弹窗 | `.jjb-membership-offer` |
| 弹窗品牌 / 副标题 / 主按钮 | `.jjb-membership-offer__brand` / `__subtitle` / `__cta` |

### Premium 价格与确认值不一致（已登记为已知问题）

| 项 | 确认值 | 线上实际 |
| --- | --- | --- |
| 月付 | $199.90 | **$99.90** |
| 标准年付 | $2,398.80 | **$1,198.80** |
| 首年（8 折） | $1,919.04 | **$959.04** |

线上那组正是需求文档 4.5 权益表里并存的另一行，且 `959.04 = 1198.80 × 0.8`
（8 折关系成立），说明线上是一套自洽的价格，不是配错单个数字。

处理方式：`membership_contract.KNOWN_PRICE_MISMATCH_TIERS` 登记 Premium，
受影响的断言跳过该档位，另有一条 `test_membership_known_price_mismatch`
把差异记为**未完成**（xfail）。**没有把断言改成线上值**——那等于用实现反推
需求，一旦线上是配错的就永远发现不了。价格对齐后从该常量移除即可恢复硬断言。

### 支付拉起需要登录态

线上未登录点 `Get Pro` 会跳 Shopify 托管登录页（`shopify.com/authentication/...`），
半屏支付弹窗不出现。这是设计行为（MEM-10 已覆盖），所以 MEM-11~13 必须带
有效登录态。缺登录态时用例报"未完成"并给出配置提示，不伪装成通过。

### 其它实测细节

- Basic 卡片价格渲染为 **`FREE`**（大写），断言需不区分大小写
- Premium 价格在 HTML 源码里搜不到 `99.90`（数字被标签分隔），必须用渲染后的
  `innerText`
- 页面存在 newsletter 弹窗遮罩，会拦截卡片按钮点击——必须先
  `close_welcome_popup()`（这正是 2026-09-17 缺陷报告里那个残留 overlay）

### 当前实跑结果

| 范围 | 结果 |
| --- | --- |
| 契约层 6 条 | 5 通过 + 1 未完成（价格不一致），有效覆盖 83% |
| 付费墙 8 条 | 全部通过（MEM-01/02/04/05/08/09/10/32） |
| 支付拉起 3 条 | 未完成（缺本地登录态，需在 CI 用 Secret 验证） |
| 离线单测 | 359 条全绿 |
