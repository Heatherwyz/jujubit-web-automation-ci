#!/usr/bin/env python3
"""从购物车结构化用例清单生成对应 Markdown 文档。"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python_playwright.cart_cases import CART_CASES, CartAutomationCase


DOCUMENT_PATH = ROOT / "docs" / "JuJuBit-购物车-自动化测试用例.md"


def _table_cell(value: str) -> str:
    """转义 Markdown 表格中的保留字符并压平意外换行。"""
    return "<br>".join(part.strip() for part in value.splitlines()).replace("|", "\\|")


def render_cart_case_document(
    cases: Iterable[CartAutomationCase] = CART_CASES,
) -> str:
    """确定性渲染购物车自动化用例文档。"""
    case_list = tuple(cases)
    rows = [
        "| ID | 用例名称 | 真实函数名 | 优先级 | 前置条件 | 操作步骤 | 预期结果 |",
        "|---|---|---|---|---|---|---|",
    ]
    for case in case_list:
        rows.append(
            "| "
            + " | ".join(
                _table_cell(value)
                for value in (
                    case.case_id,
                    case.title,
                    f"`{case.test_function}`",
                    case.priority,
                    case.precondition,
                    case.steps,
                    case.expected,
                )
            )
            + " |"
        )

    lines = [
        "# JuJuBit 购物车自动化测试用例",
        "",
        "> 本文档由 `python_playwright/cart_cases.py` 自动生成，请勿直接修改。",
        "> 修改结构化用例后运行 `.venv/bin/python scripts/sync_cart_case_docs.py` 同步。",
        "",
        "## 1. 范围与执行口径",
        "",
        f"- 共 `{len(case_list)}` 个逻辑 pytest 函数；每个函数按 PC/H5 参数化，完整执行生成 `{len(case_list) * 2}` 条独立报告记录。",
        "- 所有购物车用例遇到首页优惠弹窗都会先关闭，再继续操作。",
        "- `CART-02` 是唯一发起真实上传和生成任务的逻辑用例；PC/H5 各执行一次时会分别产生一次生成任务。",
        "- `CART-03` 至 `CART-15` 独立清空购物车后复用账号 Gallery 中已有的成功资产，不依赖上一条用例遗留的购物车状态；无可复用资产时明确跳过。",
        "- 涉及 Checkout 的用例只验证进入结算页及订单摘要，不提交订单、不点击支付。",
        "- AB 实验和失效商品不在本轮范围内；角标 `99+` 使用同一 SKU 数量 100 验证。",
        "",
        "## 2. 主流程",
        "",
        "1. 从 `jujubit.ai` 首页点击 Header 左上角 Create，进入创作页。",
        "2. 上传图片并生成，确认本次 Gallery 结果同时具备真实加载的 2D 图片与就绪的 3D renderer。",
        "3. 从 Gallery 加购生成模型，确认保持在创作页并打开半屏购物车。",
        "4. 从半屏购物车直接进入 Checkout，验证当前商品摘要。",
        "5. 返回 Gallery，经 Header 右上角 Cart 进入全屏购物车。",
        "6. 从全屏购物车进入 Checkout，验证当前商品摘要。",
        "",
        "其余用例在该主流程基础上独立覆盖角标、内容完整性、包邮临界值、数量联动、空态、数量上限、视图一致性和失败请求保护。",
        "",
        "## 3. 自动化用例",
        "",
        *rows,
        "",
        "## 4. 线上最终文案",
        "",
        "以下文案保留线上组件实际大小写、标点和占位格式，自动化断言以此为准。",
        "",
        "| 场景 | 最终文案 |",
        "|---|---|",
        "| 购物车标题 | `Cart` |",
        "| 空购物车 | `Your Cart is Empty` |",
        "| 小计标签 | `Subtotal` |",
        "| 总优惠标签 | `You Save` |",
        "| 单商品优惠 | `Save $XX.XX` |",
        "| 未达到包邮门槛 | `Add $XX.XX more to enjoy Free Shipping` |",
        "| 已达到包邮门槛 | `You've qualified for free standard shipping` |",
        "| Checkout 按钮 | `Checkout (N)` |",
        "| 100 件及以上角标 | `99+` |",
        "",
        "其中当前包邮门槛为 `$99.00`：空车提示 `Add $99.00 more to enjoy Free Shipping`；`$98.99` 提示还差 `$0.01`；`$99.00` 及以上显示已获包邮文案。",
        "",
        "## 5. 执行与同步",
        "",
        "完整执行首页和购物车 PC/H5 用例：",
        "",
        "```bash",
        ".venv/bin/python run_all.py --include-cart",
        "```",
        "",
        "只收集购物车用例并确认应为 30 条：",
        "",
        "```bash",
        ".venv/bin/python -m pytest -c pytest-playwright.ini --collect-only -q python_playwright/tests/test_cart.py",
        "```",
        "",
        "修改 `python_playwright/cart_cases.py` 后同步本文档：",
        "",
        "```bash",
        ".venv/bin/python scripts/sync_cart_case_docs.py",
        "```",
        "",
        "离线同步测试会精确比对 `CART_CASES`、`test_cart.py` 的真实函数、报告 `CASE_TITLES` 和本 Markdown；任一侧遗漏或名称漂移都会失败。",
        "",
    ]
    return "\n".join(lines)


def sync_cart_case_document(path: Path = DOCUMENT_PATH) -> Path:
    """把当前结构化清单写入指定文档路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cart_case_document(), encoding="utf-8")
    return path


def main() -> int:
    path = sync_cart_case_document()
    print(f"已同步 {len(CART_CASES)} 条购物车自动化用例：{path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
