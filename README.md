# JuJuBit UI 自动化测试

本项目使用 `pytest + Playwright Python` 自动化方案，覆盖 JuJuBit 各 UI 模块的 PC 和 H5。

## 安装

```bash
cd /Users/wyz/pro/jujubit-web-automation
python3 -m venv .venv
.venv/bin/pip install -r requirements-playwright.txt
.venv/bin/playwright install chromium
```

## 一键执行

```bash
.venv/bin/python run_all.py
```

购物车端到端用例会真实上传图片、创建生成任务并修改购物车，因此默认不执行。
确认测试环境和账号配额可用后，显式执行首页与购物车全部用例：

```bash
.venv/bin/python run_all.py --include-cart
```

如只想执行单一登录上下文的购物车主链路（默认 PC/H5 各 1 条，且不重复执行首页），运行：

```bash
.venv/bin/python run_all.py --cart-smoke-only
```

该 Smoke 会在同一个 context 内完成“生成 2D/3D → 加购 → 半屏/全屏购物车 → Checkout”。
GitHub 会附加 `--platform pc`，只执行 1 条 PC 主链路；完整回归仍同时覆盖 PC/H5 30 条记录。

如只想执行全部 30 条购物车 PC/H5 记录，运行：

```bash
.venv/bin/python run_all.py --cart-only
```

`run_all.py` 默认让购物车关键请求相隔 6 秒；如在已获站点允许的专用测试环境中需要调整，
可附加 `--cart-request-interval <秒数>`。不要把间隔降为 0 来规避 429，这只会增加被频控的概率。

如站点出现 HTTP 429 或网站要求人工确认，可用有界面模式运行：

```bash
.venv/bin/python run_all.py --manual-verification
```

脚本会在出现 429 时暂停；请在弹出的浏览器中自行完成网站要求的确认，确认
页面显示后回到终端按 Enter，脚本会从当前 case 继续。脚本不会自动绕过人机验证。

该命令会自动：

1. 执行全部 PC/H5 用例。
2. 出现优惠弹窗时先关闭弹窗再继续操作。
3. 为失败用例生成视频。
4. 生成包含通过/失败明细的 HTML 报告。
5. 将报告和视频归档到 `artifacts/runs/<时间戳>/`。

每次运行结束后，终端会输出本次报告路径。例如：

```text
artifacts/runs/<时间戳>/jujubit-report-<时间戳>.html
```

打开报告后，可直接查看通过用例、失败用例，以及失败行中的“播放错误视频”链接。

## 目录说明

- `python_playwright/`：页面对象、fixture 和测试用例。
- `docs/`：需求测试用例设计。
- `recorded/`：真实浏览器 Codegen 录制资产；只用于页面变更评审和定位器微调，不直接作为 CI 回归脚本。
- `scripts/record_ui_flow.py`：统一启动 PC/H5 真实录制；`scripts/validate_recording.py`：离线检查录制语法、定位器风险和敏感输入。
- `run_all.py`：一键运行和按时间戳归档入口。
- `artifacts/runs/`：历史报告及关联失败视频。

## 页面变化时通过真实录制微调

当首页或其他页面的 DOM、文案或交互发生变化时，不需要另起一套测试框架。先用真实
Playwright Codegen 录制当前用户路径，再把经评审的最小定位器/等待变化回填到现有 Page
Object，最后仍由 pytest 和 `run_all.py` 执行回归、生成报告。

例如录制首页 PC 流程：

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name homepage-change \
  --url https://jujubit.ai/ \
  --platform pc
