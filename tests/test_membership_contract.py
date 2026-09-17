"""会员付费墙契约的离线单测：不访问站点，不起浏览器。

喂固定 HTML 样本，锁定契约函数对"合规"和"坏掉"两类输入的判定。
价格等期望值来自 docs/requirements/07-冲突确认结果.md（用户已确认）。
"""

from __future__ import annotations

import unittest

from python_playwright.membership_contract import (
    EXPECTED_FIRST_YEAR_PRICES,
    EXPECTED_MONTHLY_PRICES,
    EXPECTED_YEARLY_PRICES,
    KNOWN_PRICE_MISMATCH_TIERS,
    MOST_POPULAR_TEXT,
    OBSERVED_ONLINE_PRICES,
    TIERS,
    check_all,
    check_most_popular,
    check_monthly_prices,
    check_qa_section,
    check_tier_names,
    check_yearly_prices,
    known_price_mismatch_reason,
)


def compliant_html(**overrides) -> str:
    """生成一份满足全部契约的付费墙 HTML，可按需替换局部片段。"""
    parts = {
        "tiers": (
            "<div class='pricing-card'><h3>Basic</h3><p class='price'>Free</p></div>"
            "<div class='pricing-card'><h3>Pro</h3>"
            "<span class='badge'>Most Popular</span>"
            "<p class='price'>$19.90/mo</p>"
            "<p class='price-yearly'>$238.80/yr</p>"
            "<p class='price-first'>$191.04</p></div>"
            "<div class='pricing-card'><h3>Premium</h3>"
            "<p class='price'>$199.90/mo</p>"
            "<p class='price-yearly'>$2,398.80/yr</p>"
            "<p class='price-first'>$1,919.04</p></div>"
        ),
        "qa": "<section class='faq'><h2>Q&A</h2><details><summary>Q1</summary></details></section>",
    }
    parts.update(overrides)
    return (
        "<!doctype html><html><head><title>Membership</title></head><body>"
        f"{parts['tiers']}{parts['qa']}"
        "</body></html>"
    )


class TierNameTests(unittest.TestCase):
    def test_all_three_tiers_present(self) -> None:
        self.assertEqual(check_tier_names(compliant_html()), [])

    def test_missing_tier_is_reported(self) -> None:
        html = compliant_html(
            tiers="<div><h3>Basic</h3></div><div><h3>Pro</h3></div>"
        )

        problems = check_tier_names(html)

        self.assertTrue(any("Premium" in item for item in problems))

    def test_all_tiers_missing_is_reported(self) -> None:
        problems = check_tier_names("<html><body>nothing</body></html>")

        self.assertEqual(len(problems), 1)
        for tier in TIERS:
            self.assertIn(tier, problems[0])


class MonthlyPriceTests(unittest.TestCase):
    def test_correct_prices_pass(self) -> None:
        self.assertEqual(check_monthly_prices(compliant_html()), [])

    def test_missing_pro_price_is_reported(self) -> None:
        html = compliant_html(
            tiers="<div><h3>Basic</h3></div><div><h3>Pro</h3></div>"
            "<div><h3>Premium</h3><p>$199.90</p></div>"
        )

        problems = check_monthly_prices(html)

        self.assertTrue(any("Pro" in item for item in problems))

    def test_price_without_dollar_sign_still_matches(self) -> None:
        """主题可能把 $ 与数字分开渲染，只要数字在就算通过。"""
        html = compliant_html(
            tiers="<div>Basic</div>"
            "<div>Pro <span>USD</span> 19.90</div>"
            "<div>Premium <span>USD</span> 199.90</div>"
        )

        self.assertEqual(check_monthly_prices(html), [])

    def test_wrong_price_is_reported(self) -> None:
        """价格改错必须报出来——这是最需要抓的回归。

        Premium 已登记为已知不一致（KNOWN_PRICE_MISMATCH_TIERS）会被跳过，
        所以这里只应报出 Pro 一条。登记项清空后该断言需同步改回 2 条。
        """
        html = compliant_html(
            tiers="<div>Basic</div><div>Pro $9.90</div><div>Premium $99.90</div>"
        )

        problems = check_monthly_prices(html)

        expected = 2 - len(KNOWN_PRICE_MISMATCH_TIERS & {"Pro", "Premium"})
        self.assertEqual(len(problems), expected)
        self.assertTrue(any("Pro" in item for item in problems))


class YearlyPriceTests(unittest.TestCase):
    def test_correct_yearly_and_first_year_pass(self) -> None:
        self.assertEqual(check_yearly_prices(compliant_html()), [])

    def test_missing_first_year_price_is_reported(self) -> None:
        html = compliant_html(
            tiers="<div>Basic</div>"
            "<div>Pro $19.90 $238.80</div>"
            "<div>Premium $199.90 $2,398.80</div>"
        )

        problems = check_yearly_prices(html)

        self.assertTrue(any("首年" in item for item in problems))

    def test_comma_variants_are_tolerated(self) -> None:
        """$2,398.80 与 2398.80 都应视为匹配。"""
        html = compliant_html(
            tiers="<div>Basic</div>"
            "<div>Pro $238.80 $191.04</div>"
            "<div>Premium 2398.80 1919.04</div>"
        )

        self.assertEqual(check_yearly_prices(html), [])


