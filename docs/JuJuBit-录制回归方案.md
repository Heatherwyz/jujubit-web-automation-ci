# JuJuBit 真实录制微调回归方案

## 1. 目标

当首页或其他页面发生真实 UI 变化时，测试人员可以用真实浏览器重新走一遍用户路径，快速确认变化位置，并把最小必要修改回填到现有 Page Object。最终回归仍使用当前项目的 pytest、Playwright Python、PC/H5 参数化和 HTML/JUnit 报告，不引入第二套执行框架。

## 2. 总体流程

```mermaid
flowchart LR
    A[线上页面发生变化] --> B[真实浏览器 Codegen 录制]
    B --> C[保存 inbox 原始录制]
    C --> D[静态校验与人工评审]
    D --> E[微调 HomePage/Page Object]
    E --> F[运行受影响 PC/H5 用例]
    F --> G[HTML/JUnit/截图/录像报告]
    G --> H[脱敏后接受录制并提交]
```

录制承担“观察变化”的职责，Page Object 承担“稳定定位”的职责，pytest 用例承担“业务断言”的职责，报告承担“结果和证据”的职责。

## 3. 为什么不直接把 Codegen 文件当测试

Codegen 记录的是某一次页面状态，可能带有偶然的 CSS、`nth()`、固定等待、测试账号值或当前文案。直接把它放进 CI 会绕过仓库已有的：

- `HomePage` 的优惠弹窗关闭和 429 限速/重试；
- PC/H5 视口参数化；
- 登录态与购物车 Context 隔离；
- 失败截图、失败录像和中文报告；
- 需求用例与报告标题的同步约束。

因此采用“录制作为变更输入，现有测试作为回归出口”的方式。这样既能使用真实操作降低定位猜测，又保持报告口径和历史结果可比较。

## 4. 仓库内新增资产

| 资产 | 作用 |
|---|---|
| `scripts/record_ui_flow.py` | 启动 Playwright Codegen，统一 PC/H5 视口、`data-testid` 优先、输出目录和元数据。 |
| `scripts/validate_recording.py` | 不访问站点，检查录制语法、元数据、明显不稳定定位器和敏感输入。 |
| `recorded/inbox/` | 临时录制收件箱，默认 Git 忽略。 |
| `recorded/accepted/` | 脱敏、评审、回归后保留的版本化录制证据。 |
| `docs/JuJuBit-录制回归方案.md` | 项目级流程、边界和验收口径。 |
| `recorded/README.md` | 日常操作命令和录制评审清单。 |

## 5. 首页变化时的操作手册

### 5.1 录制真实路径

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name homepage-change \
  --url https://jujubit.ai/ \
  --platform pc
```

在打开的真实浏览器中完成与用户相同的操作。若要复核响应式变化，再录一次 H5：

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name homepage-change \
  --url https://jujubit.ai/ \
  --platform h5
```

如果需要登录态，显式使用本地未提交的状态文件：

```bash
--load-storage artifacts/auth/storage-state.json
```

录制结束后关闭 Codegen 窗口。目录内会有 `flow.py` 和 `recording.json`。

### 5.2 评审录制

```bash
.venv/bin/python scripts/validate_recording.py recorded/inbox/<录制目录>
```

通过后仍需人工看一遍生成代码：

- 入口 URL、关键点击和页面变化是否真的发生；
- 是否优先使用 role、label、testid 或稳定业务属性；
- 是否因为首页轮播、弹窗、列表顺序而生成了脆弱定位；
- 是否需要将候选等待改成“组件可见/状态完成”等可观察条件；
- 是否需要移除账号、验证码、Cookie、授权头和业务数据。

### 5.3 微调代码

以首页入口变化为例，只修改 `python_playwright/pages/home_page.py` 中对应定位或等待逻辑，保留 `python_playwright/tests/test_home.py` 的业务断言。若变化属于需求变化，再同步测试名称和 `docs/JuJuBit-Shopify-首页改版-测试用例.md`；若只是 DOM/文案变化，不要无理由扩张用例范围。

### 5.4 最小回归和完整回归

先跑受影响的 PC 用例：

```bash
.venv/bin/python -m pytest -c pytest-playwright.ini \
  --pw-platform pc \
  python_playwright/tests/test_home.py \
  -k 'test_tc01 or test_tc07 or test_tc15'
```

再跑 H5：

```bash
.venv/bin/python -m pytest -c pytest-playwright.ini \
  --pw-platform h5 \
  python_playwright/tests/test_home.py
```

确认通过后执行当前完整入口：

```bash
.venv/bin/python run_all.py --platform all
```

报告仍归档到 `artifacts/runs/<时间戳>/`，不改变现有飞书通知和 CI 统计。

### 5.5 接受录制

录制只有在脱敏、静态检查和最小回归都通过后才进入版本库：

```bash
mkdir -p recorded/accepted/homepage
mv recorded/inbox/<录制目录> recorded/accepted/homepage/<日期>-<变更名>
.venv/bin/python scripts/validate_recording.py \
  recorded/accepted/homepage/<日期>-<变更名> --strict
```

提交应同时包含：Page Object 微调、测试断言（如有）、接受后的录制和文档说明。这样后续页面再次变化时，可以比较上一个真实路径和当前路径，而不是重新猜测定位器。

## 6. 失败归因

录制后回归失败时按以下顺序判断：

1. **录制路径错误**：录制是否真的完成了目标流程，是否被优惠弹窗、登录或验证码打断。
2. **定位变化**：录制能点到但现有 Page Object 点不到，通常只需更新定位器或等待。
3. **行为变化**：按钮名称、路由、组件状态或业务规则发生变化，需要更新需求用例和断言。
4. **环境问题**：429、验证码、网络超时、登录态过期或测试数据缺失，应按现有报告口径标记未完成，不能用重试掩盖产品缺陷。
5. **真实产品缺陷**：录制和人工操作也无法完成，保留失败截图/录像并按缺陷流程提交。

## 7. 版本和维护规则

- `recorded/inbox` 只用于临时探索；`recorded/accepted` 只保留有复盘价值的关键流程，不保存每次无差异录制。
- 原始录制可以较接近 Codegen 输出，但最终 Page Object 必须保持语义化、可维护和跨 PC/H5 可复用。
- 录制脚本不保存秘密；登录态、HAR、截图、录像留在被 `.gitignore` 排除的产物目录。
- 不因单次录制成功就删除原有断言；录制是定位证据，不是业务覆盖证明。
- 每次接受录制前运行 `tests/test_recording_workflow.py` 和受影响的 UI 用例。

## 8. 本方案的边界

本方案不自动替用户判断产品需求，也不自动修改 Page Object。真实录制降低了“页面变了以后定位器该怎么改”的探索成本，但最终修改仍需人工确认，尤其是涉及金额、登录、购物车和 Checkout 的流程。
