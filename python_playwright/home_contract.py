"""首页服务端 HTML 契约：期望值与纯解析断言，不依赖 Playwright 或浏览器。

这一层只回答“不执行 JavaScript 的原始 HTML 是否包含约定内容”。它没有浏览器、
没有登录态、没有视口差异，因此同一份 HTML 的结论是确定的：一红就是站点或主题
真的改坏了，不存在渲染时序或频控造成的噪声。

需要真实点击、可见性、遮挡判断和交互的验收留在 Playwright 层（见
``python_playwright/tests/test_home_requirements.py``）。把两层分开的原因是它们
的失败含义不同——本层失败必须立刻查，浏览器层失败还要先排除环境因素。

模块内所有函数都接受 HTML 字符串并返回问题列表（空列表表示通过），因此可以被
离线单测直接覆盖，无需起浏览器或访问站点。
"""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

EXPECTED_TITLE = "JuJuBit | Custom Figurines, Crystal Bracelets & Art Toys"
EXPECTED_DESCRIPTION = (
    "JuJuBit makes custom figurines from your photo, crystal bracelets, and art toys. "
    "AI-assisted design, worldwide shipping. Turn your photo into a 3D collectible."
)
EXPECTED_H1 = "Create Your Own Custom Figurine From a Photo"
# 线上 Logo 是 inline SVG（无 img 子元素），无障碍名称由锚点的 aria-label 提供。
# 历史常量写的是一个全站出现 0 次的 alt 字符串，浏览器层因为走了
# "无 img 就检查 aria-label" 的分支，那条 alt 断言从未真正执行过。
EXPECTED_LOGO_ACCESSIBLE_NAME = "JuJuBit"
EXPECTED_NAVIGATION_LINKS = {
    "Templates": "/collections/templates-create-your-own",
    "How It Works": "/pages/how-it-works",
}
EXPECTED_HEADER_CATEGORY_LINKS = {
    # 线上主题已将该品类的导航展示文案更新为 FIGURINES；业务集合地址
    # 仍然是 art-toy。按当前可见文案验收，避免把旧名称误报为缺少链接。
    "FIGURINES": "/collections/art-toy",
    "FDM LAMPS": "/collections/fdm",
    "Crystal Bracelets": "/collections/crystal-bracelets",
    "Keycaps": "/collections/keycaps",
    "Photo Boards": "/collections/photo-board",
}
# 核心版块文案由主题配置，取稳定标识而非营销长句，避免文案微调即报红。
EXPECTED_SECTION_MARKERS = ("Pick Your Style", "How It Works")


def normalize_text(value: str) -> str:
    """折叠空白并解码实体，供文本包含类断言使用。"""
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _strip_tags(value: str) -> str:
    return normalize_text(re.sub(r"<[^>]+>", " ", value))