class MostPopularTests(unittest.TestCase):
    def test_badge_present_passes(self) -> None:
        self.assertEqual(check_most_popular(compliant_html()), [])

    def test_missing_badge_is_reported(self) -> None:
        html = compliant_html(
            tiers="<div>Basic</div><div>Pro $19.90</div><div>Premium $199.90</div>"
        )

        problems = check_most_popular(html)

        self.assertTrue(problems)
        self.assertIn(MOST_POPULAR_TEXT, problems[0])


class QaSectionTests(unittest.TestCase):
    def test_qa_section_passes(self) -> None:
        self.assertEqual(check_qa_section(compliant_html()), [])

    def test_faq_wording_also_passes(self) -> None:
        html = compliant_html(qa="<section><h2>FAQ</h2></section>")

        self.assertEqual(check_qa_section(html), [])

    def test_frequently_asked_also_passes(self) -> None:
        html = compliant_html(
            qa="<section><h2>Frequently Asked Questions</h2></section>"
        )

        self.assertEqual(check_qa_section(html), [])

    def test_missing_qa_is_reported(self) -> None:
        problems = check_qa_section(compliant_html(qa=""))

        self.assertTrue(problems)


class AggregateTests(unittest.TestCase):
    def test_fully_compliant_html_reports_nothing(self) -> None:
        self.assertEqual(check_all(compliant_html()), {})

    def test_check_all_collects_every_failing_contract(self) -> None:
        html = compliant_html(
            tiers="<div>Basic</div><div>Pro</div>",  # 缺 Premium 与全部价格
            qa="",
        )

        report = check_all(html)

        self.assertIn("三档名称", report)
        self.assertIn("Q&A section", report)
        self.assertIn("Most Popular 标记", report)


class KnownPriceMismatchTests(unittest.TestCase):
    """已知价格不一致的登记机制：不能悄悄把断言改成线上值。"""

    def test_registered_tiers_are_valid(self) -> None:
        self.assertTrue(KNOWN_PRICE_MISMATCH_TIERS <= set(TIERS))

    def test_registered_tiers_have_observed_values(self) -> None:
        """每个登记档位都要记下线上实测值，否则无法判断记录是否过期。"""
        for tier in KNOWN_PRICE_MISMATCH_TIERS:
            self.assertIn(tier, OBSERVED_ONLINE_PRICES, f"{tier} 缺线上实测价格")
            observed = OBSERVED_ONLINE_PRICES[tier]
            for key in ("monthly", "yearly", "first_year"):
                self.assertIn(key, observed, f"{tier} 缺 {key}")

    def test_expected_values_are_not_replaced_by_observed(self) -> None:
        """确认值必须保持产品口径，不能被线上值覆盖——否则等于用实现反推需求。"""
        for tier in KNOWN_PRICE_MISMATCH_TIERS:
            observed = OBSERVED_ONLINE_PRICES[tier]
            self.assertNotEqual(
                EXPECTED_MONTHLY_PRICES[tier],
                observed["monthly"],
                f"{tier} 的确认值被改成了线上值，已知问题记录失去意义",
            )

    def test_reason_names_recovery_condition(self) -> None:
        """xfail 原因必须写清怎么恢复，否则会变成永久静默。"""
        reason = known_price_mismatch_reason()
        if KNOWN_PRICE_MISMATCH_TIERS:
            self.assertIn("KNOWN_PRICE_MISMATCH_TIERS", reason)
            self.assertIn("恢复硬断言", reason)
        else:
            self.assertEqual(reason, "")

    def test_observed_first_year_is_eighty_percent_of_yearly(self) -> None:
        """线上那组价格自身应满足 8 折关系——否则可能是配错了单个数字。"""
        for tier, observed in OBSERVED_ONLINE_PRICES.items():
            yearly = float(observed["yearly"].lstrip("$").replace(",", ""))
            first = float(observed["first_year"].lstrip("$").replace(",", ""))

            self.assertAlmostEqual(first, yearly * 0.8, places=2)


class ConfirmedValueTests(unittest.TestCase):
    """锁定用户已确认的价格，防止被改回旧值。"""

    def test_monthly_prices_match_confirmation(self) -> None:
        self.assertEqual(EXPECTED_MONTHLY_PRICES["Pro"], "$19.90")
        self.assertEqual(EXPECTED_MONTHLY_PRICES["Premium"], "$199.90")

    def test_yearly_prices_match_confirmation(self) -> None:
        self.assertEqual(EXPECTED_YEARLY_PRICES["Pro"], "$238.80")
        self.assertEqual(EXPECTED_YEARLY_PRICES["Premium"], "$2,398.80")

    def test_first_year_is_eighty_percent(self) -> None:
        """首年 8 折：确认过 20% 是打 8 折的意思。"""
        for tier in ("Pro", "Premium"):
            standard = float(
                EXPECTED_YEARLY_PRICES[tier].lstrip("$").replace(",", "")
            )
            first_year = float(
                EXPECTED_FIRST_YEAR_PRICES[tier].lstrip("$").replace(",", "")
            )

            self.assertAlmostEqual(first_year, standard * 0.8, places=2)

    def test_third_tier_is_named_premium(self) -> None:
        """确认过第三档叫 Premium 而非 Prime。"""
        self.assertIn("Premium", TIERS)
        self.assertNotIn("Prime", TIERS)


if __name__ == "__main__":
    unittest.main()
