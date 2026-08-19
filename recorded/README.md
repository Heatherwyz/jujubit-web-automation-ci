# 真实录制资产

本目录保存 Playwright Codegen 的真实操作录制，用于发现页面变更、复核定位器和辅助微调现有 Page Object。

录制不是第二套测试框架，也不是直接替换 `python_playwright/tests/` 的脚本。稳定动作最终仍需回填到：

- `python_playwright/pages/`：页面对象和定位器；
- `python_playwright/tests/`：业务断言和 PC/H5 参数化；
- 现有 `run_all.py` / pytest HTML、JUnit、截图和录像报告链路。

## 目录约定

```text
recorded/
├── inbox/       # 本地临时录制，默认被 Git 忽略
└── accepted/    # 已脱敏、已评审、值得保留的录制，可提交版本库
```

每份已接受的录制建议包含：

```text
accepted/<流程名>/<版本或日期>/
├── flow.py          # Codegen 原始脚本，作为变更证据和定位参考
└── recording.json   # URL、端、目标和录制状态，不包含 Cookie 内容
```

`storage-state.json`、HAR、截图和录像不应放进 `accepted/`。它们可能包含 Cookie、请求头、账号或其他敏感数据，应放在 `artifacts/` 或本机安全目录。

## 首页发生变化时的微调流程

### 1. 启动真实录制

PC：

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name homepage-change \
  --url https://jujubit.ai/ \
  --platform pc
```

H5：

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name homepage-change \
  --url https://jujubit.ai/ \
  --platform h5
```

脚本会打开真实的 Codegen 浏览器。按真实用户路径操作，遇到优惠弹窗就按用户实际行为关闭；确认页面变化后关闭 Codegen 窗口，录制会写入 `recorded/inbox/<时间>-<名称>-<端>/`。

需要登录的流程显式传入状态文件，例如：

```bash
.venv/bin/python scripts/record_ui_flow.py \
  --name cart-change \
  --url https://jujubit.ai/ \
  --platform pc \
  --load-storage artifacts/auth/storage-state.json
```

不要把登录态、验证码或支付数据写进录制脚本，也不要把状态文件提交到 Git。

### 2. 静态检查和人工评审

```bash
.venv/bin/python scripts/validate_recording.py recorded/inbox/<录制目录>
```

检查重点：

- 录制是否从正确 URL 开始，是否包含完整的真实路径；
- Codegen 生成的 `get_by_role`、`get_by_label`、`get_by_test_id` 是否仍指向正确元素；
- 是否出现 XPath、`nth()`、`first()`、固定长等待；
- 是否含有邮箱、密码、验证码、Cookie、Authorization 或其他敏感值；
- 变化是定位器/文案变化，还是产品行为、接口或数据发生变化。

录制中的断言和等待是候选内容，不能未经评审直接当作最终业务断言。

### 3. 回填现有 Page Object

把录制中确认变化的最小部分修改到 `python_playwright/pages/home_page.py`。例如首页 Create 入口的 DOM 结构变化，只更新 `HomePage` 的定位器和等待逻辑；不要把整个 Codegen 文件复制成独立测试。

保留 `python_playwright/tests/test_home.py` 中的业务断言。这样脚本仍然覆盖 URL、组件挂载、导航内容和无障碍语义，而不是只证明“鼠标点击成功”。

### 4. 运行受影响回归

先按端运行受影响的首页用例：

```bash
.venv/bin/python -m pytest -c pytest-playwright.ini \
  --pw-platform pc \
  python_playwright/tests/test_home.py \
  -k 'test_tc01 or test_tc07 or test_tc15'
```

H5 将 `pc` 改成 `h5`。确认最小回归通过后，再执行首页完整回归：

```bash
.venv/bin/python run_all.py --platform all
```

报告、失败截图和失败录像仍由现有 `artifacts/runs/<时间戳>/` 链路生成。

### 5. 接受录制并提交

只有在脱敏、评审和受影响回归完成后，才把临时目录移入 `recorded/accepted/`：

```bash
mkdir -p recorded/accepted/homepage
mv recorded/inbox/<录制目录> recorded/accepted/homepage/<日期>-<变更名>
.venv/bin/python scripts/validate_recording.py recorded/accepted/homepage/<日期>-<变更名> --strict
```

提交时同时包含 Page Object、测试断言、录制证据和必要的文档更新，方便以后复盘“为什么改这个定位器”。

## 定位器决策顺序

1. 唯一且符合业务语义的 `data-testid`；
2. `get_by_role` + 可见名称；
3. `get_by_label`、唯一链接 URL 或稳定业务属性；
4. 仅在没有更好选择时使用局部 CSS；
5. 避免 XPath、层级长链、`nth()` 和依赖视觉顺序的定位。

录制只反映某一次页面状态。最终 Page Object 需要补充加载、空态、弹窗、PC/H5 差异和失败请求等断言，不能把 Codegen 生成的偶然选择当成稳定契约。

## 录制与回归的边界

```text
真实录制
    → 发现动作/定位变化
    → 静态检查 + 人工评审
    → 最小修改 Page Object
    → 现有 pytest 用例回归
    → HTML/JUnit/截图/录像留证
    → 接受录制并提交
```

CI 默认不直接执行 `recorded/` 下的原始脚本，避免绕过项目已有的登录态隔离、请求限速、弹窗处理和报告口径。录制资产的作用是让首页变化时能用真实操作快速定位差异，同时保持最终回归结果可比、可审计。