class AnchorCollector(HTMLParser):
    """从服务端 HTML 中提取真实锚点，避免把脚本字符串误当成导航链接。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._active_anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self._active_anchor is not None:
            return
        attributes = dict(attrs)
        self._active_anchor = {"href": attributes.get("href", ""), "text": []}

    def handle_data(self, data):
        if self._active_anchor is not None:
            self._active_anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or self._active_anchor is None:
            return
        self.anchors.append(
            {
                "href": self._active_anchor["href"],
                "text": normalize_text(" ".join(self._active_anchor["text"])),
            }
        )
        self._active_anchor = None


class FaqContentCollector(HTMLParser):
    """只收集 SSR FAQ section 内结构完整且有正文的问答。"""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_section = False
        self.items: list[dict[str, str]] = []
        self._stack: list[str] = []
        self._section_depth = 0
        self._current_item: dict | None = None
        self._item_depth: int | None = None
        self._summary_depth: int | None = None
        self._question_depth: int | None = None
        self._answer_depth: int | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = dict(attrs)
        if self._section_depth == 0:
            if tag != "section" or "data-jjb-faq" not in attributes:
                return
            self.has_section = True
            self._section_depth = 1
            self._stack = [tag]
            return

        if tag == "section":
            self._section_depth += 1
        if tag not in self._VOID_TAGS:
            self._stack.append(tag)
        depth = len(self._stack)
        classes = set((attributes.get("class") or "").split())

        if (
            tag == "details"
            and self._current_item is None
            and ("data-faq-item" in attributes or "jjb-faq__item" in classes)
        ):
            self._current_item = {"question": [], "answer": []}
            self._item_depth = depth
        if self._current_item is None:
            return
        if tag == "summary":
            self._summary_depth = depth
        elif tag == "h3" and self._summary_depth is not None:
            self._question_depth = depth
        if "data-faq-answer" in attributes or "jjb-faq__answer" in classes:
            self._answer_depth = depth

    def handle_data(self, data):
        if self._current_item is None:
            return
        if self._question_depth is not None:
            self._current_item["question"].append(data)
        if self._answer_depth is not None:
            self._current_item["answer"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._section_depth == 0 or not self._stack:
            return
        try:
            depth = len(self._stack) - self._stack[::-1].index(tag)
        except ValueError:
            return
        if self._question_depth == depth and tag == "h3":
            self._question_depth = None
        if self._answer_depth == depth:
            self._answer_depth = None
        if self._summary_depth == depth and tag == "summary":
            self._summary_depth = None
        if self._item_depth == depth and tag == "details":
            self.items.append(
                {
                    key: normalize_text(" ".join(parts))
                    for key, parts in self._current_item.items()
                }
            )
            self._current_item = None
            self._item_depth = None
            self._summary_depth = None
            self._question_depth = None
            self._answer_depth = None

        if tag == "section":
            self._section_depth -= 1
        # Shopify 输出通常是合法嵌套；若第三方富文本产生不完整标签，则从
        # 当前闭合标签处一起退栈，避免后续问答被错误吞进前一项。
        del self._stack[depth - 1 :]
        if self._section_depth == 0:
            self._stack = []


def head_titles(html: str) -> list[str]:
    """返回 head 内的 title 文本列表；用于验收唯一且精确。"""
    head_match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.I | re.S)
    if not head_match:
        return []
    return [
        _strip_tags(value)
        for value in re.findall(
            r"<title\b[^>]*>(.*?)</title>", head_match.group(1), re.I | re.S
        )
    ]


def h1_texts(html: str) -> list[str]:
    return [
        _strip_tags(value)
        for value in re.findall(r"<h1\b[^>]*>(.*?)</h1>", html, re.I | re.S)
    ]


def check_seo_metadata(html: str) -> list[str]:
    """title 唯一精确、meta description 精确存在。"""
    problems: list[str] = []
    if not re.search(r"<head\b[^>]*>(.*?)</head>", html, re.I | re.S):
        return ["服务端 HTML 缺少 head"]
    titles = head_titles(html)
    if titles != [EXPECTED_TITLE]:
        problems.append(f"title 应唯一且精确匹配 {EXPECTED_TITLE!r}，实际为 {titles!r}")
    if EXPECTED_DESCRIPTION not in normalize_text(html):
        problems.append("缺少精确 meta description")
    return problems


def check_h1(html: str) -> list[str]:
    texts = h1_texts(html)
    if texts != [EXPECTED_H1]:
        return [f"H1 应唯一且精确匹配 {EXPECTED_H1!r}，实际为 {texts!r}"]
    return []


def check_navigation_anchors(html: str) -> list[str]:
    """导航必须是带 href 的真实锚点，而不是脚本驱动的伪链接。"""
    collector = AnchorCollector()
    collector.feed(html)
    problems: list[str] = []
    for label, path in EXPECTED_NAVIGATION_LINKS.items():
        matches = [
            anchor
            for anchor in collector.anchors
            if anchor["text"].casefold() == label.casefold()
            and urlparse(anchor["href"]).path.rstrip("/") == path.rstrip("/")
        ]
        if not matches:
            problems.append(f"缺少真实导航锚点 {label} -> {path}")
    return problems


def check_category_anchors(html: str) -> list[str]:
    """品类入口地址必须与需求一致，文案改动不影响目标集合。"""
    collector = AnchorCollector()
    collector.feed(html)
    problems: list[str] = []
    for label, path in EXPECTED_HEADER_CATEGORY_LINKS.items():
        matches = [
            anchor
            for anchor in collector.anchors
            if anchor["text"].casefold() == label.casefold()
            and urlparse(anchor["href"]).path.rstrip("/") == path.rstrip("/")
        ]
        if not matches:
            problems.append(f"缺少品类锚点 {label} -> {path}")
    return problems


def heading_texts(html: str) -> list[str]:
    """返回 h1~h4 的纯文本，用于判断版块是否真的存在。"""
    return [
        _strip_tags(value)
        for value in re.findall(
            r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", html, re.I | re.S
        )
    ]


def check_core_sections(html: str) -> list[str]:
    """核心版块必须以标题形式存在。

    不能对整份 HTML 做子串匹配：导航里的 “How It Works” 链接会让整个版块被删掉
    也照样通过。这里只在标题元素内查找，保证命中的是版块而不是同名链接。
    """
    headings = [normalize_text(text) for text in heading_texts(html)]
    missing = [
        marker
        for marker in EXPECTED_SECTION_MARKERS
        if not any(marker in heading for heading in headings)
    ]
    if missing:
        return ["缺少核心 section 标题：" + "、".join(missing)]
    return []


def check_faq_ssr(html: str) -> list[str]:
    """FAQ 必须服务端渲染且问答成对，否则 SEO 与无脚本可读性不成立。"""
    collector = FaqContentCollector()
    collector.feed(html)
    if not collector.has_section:
        return ["缺少 FAQ section（data-jjb-faq）"]
    if not collector.items:
        return ["FAQ section 内没有 SSR 问答"]
    incomplete = [
        index
        for index, item in enumerate(collector.items, start=1)
        if not item["question"] or not item["answer"]
    ]
    if incomplete:
        return [
            "FAQ 问题或答案为空：第 " + "、".join(map(str, incomplete)) + " 项"
        ]
    return []


def check_logo_accessible_name(html: str) -> list[str]:
    """指向首页的品牌 Logo 必须有无障碍名称，供读屏器识别。

    Logo 可能是 inline SVG（当前线上实现）或 img。前者靠锚点 aria-label 提供
    名称，后者靠 img alt。两种都接受，但必须有其中之一——否则读屏器只会念出
    一个无意义的链接。属性可能用单引号或双引号，两种都要匹配。
    """
    anchors = re.findall(r"<a\b[^>]*>", html, re.I)
    home_logo_anchors = [
        tag
        for tag in anchors
        if re.search(r"""href\s*=\s*['"]/['"]""", tag, re.I)
        and re.search(r"logo", tag, re.I)
    ]
    if not home_logo_anchors:
        return ["未找到指向首页的 Logo 锚点"]
    for tag in home_logo_anchors:
        label = re.search(
            r"""aria-label\s*=\s*['"]([^'"]*)['"]""", tag, re.I
        )
        if label and normalize_text(label.group(1)) == EXPECTED_LOGO_ACCESSIBLE_NAME:
            return []
    # 没有 aria-label 时退回检查 img alt，兼容主题换回图片 Logo 的情况。
    for match in re.finditer(
        r"<a\b[^>]*href\s*=\s*['\"]/['\"][^>]*>(.*?)</a>", html, re.I | re.S
    ):
        for img in re.findall(r"<img\b[^>]*>", match.group(1), re.I):
            alt = re.search(r"""alt\s*=\s*['"]([^'"]*)['"]""", img, re.I)
            if alt and EXPECTED_LOGO_ACCESSIBLE_NAME in normalize_text(alt.group(1)):
                return []
    return [
        f"Logo 锚点缺少无障碍名称：aria-label 或 img alt 需包含 "
        f"{EXPECTED_LOGO_ACCESSIBLE_NAME!r}"
    ]


