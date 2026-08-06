"""pytest 全局命令行参数。

测试用例本身放在 ``python_playwright/tests``，这里集中定义运行模式，
避免每个测试文件重复解析参数。
"""


def pytest_addoption(parser):
    """注册平台、报告、录像和 429 人工确认相关参数。"""
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
        help="首页收到 HTTP 429 后的自动等待重试次数。",
    )
    parser.addoption(
        "--pw-link-request-interval",
        type=float,
        default=0.8,
        help="批量检查首页站内链接时的最小请求间隔（秒）。",
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
