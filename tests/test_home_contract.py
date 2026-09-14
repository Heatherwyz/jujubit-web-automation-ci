"""首页服务端 HTML 契约的离线单测：不访问站点，不起浏览器。

这些用例喂固定 HTML 样本，锁定契约函数对“合规”和“坏掉”两类输入的判定。
契约层的价值在于确定性：同一份 HTML 永远得出同一结论，所以它必须有离线覆盖，
否则线上那一次请求的结果就无从校验。
"""

from __future__ import annotations

import unittest

from python_playwright.home_contract import (
    EXPECTED_DESCRIPTION,
    EXPECTED_H1,
    EXPECTED_TITLE,
    check_all,
    check_category_anchors,
    check_core_sections,
    check_faq_ssr,
    check_h1,
    check_json_ld_faq_matches_ssr,
    check_logo_accessible_name,
    check_navigation_anchors,
    check_seo_metadata,
    check_social_videos,
)

FAQ_SECTION = """
<section data-jjb-faq>
  <details data-faq-item>
    <summary><h3>How long does it take?</h3></summary>
    <div data-faq-answer>About five business days.</div>
  </details>
  <details data-faq-item>
    <summary><h3>Do you ship worldwide?</h3></summary>
    <div data-faq-answer>Yes, worldwide shipping is available.</div>
  </details>
</section>
"""

JSON_LD = """
<script type="application/ld+json">
{"@type":"FAQPage","mainEntity":[
  {"@type":"Question","name":"How long does it take?"},
  {"@type":"Question","name":"Do you ship worldwide?"}
]}
</script>
"""


def compliant_html(**overrides) -> str:
    """生成一份满足全部契约的首页 HTML，可按需替换局部片段。"""
    parts = {
        "title": f"<title>{EXPECTED_TITLE}</title>",
        "description": f'<meta name="description" content="{EXPECTED_DESCRIPTION}">',
        "h1": f"<h1>{EXPECTED_H1}</h1>",
        # 线上实现：inline SVG Logo，无障碍名称由锚点 aria-label 提供（单引号）。
        "logo": (
            "<a class='jjb-header__logo-link' href='/' aria-label='JuJuBit'>"
            "<span class='jjb-header__logo-text'><svg viewBox='0 0 125 31'>"
            "<path d='M12 18'/></svg></span></a>"
        ),
        "nav": (
            '<a href="/collections/templates-create-your-own">Templates</a>'
            '<a href="/pages/how-it-works">How It Works</a>'
        ),
        "categories": (
            '<a href="/collections/art-toy">FIGURINES</a>'
            '<a href="/collections/fdm">FDM LAMPS</a>'
            '<a href="/collections/crystal-bracelets">Crystal Bracelets</a>'
            '<a href="/collections/keycaps">Keycaps</a>'
            '<a href="/collections/photo-board">Photo Boards</a>'
        ),
        "sections": "<h2>Pick Your Style</h2><h2>How It Works</h2>",
        "faq": FAQ_SECTION,
        # 线上写法：布尔属性带值（playsinline="true" loop="loop" muted="muted"）。
        "videos": (
            '<video playsinline="true" loop="loop" muted="muted" '
            'class="jjb-social-media__video" preload="metadata"></video>'
        ),
        "json_ld": JSON_LD,
    }
    parts.update(overrides)
    return (
        "<!doctype html><html><head>"
        f"{parts['title']}{parts['description']}{parts['json_ld']}"
        "</head><body>"
        f"{parts['logo']}{parts['nav']}{parts['categories']}"
        f"{parts['h1']}{parts['sections']}{parts['faq']}{parts['videos']}"
        "</body></html>"
    )


class CompliantHtmlTests(unittest.TestCase):
    def test_fully_compliant_html_reports_no_problem(self) -> None:
        self.assertEqual(check_all(compliant_html()), {})


class SeoMetadataTests(unittest.TestCase):
    def test_missing_head_is_reported(self) -> None:
        problems = check_seo_metadata("<html><body><h1>x</h1></body></html>")

        self.assertEqual(problems, ["服务端 HTML 缺少 head"])

    def test_duplicate_title_is_rejected(self) -> None:
        """重复 title 会让搜索引擎取值不确定，必须报出来。"""
        html = compliant_html(
            title=f"<title>{EXPECTED_TITLE}</title><title>{EXPECTED_TITLE}</title>"
        )

        problems = check_seo_metadata(html)

        self.assertTrue(any("唯一" in item for item in problems))

    def test_changed_title_is_rejected(self) -> None:
        problems = check_seo_metadata(compliant_html(title="<title>别的标题</title>"))

        self.assertTrue(any("title" in item for item in problems))

    def test_missing_description_is_rejected(self) -> None:
        problems = check_seo_metadata(compliant_html(description=""))

        self.assertIn("缺少精确 meta description", problems)

    def test_title_with_nested_markup_is_normalized(self) -> None:
        """主题偶尔在 title 里插入标签或换行，折叠后仍应视为匹配。"""
        html = compliant_html(title=f"<title>\n  {EXPECTED_TITLE}\n</title>")

        self.assertEqual(check_seo_metadata(html), [])


