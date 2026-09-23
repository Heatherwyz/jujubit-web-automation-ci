# 给 AI 助手的项目约定

## 手动触发测试

用户会用自然语言让我跑测试（"跑一下"、"跑个回归"、"验证一下"）。**没有默认范围**——
各层耗时和副作用差别很大，先确认跑哪一层，不要自行假设。

| 层 | 命令 | 条数 | 耗时 | 访问站点 | 副作用 |
| --- | --- | --- | --- | --- | --- |
| 离线单测 | `.venv/bin/python -m pytest -q` | 390 | 3 秒 | 否 | 无 |
| HTML 契约 | `.venv/bin/python -m pytest -c pytest-playwright.ini -m html_contract -q` | 15 | 3 秒 | 两次 GET | 无 |
| 首页 UI | `.venv/bin/python run_all.py --platform pc`（或 `h5` / 省略跑双端） | 71 | 10-18 分钟 | 是 | 无 |
| 会员 | `.venv/bin/python run_all.py --membership-only --platform pc` | 92 | 15-20 分钟 | 是 | 无（支付只拉起表单，不付款） |
| 购物车 | `.venv/bin/python run_all.py --cart-daily` | 32 | 30-40 分钟 | 是 | **真实登录、创建生成任务、写入购物车** |

要点：

- 购物车层有外部副作用（会在测试账号下真实生成模型并加购），执行前说明清楚。
- **会员层的支付用例只走到拉起 Airwallex 表单**（断言表单就绪、SDK 挂载），
  不填卡、不点 Pay Now、不产生真实扣款。页面对象刻意不提供填卡与提交方法，
  `tests/test_membership_suite_wiring.py` 会守住这条边界。
- 会员的管理页与支付拉起用例需要登录态（`membership_session` marker）。
  `page` fixture 会为这个 marker 加载 `artifacts/auth/storage-state.json`。
  缺文件或 Cookie 过期时它们会如实报"未完成"而不是失败。
  每日全量与会员工作流都会把这份 Secret 写回 Runner 上的同一路径。

### 登录态怎么拿

Shopify Customer Accounts 的会话凭据是 `_shopify_essential`（HttpOnly，
不是旧版 legacy 的 `_secure_customer_sig`）。页面脚本、DevTools 的 Cookie
面板、内置浏览器的自动化接口都读不到值，必须用下面两种方式之一：

```bash
# 首选：内置窗口已登录过时，直接从它的 profile 提取（免验证码）
.venv/bin/python scripts/import_iab_storage_state.py

# 备选：开独立浏览器手工登录一次（要收邮箱验证码）
.venv/bin/python scripts/export_storage_state.py --email <账号邮箱>

gh secret set PLAYWRIGHT_STORAGE_STATE_JSON < artifacts/auth/storage-state.json
```

**登录入口必须是 `/customer_authentication/login`。** 它和 `/account/login`
是两条 OAuth 链路，client_id 不同：后者回调到
`shopify.com/<shop_id>/account/callback`，只给 Shopify 托管账户页种会话，
店面仍是未登录。踩过的坑是托管账户页能打开、订单都能看，但会员页 overview
仍显示 `Log in to view your plan`，`membership_session` 用例照样拿不到数据。

判定登录成功只认一条：会员页 overview 显示账号邮箱。付费墙上的
`Current Plan` 不算——未登录用户看到的 Basic 默认档也是这样。

### 会员用例的四个断言陷阱

都是"手工验证能过、用例必败"或"恒真恒假"的写法，已在离线层钉住
（`PaymentAssertionTrapTests`、`MembershipAdminPageTests`）：

- **`.jjb-membership-checkout` 常驻 DOM**，未拉起支付时就存在（隐藏态），
  且 `__plan` / `__price` 预置了 `Pro Membership`、`$19.90` 模板文案。
  用 `count()` 判断会误判成"已出现"并读到与当前档位无关的假数据。一律用
  可见性判断（`_visible_text` / `payment_layer_visible`）。
- **Airwallex 托管页按 locale 渲染**：CI 的 Chromium 显示中文
  （`订阅 …`、`每月 预付结算`、`$191.04 USD 今日应付金额`），手工打开常是
  英文。断言锚点必须语言无关；金额取紧跟 `USD` 的那个——中文把标签放在
  金额后面，按标签往后捕获会抓到小计原价，把已生效的折扣误判成没打折。
- **管理页入口是会员页的 MEMBERSHIP 视图**，不是 `/account`。后者 302 到
  Shopify 托管页，只有 Profile / Orders。页签是 `role=tab` 按钮，
  `a[href*="membership"]` 实测 0 命中、恒假。
- **两层弹窗都要关**：newsletter 弹窗拦匿名用例，会员 offer 弹窗
  （登录态下约 9 秒才渲染成 900px 遮罩）拦登录用例。只关一个仍会报
  `intercepts pointer events` 的 click timeout。另外 `page.reload()` 必须
  指定 `wait_until="domcontentloaded"`，默认等 `load` 会 30 秒超时。
