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

购物车端到端用例会真实上传图片、创建一次生成任务并修改购物车，因此默认不执行。
确认测试环境和账号配额可用后，显式执行首页与购物车全部用例：

```bash
.venv/bin/python run_all.py --include-cart
```

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
- `run_all.py`：一键运行和按时间戳归档入口。
- `artifacts/runs/`：历史报告及关联失败视频。

## GitHub Actions 每日运行

项目已经包含 `.github/workflows/daily-ui-tests.yml`，可以在 GitHub 上安装
Playwright Chromium，执行自动收集的全部 PC/H5 用例，并在每次运行后上传 HTML、截图、
失败录像和 `results.xml`。工作流默认每天北京时间 09:00（UTC 01:00）执行，也可以在
仓库的 **Actions → JuJuBit UI Tests → Run workflow** 手动触发。

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

Webhook 只从 GitHub Secrets 读取，不会写入代码。通知卡片会显示状态、通过率、业务失败、
跳过、429 频控、耗时、分支、执行人、提交、开始时间和模块结果，并提供 **查看运行与报告**
和 **下载 HTML 报告与录屏** 两个按钮。测试文件名或类名包含 `cart` / `shopping_cart` 的用例
会自动归入“购物车”，首页用例仍归入“首页”。Artifact 名称包含本次运行的时间戳，例如
`jujubit-ui-report-20260806-150512`，可用于区分每天的结果。

下载按钮指向 GitHub Artifact，通常会下载 ZIP；解压后打开其中带时间戳的 HTML 文件，
报告里的失败视频相对链接仍然有效。该链接要求访问者登录 GitHub 且拥有仓库权限。若要
让未登录的群成员直接打开网页，需要另行部署带访问控制的对象存储或报告站点，不建议把
包含页面截图/录像的报告直接公开。

### 海外访问与 HTTP 429

GitHub 托管 Runner 的出口地区和 IP 不保证固定，Shopify/WAF 可能返回 429 或人机验证。
工作流会按现有规则限速和重试，但不会自动绕过 CAPTCHA；无人值守的 GitHub Job 也无法
等待人工点击确认。若定时任务持续被拦截，建议使用固定海外出口 IP 的 self-hosted
Runner，并在站点/WAF 中为该测试流量配置受控白名单。这样得到的海外加载和访问结果也更
稳定、可复现。

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

`python_playwright/tests/test_cart.py` 只生成一次模型，并在同一条主流程中验证 Gallery
的 2D/3D 结果、半屏购物车、100 件数量上限对应的 `99+` 角标、半屏 Checkout、全屏购物车
和全屏 Checkout。默认测试图片来自 JuJuBit CDN，也可以通过 `--pw-cart-image` 传入本地图片
或其他图片 URL；生成等待上限通过 `--pw-generation-timeout`（秒）调整。

购物车用例使用 `cart_session` 标记；只有 `--pw-storage-state` 指向存在的
`artifacts/auth/storage-state.json` 时才加载登录态，不会影响首页用例。首次登录需要验证码时，
请在本地可见浏览器中完成登录后导出该 state 文件，文件已被 `.gitignore` 排除。