class HeadingTests(unittest.TestCase):
    def test_single_expected_h1_passes(self) -> None:
        self.assertEqual(check_h1(compliant_html()), [])

    def test_multiple_h1_is_rejected(self) -> None:
        html = compliant_html(h1=f"<h1>{EXPECTED_H1}</h1><h1>另一个</h1>")

        self.assertTrue(check_h1(html))

    def test_missing_h1_is_rejected(self) -> None:
        self.assertTrue(check_h1(compliant_html(h1="")))


class AnchorTests(unittest.TestCase):
    def test_real_anchors_pass(self) -> None:
        self.assertEqual(check_navigation_anchors(compliant_html()), [])

    def test_script_driven_pseudo_link_is_rejected(self) -> None:
        """没有 href 的伪链接不满足“真实锚点”要求。"""
        html = compliant_html(
            nav='<span onclick="go()">Templates</span>'
            '<a href="/pages/how-it-works">How It Works</a>'
        )

        problems = check_navigation_anchors(html)

        self.assertTrue(any("Templates" in item for item in problems))

    def test_trailing_slash_difference_is_tolerated(self) -> None:
        html = compliant_html(
            nav='<a href="/collections/templates-create-your-own/">Templates</a>'
            '<a href="/pages/how-it-works/">How It Works</a>'
        )

        self.assertEqual(check_navigation_anchors(html), [])

    def test_wrong_destination_is_reported(self) -> None:
        html = compliant_html(
            nav='<a href="/collections/wrong">Templates</a>'
            '<a href="/pages/how-it-works">How It Works</a>'
        )

        self.assertTrue(check_navigation_anchors(html))

    def test_category_link_pointing_elsewhere_is_reported(self) -> None:
        html = compliant_html(
            categories='<a href="/collections/art-toy">FIGURINES</a>'
            '<a href="/collections/fdm">FDM LAMPS</a>'
            '<a href="/collections/crystal-bracelets">Crystal Bracelets</a>'
            '<a href="/collections/keycaps">Keycaps</a>'
            '<a href="/collections/moved">Photo Boards</a>'
        )

        problems = check_category_anchors(html)

        self.assertTrue(any("Photo Boards" in item for item in problems))


class SectionAndFaqTests(unittest.TestCase):
    def test_missing_section_marker_is_reported(self) -> None:
        problems = check_core_sections(
            compliant_html(sections="<h2>Pick Your Style</h2>")
        )

        self.assertTrue(any("How It Works" in item for item in problems))

    def test_ssr_faq_pairs_pass(self) -> None:
        self.assertEqual(check_faq_ssr(compliant_html()), [])

    def test_missing_faq_section_is_reported(self) -> None:
        self.assertEqual(
            check_faq_ssr(compliant_html(faq="")),
            ["缺少 FAQ section（data-jjb-faq）"],
        )

    def test_faq_section_without_items_is_reported(self) -> None:
        html = compliant_html(faq="<section data-jjb-faq></section>")

        self.assertEqual(check_faq_ssr(html), ["FAQ section 内没有 SSR 问答"])

    def test_faq_item_with_empty_answer_is_reported(self) -> None:
        """答案靠 JS 注入时 SSR 里是空的，SEO 与无脚本可读性不成立。"""
        html = compliant_html(
            faq="""
            <section data-jjb-faq>
              <details data-faq-item>
                <summary><h3>How long does it take?</h3></summary>
                <div data-faq-answer></div>
              </details>
            </section>
            """
        )

        problems = check_faq_ssr(html)

        self.assertTrue(any("为空" in item for item in problems))


class SocialVideoTests(unittest.TestCase):
    """浏览器层在没有 video 时会 pytest.skip；契约层必须把缺失判为失败。"""

    def test_compliant_videos_pass(self) -> None:
        self.assertEqual(check_social_videos(compliant_html()), [])

    def test_missing_video_section_is_reported(self) -> None:
        """版块整块被删时不能显示"跳过"，必须是失败。"""
        problems = check_social_videos(compliant_html(videos=""))

        self.assertEqual(len(problems), 1)
        self.assertIn("没有 video 元素", problems[0])

    def test_valueless_boolean_attributes_are_accepted(self) -> None:
        """HTML 布尔属性只要出现即生效，不要求带值。"""
        html = compliant_html(videos="<video muted playsinline loop></video>")

        self.assertEqual(check_social_videos(html), [])

    def test_missing_muted_is_reported(self) -> None:
        """自动播放的视频必须静音，否则移动端会被浏览器阻止播放。"""
        html = compliant_html(
            videos='<video playsinline="true" loop="loop"></video>'
        )

        problems = check_social_videos(html)

        self.assertTrue(any("muted" in item for item in problems))

    def test_missing_playsinline_and_loop_are_both_reported(self) -> None:
        html = compliant_html(videos='<video muted="muted"></video>')

        problems = check_social_videos(html)

        self.assertTrue(any("playsinline" in item for item in problems))
        self.assertTrue(any("loop" in item for item in problems))

    def test_each_offending_video_is_reported_separately(self) -> None:
        """一个视频有问题不能掩盖其他视频的同类问题。"""
        html = compliant_html(
            videos=(
                '<video muted playsinline loop></video>'
                "<video></video>"
                '<video muted playsinline></video>'
            )
        )

        problems = check_social_videos(html)

        self.assertEqual(len(problems), 2)
        self.assertIn("第 2 个", problems[0])
        self.assertIn("第 3 个", problems[1])


