"""pytest 全局命令行参数。

测试用例本身放在 ``python_playwright/tests``，这里集中定义运行模式，
避免每个测试文件重复解析参数。
"""


def pytest_addoption(parser):
    """注册平台、报告、录像、购物车和人工确认相关参数。"""
    parser.addoption("--pw-platform", choices=("all", "pc", "h5"), default="all")
    parser.addoption("--headed", action="store_true", default=False)
    parser.addoption("--base-url", default="https://jujubit.ai")
    parser.addoption("--pw-record-video", action="store_true", default=False)
    parser.addoption(
        "--pw-manual-verification",
        action="store_true",
        default=False,
        help="遇到 429 或人机验证时暂停，等待用户在有界面浏览器中手动确认。",
    )
    parser.addoption(
        "--pw-request-interval",
        type=float,
        default=6.0,
        help="两次首页导航的最小间隔（秒），用于降低触发站点频控的概率。",
    )
    parser.addoption(
        "--pw-429-retries",
        type=int,
        default=2,
        help="首页及可安全重复请求收到 HTTP 429 后的自动等待重试次数。",
    )
    parser.addoption(
        "--pw-link-request-interval",
        type=float,
        default=4.0,
        help="批量检查首页站内链接时的最小请求间隔（秒）；与首页导航共用限速器。",
    )
    parser.addoption(
        "--pw-cart-request-interval",
        type=float,
        default=2.0,
        help="购物车 API 与关键 UI 操作的最小间隔（秒），用于降低登录态频控。",
    )
    parser.addoption(
        "--pw-cart-image",
        default="https://jujubit.ai/cdn/shop/files/pod_1800x1800.png?v=1770294841",
        help="购物车主流程使用的 PNG/JPG/WebP 本地路径或 URL。",
    )
    parser.addoption(
        "--pw-generation-timeout",
        type=int,
        default=600,
        help="等待 2D 图片和 3D 模型生成完成的最长秒数。",
    )
    parser.addoption(
        "--pw-storage-state",
        default="artifacts/auth/storage-state.json",
        help="Playwright 登录状态文件路径；测试 fixture 会在文件存在时复用。",
    )
    parser.addoption(
        "--pw-artifact-dir",
        default="",
        help="保存本次报告、截图和失败视频的目录；run_all.py 会自动传入时间戳目录。",
    )
    parser.addoption(
        "--pw-report-name",
        default="report.html",
        help="HTML 报告文件名；run_all.py 会自动传入带时间戳的文件名。",
    )
