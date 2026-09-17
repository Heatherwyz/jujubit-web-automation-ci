# JuJuBit 首页缺陷报告（2026-09-17）

> 来源：每日首页 UI 回归 [运行 35186182117](https://github.com/Heatherwyz/jujubit-web-automation/actions/runs/35186182117)
> 结果：71 条中 9 条业务失败，有效覆盖 97%（69/71 得出业务结论）
>
> 两个缺陷均已直连 `https://jujubit.ai` 复现，不依赖 CI 环境。

## 结论先行

| 缺陷 | 影响面 | 严重度 | 建议 |
| --- | --- | --- | --- |
| 弹窗遮罩残留，H5 用户点不开导航菜单 | 移动端全部用户 | **阻断** | 立即修 |
| 整个 Footer 从主题中消失 | 全端 | 高 | 尽快修 |

判断这一轮可信的依据：有效覆盖 97%，无频控、无环境拦截。相同用例在
2026-09-16 的两次运行中 **全部通过**，其间未改动任何测试代码。

---

## 缺陷 1：newsletter 弹窗遮罩残留，拦截 H5 导航点击（阻断）

### 现象

H5 端点击 Header 的菜单按钮无反应，导航抽屉无法展开。

### 复现步骤

1. 移动端视口（如 390×844）打开 `https://jujubit.ai`
2. 等待页面加载完成（不要触发 newsletter 弹窗）
3. 点击 Header 右上角菜单按钮（`aria-label="Site navigation"`）

预期：导航抽屉展开。实际：点击无任何响应。

### 根因证据

`.newsletter-popup-v2__overlay` 铺满整个视口且仍可接收点击，但弹窗本身并未打开：

```
pointerEvents:   auto        ← 会拦截点击
position:        absolute
size:            390x844     ← 与视口等大
coversViewport:  True
popupOpen:       False       ← 弹窗没开，遮罩却在
```

也就是说：newsletter 弹窗关闭（或从未打开）后，遮罩层没有被移除，也没有把
`pointer-events` 置为 `none`，于是它静默吃掉了下方所有点击。

自动化侧的表现是 Playwright 点击超时：

```
Locator.click: Timeout exceeded
  - <div class="newsletter-popup-v2__overlay"></div> from
    <div id="shopify-section-sections--29102207336819__newsletter-popup"> …
    intercepts pointer events
```

### 建议修复方向

弹窗未展示时，遮罩应满足任一条件：不渲染、`display:none`、或
`pointer-events:none`。请检查 newsletter-popup section 的关闭逻辑与初始状态。

### 受影响用例（5 条，均 H5）

- TC-07 主导航包含核心入口
- TC-08 主导航链接均为站内地址
- REQ-04B 首页配置的导航与 Hero 链接可真实打开
- REQ-07 当前一级导航均使用有效真实链接
- REQ-11 Header 与品类导航 URL 符合需求

---

## 缺陷 2：整个 Footer 从 Shopify 主题中消失（高）

### 现象

PC 与 H5 端页面底部都没有 Footer：地区/币种切换器、社交平台入口、Footer
导航链接全部不存在。

### 根因证据

页面共渲染 15 个 Shopify section，**其中没有任何 footer**：

```
sections--…__jjb_announcement_bar
sections--…__jjb_header
sections--…__newsletter-popup
template--…__jjb_banner / jjb_template_entry / jjb_how_it_works
template--…__jjb_category / jjb_products / jjb_showcase / jjb_credit
template--…__jjb_comment / jjb_social_media / jjb_faq / hero-video
```

浏览器实测（PC 与 H5 结果一致）：

```
footer 元素数：            0
可见社交链接（instagram）： 0
localization-form：        0
[name=country_code]：      0
window.theme.sections：    仅 header、video-section 两个
hasFooterSection：         False
```

### 一个容易误判的点

服务端 HTML 里搜 `instagram.com` 能命中 1 次，但它位于 **JSON-LD 的 `sameAs`
字段**（结构化数据），不是 Footer 的真实锚点：

```json
"sameAs": [ "https://www.instagram.com/thisisjujubit_/",
            "https://www.youtube.com/@thisisjujubit", … ]
```

所以「HTML 里有社交链接」不代表页面上有 Footer 入口。这也是为什么结构化数据
仍然声明社交账号，而页面却一个都点不到——两者已经不一致。

### 影响

- 用户无法从底部导航、切换地区/币种、访问社交账号
- 结构化数据声明的 `sameAs` 与页面实际内容不符
- Footer 常含隐私政策、退款政策等合规链接，缺失可能带来合规风险

### 建议修复方向

检查 Shopify 主题编辑器中 Footer section 是否被误删，或 `theme.liquid` 中
Footer 的渲染是否被移除。

### 受影响用例（4 条）

- REQ-05 Footer 地区与币种切换器可见且可展开（PC + H5）
- REQ-06 Footer 当前社交平台地址、名称与安全属性正确（PC + H5）

---

## 修复后如何验证

```bash
# 只跑受影响的用例（约 2 分钟）
.venv/bin/python -m pytest -c pytest-playwright.ini -q \
  "python_playwright/tests/test_home_requirements.py::test_footer_locale_switcher_is_available" \
  "python_playwright/tests/test_home_requirements.py::test_external_social_links_are_safe" \
  "python_playwright/tests/test_home.py::test_tc07_navigation_has_core_entries"

# 或跑完整首页回归（约 15 分钟，71 条）
.venv/bin/python run_all.py --platform pc
```

两个缺陷修复后，这 9 条应全部转为通过，有效覆盖回到 100%。