class LogoAndStructuredDataTests(unittest.TestCase):
    def test_inline_svg_logo_with_aria_label_passes(self) -> None:
        """线上实现是 inline SVG + 单引号 aria-label，必须视为合规。"""
        self.assertEqual(check_logo_accessible_name(compliant_html()), [])

    def test_double_quoted_aria_label_also_passes(self) -> None:
        html = compliant_html(
            logo='<a class="jjb-header__logo-link" href="/" aria-label="JuJuBit">'
            "<svg viewBox='0 0 1 1'></svg></a>"
        )

        self.assertEqual(check_logo_accessible_name(html), [])

    def test_img_logo_with_alt_still_passes(self) -> None:
        """主题换回图片 Logo 时，img alt 同样满足无障碍名称要求。"""
        html = compliant_html(
            logo='<a class="site-logo" href="/">'
            '<img src="/logo.png" alt="JuJuBit - Custom Figurines"></a>'
        )

        self.assertEqual(check_logo_accessible_name(html), [])

    def test_logo_without_any_accessible_name_is_reported(self) -> None:
        """读屏器只会念出一个无意义链接，必须报出来。"""
        html = compliant_html(
            logo='<a class="jjb-header__logo-link" href="/">'
            "<svg viewBox='0 0 1 1'></svg></a>"
        )

        problems = check_logo_accessible_name(html)

        self.assertTrue(any("无障碍名称" in item for item in problems))

    def test_missing_logo_anchor_is_reported(self) -> None:
        self.assertEqual(
            check_logo_accessible_name(compliant_html(logo="")),
            ["未找到指向首页的 Logo 锚点"],
        )

    def test_wrong_accessible_name_is_reported(self) -> None:
        html = compliant_html(
            logo="<a class='jjb-header__logo-link' href='/' aria-label='Home'>"
            "<svg viewBox='0 0 1 1'></svg></a>"
        )

        self.assertTrue(check_logo_accessible_name(html))

    def test_json_ld_matching_ssr_passes(self) -> None:
        self.assertEqual(check_json_ld_faq_matches_ssr(compliant_html()), [])

    def test_broken_json_ld_is_reported(self) -> None:
        html = compliant_html(
            json_ld='<script type="application/ld+json">{"@type":]</script>'
        )

        problems = check_json_ld_faq_matches_ssr(html)

        self.assertTrue(any("无法解析" in item for item in problems))

    def test_json_ld_question_absent_from_ssr_is_reported(self) -> None:
        """结构化数据宣称的问答必须真实存在，否则属于向搜索引擎虚报内容。"""
        html = compliant_html(
            json_ld="""
            <script type="application/ld+json">
            {"@type":"FAQPage","mainEntity":[
              {"@type":"Question","name":"A question never rendered"}
            ]}
            </script>
            """
        )

        problems = check_json_ld_faq_matches_ssr(html)

        self.assertTrue(any("不存在" in item for item in problems))

    def test_missing_json_ld_is_reported(self) -> None:
        self.assertEqual(
            check_json_ld_faq_matches_ssr(compliant_html(json_ld="")),
            ["缺少 application/ld+json 结构化数据"],
        )

    def test_json_ld_without_faq_page_is_tolerated(self) -> None:
        """只声明 Organization 等类型时不强制 FAQ 一致性。"""
        html = compliant_html(
            json_ld='<script type="application/ld+json">'
            '{"@type":"Organization","name":"JuJuBit"}</script>'
        )

        self.assertEqual(check_json_ld_faq_matches_ssr(html), [])


class AggregateReportTests(unittest.TestCase):
    def test_check_all_collects_every_failing_contract(self) -> None:
        html = compliant_html(title="<title>错的</title>", faq="", logo="<img>")

        report = check_all(html)

        self.assertIn("SEO 元数据", report)
        self.assertIn("FAQ 服务端渲染", report)
        self.assertIn("Logo 无障碍名称", report)
        # 未受影响的契约不应出现在报告里。
        self.assertNotIn("唯一 H1", report)
        self.assertNotIn("导航真实锚点", report)


if __name__ == "__main__":
    unittest.main()
