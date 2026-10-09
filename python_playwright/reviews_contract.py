"""静态评论页契约：只检查服务端 HTML，不启动浏览器。"""

from __future__ import annotations

import re
from html import unescape

REVIEWS_PATH = "/pages/reviews"
EXPECTED_REVIEW_TITLE = "Is JuJuBit Legit? Real Customer Reviews & Ratings"


def reviews_contract_problems(html: str) -> list[str]:
    """返回静态评论页不符合契约的问题；空列表表示通过。"""
    problems: list[str] = []
    title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    if title != EXPECTED_REVIEW_TITLE:
        problems.append(f"标题应为 {EXPECTED_REVIEW_TITLE!r}，实际 {title!r}")
    visible = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    visible = unescape(re.sub(r"<[^>]+>", " ", visible))
    visible = re.sub(r"\s+", " ", visible)
    if re.search(r"page not found|404|internal server error", visible, re.I):
        problems.append("评论页返回了错误页内容")
    if len(re.findall(r"\breview\b", visible, re.I)) < 3:
        problems.append("评论页可见内容中的 review 不足 3 处")
    if not re.search(r"\b[1-5](?:\.0)?\s*/\s*5\b|\bstar", visible, re.I):
        problems.append("评论页没有评分或星级内容")
    return problems
