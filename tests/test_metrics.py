"""性能脚本共用统计与归一化实现的离线单测。

这里锁定的是"同一份数据只能得出一个结论"。此前 _percentile 在多个脚本里各写
一遍并写出了两种算法，导致 generate_website_performance_report 汇总 Pingdom
数据时与 pingdom_link_performance 自己算出的 P95 不一致。
"""

from __future__ import annotations

import math
import unittest

from scripts._metrics import (
    ASSET_PATH_RE,
    canonical_query,
    format_bytes,
    normalize_url,
    percentile,
)


class PercentileTests(unittest.TestCase):
    def test_empty_input_returns_none(self) -> None:
        self.assertIsNone(percentile([], 0.95))

    def test_single_value_returns_that_value(self) -> None:
        self.assertEqual(percentile([42], 0.5), 42)
        self.assertEqual(percentile([42], 0.95), 42)

    def test_input_order_does_not_matter(self) -> None:
        self.assertEqual(percentile([500, 100, 300], 0.5), 300)

    def test_p50_and_p95_on_known_sample(self) -> None:
        values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 5000]

        self.assertEqual(percentile(values, 0.50), 500)
        self.assertEqual(percentile(values, 0.95), 5000)

    def test_boundary_percents_return_min_and_max(self) -> None:
        values = [10, 20, 30]

        self.assertEqual(percentile(values, 0), 10)
        self.assertEqual(percentile(values, 1), 30)

    def test_never_interpolates_unobserved_values(self) -> None:
        """分位数必须是真实观测到的样本，插值会产生虚假数字。"""
        values = [100, 900]

        for percent in (0.1, 0.25, 0.5, 0.75, 0.9, 0.95):
            self.assertIn(percentile(values, percent), values)

    def test_matches_nearest_rank_definition_across_sizes(self) -> None:
        """锁定算法为最近秩，防止有人改回上取整秩而使历史报告不可比。"""
        for size in range(1, 41):
            values = list(range(1, size + 1))
            for percent in (0.5, 0.9, 0.95):
                expected = values[min(size - 1, round((size - 1) * percent))]

                self.assertEqual(
                    percentile(values, percent),
                    expected,
                    f"n={size}, p={percent}",
                )

    def test_differs_from_ceiling_rank_where_it_used_to(self) -> None:
        """记录两种算法的真实分歧点，说明统一实现解决的是什么问题。

        n=12、P95 时最近秩取第 11 个样本，上取整秩取第 12 个；此前两个脚本
        对同一批 Pingdom 数据就是这样各报一个 P95。
        """
        values = [100 * (index + 1) for index in range(12)]
        ceiling_rank = values[min(11, math.ceil(12 * 0.95) - 1)]

        self.assertEqual(percentile(values, 0.95), 1100)
        self.assertEqual(ceiling_rank, 1200)


class NormalizeUrlTests(unittest.TestCase):
    def test_canonical_host_and_scheme(self) -> None:
        self.assertEqual(normalize_url("http://www.jujubit.ai/cart"), "https://jujubit.ai/cart")

    def test_root_path_is_preserved(self) -> None:
        self.assertEqual(normalize_url("https://jujubit.ai/"), "https://jujubit.ai/")

    def test_external_and_non_http_are_rejected(self) -> None:
        for url in (
            "https://example.com/cart",
            "ftp://jujubit.ai/cart",
            "mailto:hi@jujubit.ai",
            "not a url",
        ):
            self.assertIsNone(normalize_url(url), url)

    def test_collection_product_paths_collapse_to_product_route(self) -> None:
        self.assertEqual(
            normalize_url("https://jujubit.ai/collections/photo-board/products/board-a"),
            "https://jujubit.ai/products/board-a",
        )

    def test_fragment_is_dropped_and_tracking_params_removed(self) -> None:
        self.assertEqual(
            normalize_url("https://jujubit.ai/cart?utm_source=fb&page=2#top"),
            "https://jujubit.ai/cart?page=2",
        )

    def test_vip_program_query_is_merged(self) -> None:
        """entry_page/return_url 只决定返回位置，页面本身相同。"""
        self.assertEqual(
            normalize_url("https://jujubit.ai/pages/vip-program?entry_page=/cart"),
            "https://jujubit.ai/pages/vip-program",
        )

    def test_static_assets_and_cdn_are_rejected(self) -> None:
        for url in (
            "https://jujubit.ai/assets/theme.css",
            "https://jujubit.ai/files/a.png",
            "https://jujubit.ai/files/a.jpg",
            "https://jujubit.ai/files/a.jpeg",
            "https://jujubit.ai/files/a.JPG",
            "https://jujubit.ai/files/a.woff2",
            "https://jujubit.ai/cdn/shop/files/a.png",
        ):
            self.assertIsNone(normalize_url(url), url)

    def test_jpg_is_recognised_as_asset(self) -> None:
        """曾写成 jpeg? ——匹配 .jpe 却漏掉 .jpg，把图片当成 HTML 页面测量。"""
        self.assertTrue(ASSET_PATH_RE.search("/photo.jpg"))
        self.assertTrue(ASSET_PATH_RE.search("/photo.jpeg"))
        self.assertTrue(ASSET_PATH_RE.search("/photo.JPG"))

    def test_trailing_slash_is_normalized(self) -> None:
        self.assertEqual(
            normalize_url("https://jujubit.ai/a/b/c/"), "https://jujubit.ai/a/b/c"
        )

    def test_same_page_reached_two_ways_normalizes_identically(self) -> None:
        """归一化的目的是同一页面只测一次。"""
        first = normalize_url("https://www.jujubit.ai/cart?utm_medium=x#frag")
        second = normalize_url("http://jujubit.ai/cart/")

        self.assertEqual(first, second)


class CanonicalQueryTests(unittest.TestCase):
    def test_utm_and_tracking_keys_removed(self) -> None:
        self.assertEqual(canonical_query("utm_source=a&_sid=b&page=2"), "page=2")

    def test_duplicate_pairs_collapse(self) -> None:
        self.assertEqual(canonical_query("a=1&a=1"), "a=1")

    def test_distinct_values_for_same_key_are_kept(self) -> None:
        self.assertEqual(canonical_query("a=1&a=2"), "a=1&a=2")

    def test_result_is_order_independent(self) -> None:
        self.assertEqual(canonical_query("b=2&a=1"), canonical_query("a=1&b=2"))


class FormatBytesTests(unittest.TestCase):
    def test_invalid_values_render_dash(self) -> None:
        for value in (None, "", "abc", -1):
            self.assertEqual(format_bytes(value), "-")

    def test_units_scale(self) -> None:
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(2048), "2.0 KB")
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.0 MB")


if __name__ == "__main__":
    unittest.main()