def _json_ld_blocks(html: str) -> list[str]:
    return re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )


def check_json_ld_faq_matches_ssr(html: str) -> list[str]:
    """FAQ 结构化数据必须可解析，且问题与 SSR 内容一致。"""
    blocks = _json_ld_blocks(html)
    if not blocks:
        return ["缺少 application/ld+json 结构化数据"]
    problems: list[str] = []
    faq_questions: list[str] = []
    for index, block in enumerate(blocks, start=1):
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError as error:
            problems.append(f"第 {index} 段 JSON-LD 无法解析：{error}")
            continue
        for node in payload if isinstance(payload, list) else [payload]:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "FAQPage":
                continue
            for entity in node.get("mainEntity") or []:
                if isinstance(entity, dict) and entity.get("name"):
                    faq_questions.append(normalize_text(str(entity["name"])))
    if problems:
        return problems
    if not faq_questions:
        # 首页未声明 FAQPage 时不强制要求；REQ-13 另有交互层验收。
        return []
    collector = FaqContentCollector()
    collector.feed(html)
    ssr_questions = {item["question"] for item in collector.items}
    missing = [name for name in faq_questions if name not in ssr_questions]
    if missing:
        problems.append(
            "JSON-LD 中的 FAQ 问题在 SSR 内容中不存在：" + "、".join(missing)
        )
    return problems


# 每项为 (契约名, 检查函数)。新增服务端 HTML 断言只需在此登记。
HOME_HTML_CONTRACTS = (
    ("SEO 元数据", check_seo_metadata),
    ("唯一 H1", check_h1),
    ("导航真实锚点", check_navigation_anchors),
    ("品类入口地址", check_category_anchors),
    ("核心版块文案", check_core_sections),
    ("FAQ 服务端渲染", check_faq_ssr),
    ("Logo 无障碍名称", check_logo_accessible_name),
    ("FAQ 结构化数据", check_json_ld_faq_matches_ssr),
)


def check_all(html: str) -> dict[str, list[str]]:
    """返回 {契约名: 问题列表}，只包含存在问题的契约。"""
    report: dict[str, list[str]] = {}
    for name, check in HOME_HTML_CONTRACTS:
        problems = check(html)
        if problems:
            report[name] = problems
    return report