- 默认回归（`run_all.py` 不带参数）**不含**会员层，需显式 `--membership`
  或 `--membership-only`。
- 单跑某一条：`pytest -c pytest-playwright.ini "路径::函数名" --pw-platform pc`
- UI 层耗时长，用后台执行并轮询，不要让命令超时。
- **改动 fixture 或分层结构后，必须跑一次"浏览器层 + 契约层混跑"**（71 条 = 首页
  62 + 契约 9）：两层单独跑都可能过，只有同进程混跑才会暴露运行时冲突（历史上
  出现过契约层自建 Playwright 运行时导致 9 errors）。命令：

  ```bash
  .venv/bin/python -m pytest -c pytest-playwright.ini \
    -m "not cart_session" --pw-platform pc -q
  ```

## 怎么读结果

判断一轮回归是否可信看**有效覆盖**，不是通过率。

- **业务失败** = 站点功能不符合预期，要立刻查。
- **未完成** = 用例没跑到断言（429 频控、人机验证、缺登录态、已知问题豁免），
  它没有验证任何业务行为，既不算通过也不算失败。

13 通过 + 17 未完成的通过率是 100%，有效覆盖只有 43%——七成用例没验证，不能据此放行。

终端汇总、HTML 报告首屏、飞书卡片三个出口口径一致；只要存在业务失败就优先判失败。

### 三个查看入口

| 入口 | 看什么 | 怎么到 |
| --- | --- | --- |
| 飞书卡片 | 结论、有效覆盖、**失败用例名与原因** | 群消息 |
| **Job Summary** | 完整渲染报告：失败表、未完成表+处置建议、模块结果 | 卡片「查看运行摘要」按钮 → Actions 运行页 |
| HTML 报告 | pytest-html 原始报告（含截图录像链接） | 卡片「下载 HTML 报告」，需下载后本地打开 |

**Job Summary 是主要阅读入口。** GitHub 对仓库内 `.html` 强制
`text/plain` + `nosniff`，浏览器只显示源码不渲染；私有仓库又不能用 Pages
（需付费套餐，且 Pages 内容公网可访问，而报告含站点地址与失败详情）。
所以结论渲染在 Job Summary，HTML 报告作为存档托管在 `test-reports` 分支
（每套件保留 30 份，索引为该分支的 `index.html`）。

生成逻辑在 `scripts/write_job_summary.py`，与终端、飞书卡片共用同一份解析，
三处口径一致。

## 修失败时的原则

这个项目历史上有 7 个提交标题带"误报"，`pytest.skip` 有 10 处。**把失败改判成
"未完成"或放宽断言，是这个仓库最需要警惕的模式**——它会让通过率失去信息量。

遇到失败时：

1. 先确认是站点真问题还是用例期望值写错了。查线上实际值，不要直接改断言让它变绿。
2. 期望值确实过时 → 改期望值，说明依据。
3. 站点真问题但暂时不修 → 用 `pytest.xfail` 记为已知问题，写清恢复条件
   （参考 `KNOWN_LAZY_HERO_PLATFORMS`）。不要删断言，也不要无条件 skip：
   删断言会连另一端的保护一起丢，无条件 skip 在报告里读不出"为什么没验证"。
4. 环境问题（429、人机验证）→ 已有熔断与冷却机制处理，不要新增豁免。

已知的断言陷阱（都踩过）：

- `not_to_be_visible()` 对 0 个元素**恒真**；`is_visible()` 对 0 个元素**恒假**，
  会让整段检查被静默跳过。依赖标记的 locator 尤其危险。
- 条件包裹的断言（`if x.count(): assert ...`）要确认条件在线上不会恒假。
- 对整页 HTML 做子串匹配会被导航/footer 里的同名文案满足。

## 分层原则

新增断言时先问：**这条需要浏览器吗？**

- 不需要 JavaScript、视口、登录态 → 写进 `python_playwright/home_contract.py`，
  在 `HOME_HTML_CONTRACTS` 登记，契约层自动多一条记录，并补一条离线单测。
- 需要真实点击、可见性、遮挡判断 → 才放进浏览器层。

契约层还负责把浏览器层"没有就跳过"的前置条件变成硬断言。

## 提交前

- 离线单测必须全绿（CI 在每个 PR/push 上跑，见 `.github/workflows/offline-checks.yml`）。
- 碰了 `cart_page.py` 或 fixture，跑一次混跑验证。
- 不要用 `git add -A`：`.mimosa/` 是安全扫描的本机缓存（含源码快照），已在
  `.gitignore` 里，但 `-A` 曾把它误提交过。
- 超时值用 `cart_page.py` 顶部的 `TIMEOUT_*` 语义常量，不要写裸字面量。