```

录制完成后检查临时目录：

```bash
.venv/bin/python scripts/validate_recording.py recorded/inbox/<录制目录>
```

原始录制不会被 pytest 收集，也不应直接复制进测试目录。它只用于确认真实动作和候选定位器；
稳定修改应进入 `python_playwright/pages/`，业务断言仍保留在
`python_playwright/tests/`。PC/H5 受影响用例通过后，再运行：

```bash
.venv/bin/python run_all.py --platform all
```

详细的操作、评审清单、脱敏规则和接受录制的提交标准见
[录制回归方案](docs/JuJuBit-录制回归方案.md) 与 [录制资产说明](recorded/README.md)。

## GitHub Actions 定时运行

项目包含两个 GitHub Actions 工作流，均会在每次运行后上传 HTML、截图、失败录像和 `results.xml`：

| 工作流 | 自动执行 | 手动入口 | 用途 |
| --- | --- | --- | --- |
| `JuJuBit 首页 UI Tests` | 每天北京时间 09:00 | **Actions → JuJuBit 首页 UI Tests → Run workflow** | 只执行首页 PC/H5 用例，不读取购物车登录态。 |
| `JuJuBit 购物车 UI Tests` | 周一至周六北京时间 10:00 执行 `daily`；周日北京时间 11:00 执行 `full` | **Actions → JuJuBit 购物车 UI Tests → Run workflow** | `daily` 为 PC 全量 15 条 + H5 关键 6 条，共 21 条；周日 `full` 为 PC/H5 各 15 条，共 30 条；手动可选择 `smoke`、`daily` 或 `full`。 |

两个工作流会共享同一个并发队列，不会同时从 GitHub Runner 访问站点。首页每天北京时间 09:00
开始，购物车周一至周六每日分层回归北京时间 10:00 开始，周日完整回归北京时间 11:00 开始；如果首页尚未结束，购物车会自动排队，随后再运行。
两条工作流会分别发送“首页”和“购物车”的飞书结果卡片与独立 Artifact，这是为了让失败录像和模块统计更清晰。

### 第一次推送到 GitHub

当前目录已经初始化为 Git 仓库，并在 `main` 分支创建了本地初始提交；目前只差远程
GitHub 仓库。先在 GitHub 创建一个仓库（建议使用 Private），再在本机执行：

```bash
cd /Users/wyz/pro/jujubit-web-automation
git remote add origin https://github.com/<你的账号>/<仓库名>.git
git push -u origin main
```

`.gitignore` 已排除 `.venv/`、`.pytest_cache/`、`artifacts/`、截图和录像，不会把本地
运行产物、飞书授权二维码或密钥提交到仓库。

### 配置飞书群通知

在飞书目标群添加“自定义机器人”，复制机器人 Webhook。然后进入 GitHub 仓库的
**Settings → Secrets and variables → Actions → New repository secret**，添加：

| Secret 名称 | 内容 |
| --- | --- |
| `LARK_WEBHOOK_URL` | 飞书机器人的完整 Webhook 地址（必填） |
| `LARK_WEBHOOK_SECRET` | 机器人开启签名校验时填写的 Secret；未开启可不填 |

Webhook 只从 GitHub Secrets 读取，不会写入代码。通知卡片会以互斥口径显示执行通过率、业务失败、
因 HTTP 429 未完成、其他跳过、耗时、分支、执行人、提交、开始时间和模块结果，并提供 **查看运行与报告**
和 **下载 HTML 报告与录屏** 两个按钮。测试文件名或类名包含 `cart` / `shopping_cart` 的用例
会自动归入“购物车”，首页用例仍归入“首页”。Artifact 名称包含本次运行的时间戳，例如
`jujubit-ui-report-20260806-150512`，可用于区分每天的结果。

下载按钮指向 GitHub Artifact，通常会下载 ZIP；解压后打开其中带时间戳的 HTML 文件，
报告里的失败视频相对链接仍然有效。该链接要求访问者登录 GitHub 且拥有仓库权限。若要
让未登录的群成员直接打开网页，需要另行部署带访问控制的对象存储或报告站点，不建议把
包含页面截图/录像的报告直接公开。

### 配置购物车登录状态

购物车主流程需要登录态。先在本地可见浏览器中登录 JuJuBit，浏览器关闭后 Playwright
会把当前登录态写入项目的 `artifacts/auth/storage-state.json`：

```bash
mkdir -p artifacts/auth
.venv/bin/playwright codegen \
  --save-storage=artifacts/auth/storage-state.json \
  https://jujubit.ai/account/login
