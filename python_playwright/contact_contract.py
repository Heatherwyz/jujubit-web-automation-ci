"""Contact 页面匿名用户标识契约。"""

from __future__ import annotations

import re
from html import unescape


CONTACT_PATH = "/pages/contact"
UID_INSTRUCTION = "Copy the following string and provide it to customer service"


def contact_uid_contract_problems(html: str) -> list[str]:
    """检查匿名用户标识提示和一段非空标识，不返回标识本身。"""
    problems: list[str] = []
    visible = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    visible = unescape(re.sub(r"<[^>]+>", " ", visible))
    visible = re.sub(r"\s+", " ", visible)
    if UID_INSTRUCTION not in visible:
        problems.append("Contact 页面缺少匿名用户标识复制提示")
    match = re.search(
        re.escape(UID_INSTRUCTION) + r"\s*:\s*(\S{8,})",
        visible,
    )
    if not match:
        problems.append("Contact 页面缺少可复制的匿名用户标识")
    return problems