```

然后把文件内容保存为 GitHub Actions Secret。若本机已经登录 GitHub CLI，可直接执行：

```bash
gh secret set PLAYWRIGHT_STORAGE_STATE_JSON < artifacts/auth/storage-state.json
```

也可以进入仓库的 **Settings → Secrets and variables → Actions → New repository secret**，
名称填写 `PLAYWRIGHT_STORAGE_STATE_JSON`，内容粘贴完整 JSON。只有购物车工作流会在临时 Runner
中还原为 `artifacts/auth/storage-state.json`，并按选择执行 Smoke、每日分层或完整购物车回归；该文件包含
登录 Cookie，已被 `.gitignore` 排除，不能直接提交到 Git 仓库。登录态失效后重复上述步骤更新 Secret。

### 海外访问与 HTTP 429

GitHub 托管 Runner 的出口地区和 IP 不保证固定，Shopify/WAF 可能返回 429 或人机验证。
为降低购物车登录流量，项目会把每日首页任务与每日购物车分层回归分开、串行排队执行；
手动 Smoke 只跑 PC，每日和完整购物车 API 还会以 6 秒最小间隔访问，首次持续 429 后剩余购物车记录会直接标记
为“429 未完成”，不会继续反复登录和撞站点。429 不计为页面功能失败，但表示该轮无法完成验收。

工作流不会自动绕过 CAPTCHA；无人值守的 GitHub Job 也无法等待人工点击确认。若购物车工作流
仍持续被拦截，可靠的长期方案是使用固定海外出口 IP 的 self-hosted Runner，并在站点/WAF 为该
测试账号和出口 IP 配置受控白名单。这样得到的海外加载和访问结果也更稳定、可复现。

### 本地检查通知配置

未配置 `LARK_WEBHOOK_URL` 时通知脚本会安全跳过，因此本地可以先只验证报告解析：

```bash
RESULTS_XML=artifacts/runs/<时间戳>/results.xml \
  .venv/bin/python scripts/send_lark_test_report.py
```

真正配置 Secret 后，在 GitHub Actions 页面手动运行一次，确认飞书卡片和 Artifact 链接都能
打开，再等待每日定时任务。

## 用例如何被读取

`run_all.py` 负责执行 `pytest`，并不逐条维护 case 列表。pytest 根据
`pytest-playwright.ini` 自动扫描 `python_playwright/tests/` 内所有名为
`test_*.py` 的文件，再执行其中所有 `test_...` 函数。

用例函数只要声明 `test_platform` 参数，`python_playwright/tests/conftest.py`
内的 `pytest_generate_tests` 会自动生成 PC 和 H5 两条执行记录。因此新增 case
通常只需：在对应模块的 `test_*.py` 中新增 `test_...` 函数，并在同文件夹的
`conftest.py` 的 `CASE_TITLES` 添加中文名称；不需要修改 `run_all.py`。

### 购物车主流程

`python_playwright/tests/test_cart.py` 包含 15 个独立逻辑函数；每个函数按 PC/H5 参数化，
完整执行会在报告中生成 30 条购物车记录。用例覆盖 Create、Gallery 的 2D/3D 结果、半屏与
全屏购物车、Checkout、角标、数量与金额联动、包邮临界值、空态、视图一致性和失败请求保护。

GitHub 周一至周六定时任务使用 `daily` 分层：PC 保留 15 条完整覆盖，H5 保留 CART-01、02、03、06、10、15
六条关键主链路，共 21 条。H5 的其余 9 条深度兼容性用例不会被删除，周日由 `full` 自动覆盖，也可在发布前
或页面改动后手动选择 `full` 执行。HTML 报告顶部会明确显示本次套件和收集数量，避免把未运行的深度用例
误看成失败或跳过。

本地可直接运行：

```bash
# 每日分层（21 条）
.venv/bin/python run_all.py --cart-suite daily

# 完整购物车回归（30 条）
.venv/bin/python run_all.py --cart-suite full
```

只有 `CART-02` 会真实上传图片并发起生成；其余购物车用例独立清空购物车后复用账号 Gallery
中已有的成功资产，不依赖前序用例遗留状态。默认测试图片来自 JuJuBit CDN，也可以通过
`--pw-cart-image` 传入本地图片或其他图片 URL；生成等待上限通过
`--pw-generation-timeout`（秒）调整。

购物车用例使用 `cart_session` 标记；只有 `--pw-storage-state` 指向存在的
`artifacts/auth/storage-state.json` 时才加载登录态，不会影响首页用例。首次登录需要验证码时，
请在本地可见浏览器中完成登录后导出该 state 文件，文件已被 `.gitignore` 排除。

15 条用例的 ID、真实函数名、步骤、预期结果及线上最终文案见
`docs/JuJuBit-购物车-自动化测试用例.md`。该文档由 `python_playwright/cart_cases.py`
确定性生成；修改结构化清单后执行以下命令同步：

```bash
.venv/bin/python scripts/sync_cart_case_docs.py
```

`tests/test_cart_case_sync.py` 会离线比对结构化清单、真实测试函数、HTML 报告标题映射和
已提交的 Markdown，防止文档与脚本遗漏或漂移。
