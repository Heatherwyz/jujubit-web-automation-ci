"""购物车主流程页面对象。"""

from dataclasses import dataclass
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from python_playwright.pages.home_page import HomePage


class SiteRateLimitError(RuntimeError):
    """站点或生成接口返回 HTTP 429，业务断言无法继续。"""


@dataclass(frozen=True)
class GeneratedResult:
    """本次新生成并已在 Gallery 展示的结果。"""

    history_total: int
    image_url: str


class CartPage:
    """从首页创作到两种购物车入口和 Checkout 的操作集合。"""

    DEFAULT_IMAGE_URL = (
        "https://jujubit.ai/cdn/shop/files/pod_1800x1800.png?v=1770294841"
    )
    CREATOR_PATH = "/products/customize-your-own"
    CHECKOUT_URL = re.compile(r"/checkouts?(?:/|[?#]|$)")
    CART_URL = re.compile(r"/cart(?:[?#]|$)")
    SHIPPING_COPY = re.compile(
        r"^Add \$[\d,]+(?:\.\d{2})? more to enjoy Free Shipping$"
    )
    QUALIFIED_SHIPPING_COPY = "You've qualified for free standard shipping"
    GENERATION_ERRORS = (
        "We couldn’t generate from this image. Please try a different one",
        "Taking longer than expected. Please try again.",
        "Failed to fetch",
        "Failed to load 3D model. Please retry.",
        "You can run up to 6 generation tasks at the same time.",
        "Daily limit of",
    )

    def __init__(self, page: Page, base_url: str, config):
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.home = HomePage(page, self.base_url, config)
        self._rate_limited_urls: list[str] = []
        page.on("response", self._record_rate_limit)

    @property
    def drawer(self):
        return self.page.locator(".ccd.is-open")

    @property
    def full_cart(self):
        return self.page.locator("custom-cart .cc")

    @property
    def header_cart(self):
        return self.page.locator(".jjb-header__cart:visible").first

    @property
    def header_badge(self):
        return self.page.locator("[data-cart-count]:visible").first

    def _record_rate_limit(self, response) -> None:
        if response.status != 429:
            return
        host = (urlparse(response.url).hostname or "").lower()
        if host == urlparse(self.base_url).hostname or host.endswith(".jujubit.ai"):
            self._rate_limited_urls.append(response.url)

    def _raise_if_rate_limited(self) -> None:
        if not self._rate_limited_urls:
            return
        parsed = urlparse(self._rate_limited_urls[-1])
        raise SiteRateLimitError(
            "站点访问频控（HTTP 429）："
            f"{parsed.netloc}{parsed.path} 未完成，本条购物车用例不计为业务失败。"
        )

    def clear_cart(self, *, ignore_errors: bool = False) -> None:
        """清空当前 browser context 的 Shopify 购物车，隔离历史数据。"""
        try:
            response = self.page.request.post(
                urljoin(f"{self.base_url}/", "cart/clear.js"),
                data={},
                timeout=30_000,
            )
            if response.status == 429:
                raise SiteRateLimitError("清空购物车时触发站点访问频控（HTTP 429）。")
            if not response.ok:
                raise AssertionError(f"清空购物车失败：HTTP {response.status}")
        except (AssertionError, PlaywrightError, SiteRateLimitError):
            if not ignore_errors:
                raise

    def open_home(self) -> None:
        """从首页开始主流程，并关闭可能遮挡入口的优惠弹窗。"""
        try:
            self.home.open()
        except AssertionError as error:
            if "HTTP 429" in str(error):
                raise SiteRateLimitError(str(error)) from error
            raise
        self.home.close_welcome_popup()

    def open_creator_from_header(self) -> None:
        """点击首页左上角 Create，并确认创作组件完成挂载。"""
        create_link = self.page.locator(".jjb-header__create:visible").first
        expect(create_link).to_be_visible()
        expect(create_link).to_have_attribute("href", self.CREATOR_PATH)
        create_link.click()
        self.page.wait_for_url(re.compile(r"/products/customize-your-own(?:[?#]|$)"))
        self._raise_if_rate_limited()
        self._wait_for_creator_ready()
        self.home.close_welcome_popup()

    def _wait_for_creator_ready(self) -> None:
        try:
            self.page.wait_for_function(
                """() => {
                    const root = document.querySelector('#jjb-create-canvas');
                    return root?.dataset.jjbCreateMountStatus === 'mounted'
                        && [...root.querySelectorAll('button')]
                            .some(button => button.textContent.trim() === 'Gallery');
                }""",
                timeout=60_000,
            )
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError("创作页面已跳转，但创作组件未在 60 秒内完成加载") from error

    def history_total(self) -> int:
        """读取 Gallery 的 History 总数，用于证明结果来自本次生成。"""
        label = self.page.get_by_text(re.compile(r"^History \(\d+\)$"), exact=True).first
        try:
            label.wait_for(state="attached", timeout=30_000)
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError("创作页未展示 Gallery History 数量") from error
        values = []
        for text in self.page.get_by_text(
            re.compile(r"^History \(\d+\)$"), exact=True
        ).all_inner_texts():
            match = re.fullmatch(r"History \((\d+)\)", text.strip())
            if match:
                values.append(int(match.group(1)))
        assert values, "Gallery History 数量文案格式异常"
        return max(values)

    def upload_image(self, source: str = "") -> None:
        """上传本地图片或 URL 图片，并等待预览与 Generate 可用。"""
        upload_input = self.page.locator("main input[type=file]").first
        expect(upload_input).to_be_attached()
        image_source = source.strip() or self.DEFAULT_IMAGE_URL
        local_path = Path(image_source).expanduser()
        if local_path.is_file():
            upload_input.set_input_files(str(local_path))
        elif urlparse(image_source).scheme in {"http", "https"}:
            response = self.page.request.get(
                image_source,
                fail_on_status_code=False,
                timeout=60_000,
            )
            if response.status == 429:
                raise SiteRateLimitError("下载购物车测试图片时触发 HTTP 429。")
            assert response.ok, (
                f"购物车测试图片下载失败：HTTP {response.status}，{image_source}"
            )
            mime_type = response.headers.get("content-type", "").split(";", 1)[0]
            assert mime_type in {"image/png", "image/jpeg", "image/webp"}, (
                f"购物车测试图片类型不受支持：{mime_type or '未返回 Content-Type'}"
            )
            suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[
                mime_type
            ]
            upload_input.set_input_files(
                {
                    "name": f"jujubit-cart-e2e.{suffix}",
                    "mimeType": mime_type,
                    "buffer": response.body(),
                }
            )
        else:
            raise AssertionError(f"购物车测试图片不存在或不是有效 URL：{image_source}")

        expect(self.page.get_by_role("button", name="Delete image", exact=True)).to_be_visible(
            timeout=30_000
        )
        expect(self.page.locator("button.jjb-tool--generate")).to_be_enabled(timeout=30_000)

    def generate_once(self) -> None:
        """只点击一次 Generate；不重试，避免重复创建计费任务。"""
        self.home.close_welcome_popup()
        generate = self.page.locator("button.jjb-tool--generate")
        expect(generate).to_be_visible()
        expect(generate).to_be_enabled()
        generate.click()

    def wait_for_new_gallery_result(
        self, previous_total: int, timeout_seconds: int
    ) -> GeneratedResult:
        """等待 History 增加，随后验证当前结果的 2D 图片和 3D 模型。"""
        deadline = time.monotonic() + max(1, timeout_seconds)
        self._poll_until(
            lambda: self.history_total() > previous_total,
            deadline,
            f"Gallery History 数量大于生成前的 {previous_total}",
        )
        self.open_gallery()

        two_d_button = self._visible_button("2D")
        two_d_button.click()
        self._poll_until(
            self._generated_image_loaded,
            deadline,
            "本次结果的 2D 图片加载完成",
        )
        generated_image = self.page.locator(
            '[data-view-name="2d"]:visible img[alt="Generated Toy Result"]'
        ).first
        image_url = generated_image.get_attribute("src") or ""
        assert image_url, "2D 生成结果图片缺少 src"

        self._poll_until(
            self._generated_model_loaded,
            deadline,
            "本次结果的 3D model-viewer 或 canvas 加载完成",
        )
        self._visible_button("3D").click()
        expect(self.page.locator('[data-view-name="3d"]:visible')).to_be_visible()
        return GeneratedResult(self.history_total(), image_url)

    def _poll_until(self, predicate, deadline: float, description: str) -> None:
        while time.monotonic() < deadline:
            self._raise_if_rate_limited()
            error_text = self._visible_generation_error()
            if error_text:
                raise AssertionError(f"生成任务失败：{error_text}")
            if predicate():
                return
            self.page.wait_for_timeout(1_000)
        self._raise_if_rate_limited()
        raise AssertionError(f"等待超时：{description}")

    def _visible_generation_error(self) -> str:
        body_text = self.page.locator("body").inner_text()
        return next((text for text in self.GENERATION_ERRORS if text in body_text), "")

    def _generated_image_loaded(self) -> bool:
        image = self.page.locator(
            '[data-view-name="2d"]:visible img[alt="Generated Toy Result"]'
        ).first
        return bool(
            image.count()
            and image.evaluate("img => img.complete && img.naturalWidth > 0")
        )

    def _generated_model_loaded(self) -> bool:
        return bool(
            self.page.evaluate(
                """() => [...document.querySelectorAll('[data-view-name="3d"]')]
                    .some(view => {
                        const model = view.querySelector('model-viewer[src]');
                        if (model?.loaded === true) return true;
                        const canvas = view.querySelector('canvas');
                        return Boolean(canvas && canvas.width > 0 && canvas.height > 0);
                    })"""
            )
        )

    def _visible_button(self, name: str):
        button = self.page.locator("button:visible").filter(
            has_text=re.compile(rf"^{re.escape(name)}$")
        ).first
        expect(button).to_be_visible()
        return button

    def open_gallery(self) -> None:
        """切换到 Gallery，并确认当前生成结果区域可交互。"""
        gallery = self.page.locator("button:visible").filter(
            has_text=re.compile(r"^Gallery$")
        ).first
        expect(gallery).to_be_visible()
        self.page.wait_for_function(
            """() => [...document.querySelectorAll('#jjb-create-canvas button')]
                .some(button => button.textContent.trim() === 'Gallery'
                    && !button.classList.contains('opacity-50'))""",
            timeout=30_000,
        )
        gallery.click()
        expect(self._visible_button("2D")).to_be_visible()
        expect(self._visible_button("3D")).to_be_visible()

    def add_current_model_to_cart(self) -> None:
        """当前 Gallery 模型只加购一次，并等待半屏购物车打开。"""
        self.home.close_welcome_popup()
        add_button = self.page.locator("button:visible").filter(
            has_text=re.compile(r"^Add to Cart$")
        ).first
        expect(add_button).to_be_visible()
        expect(add_button).to_be_enabled()
        with self.page.expect_response(
            lambda response: "/cart/add.js" in response.url,
            timeout=30_000,
        ) as response_info:
            add_button.click()
        response = response_info.value
        if response.status == 429:
            raise SiteRateLimitError("Gallery 加购时触发站点访问频控（HTTP 429）。")
        assert response.ok, f"Gallery 加购接口失败：HTTP {response.status}"
        expect(self.drawer).to_be_visible(timeout=30_000)
        assert urlparse(self.page.url).path != "/cart", "Add to Cart 不应直接进入全屏购物车"

    def assert_drawer_cart(self, quantity: int) -> None:
        """校验半屏购物车商品、金额、包邮与 Checkout 件数。"""
        expect(self.drawer).to_be_visible()
        expect(self.drawer.locator(".ccd-item")).to_have_count(1)
        self._assert_cart_image_loaded(self.drawer.locator(".ccd-item img").first)
        expect(self.drawer.locator(".ccd-subtotal-val")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.drawer.locator(".ccd-qty-num")).to_have_value(str(quantity))
        expect(self.drawer.locator(".ccd-checkout")).to_have_text(f"Checkout ({quantity})")
        self._assert_shipping_copy(self.drawer.locator(".ccd-shipping-text"))

    def set_drawer_quantity(self, quantity: int) -> None:
        """直接输入单 SKU 上限 100，验证 99+ 边界而不连点 99 次。"""
        assert quantity == 100, "本主流程只使用需求明确的单 SKU 上限 100"
        quantity_input = self.drawer.locator(".ccd-qty-num")
        quantity_input.fill(str(quantity))
        quantity_input.press("Enter")
        expect(self.drawer.locator(".ccd-checkout")).to_have_text(
            f"Checkout ({quantity})", timeout=30_000
        )
        expect(quantity_input).to_have_value(str(quantity))
        expect(self.header_badge).to_be_visible()
        expect(self.header_badge).to_have_text("99+")
        expect(self.drawer.locator(".ccd-shipping-text")).to_have_text(
            self.QUALIFIED_SHIPPING_COPY
        )

    def checkout_from_drawer(self) -> None:
        self._checkout(self.drawer.locator(".ccd-checkout"), "半屏购物车")

    def return_to_gallery(self, gallery_url: str, result: GeneratedResult) -> None:
        """从 Checkout 返回刚才的 Gallery，并确认生成记录仍可见。"""
        response = self.page.goto(gallery_url, wait_until="commit")
        if response is not None and response.status == 429:
            raise SiteRateLimitError("返回 Gallery 时触发站点访问频控（HTTP 429）。")
        if response is not None and not response.ok:
            raise AssertionError(f"返回 Gallery 失败：HTTP {response.status}")
        self._wait_for_creator_ready()
        self.home.close_welcome_popup()
        self._poll_until(
            lambda: self.history_total() >= result.history_total,
            time.monotonic() + 60,
            "刚生成的 Gallery History 重新加载",
        )
        self.open_gallery()
        self._visible_button("2D").click()
        image = self.page.locator(
            '[data-view-name="2d"]:visible img[alt="Generated Toy Result"]'
        ).first
        expect(image).to_be_visible(timeout=30_000)
        actual_url = image.get_attribute("src") or ""
        assert urlparse(actual_url).path == urlparse(result.image_url).path, (
            "返回 Gallery 后未恢复刚才生成的 2D 结果"
        )

    def open_full_cart_from_header(self) -> None:
        """点击 Gallery 右上角购物车按钮，并确认进入全屏 /cart。"""
        self.home.close_welcome_popup()
        expect(self.header_badge).to_have_text("99+")
        expect(self.header_cart).to_be_visible()
        self.header_cart.click()
        self.page.wait_for_url(self.CART_URL, timeout=30_000)
        self._raise_if_rate_limited()
        expect(self.full_cart).to_be_visible(timeout=30_000)

    def assert_full_cart_page(self, quantity: int) -> None:
        """校验全屏购物车保留同一商品、数量和 Checkout 能力。"""
        expect(self.full_cart.locator(".cc-close")).to_be_visible()
        expect(self.full_cart.locator(".cc-item")).to_have_count(1)
        self._assert_cart_image_loaded(self.full_cart.locator(".cc-item-img").first)
        expect(self.full_cart.locator(".cc-qty-num")).to_have_value(str(quantity))
        expect(self.full_cart.locator(".cc-subtotal-val")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.full_cart.locator(".cc-checkout")).to_have_text(
            f"Checkout ({quantity})"
        )
        expect(self.full_cart.locator(".cc-checkout")).to_be_enabled()
        expect(self.full_cart.locator(".cc-shipping-text")).to_have_text(
            self.QUALIFIED_SHIPPING_COPY
        )

    def checkout_from_full_cart(self) -> None:
        self._checkout(self.full_cart.locator(".cc-checkout"), "全屏购物车")

    def _checkout(self, button, source: str) -> None:
        """从指定购物车入口进入 Checkout；有副作用的点击只执行一次。"""
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        button.click()
        try:
            self.page.wait_for_url(self.CHECKOUT_URL, timeout=60_000)
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError(f"{source}点击 Checkout 后未进入结算页：{self.page.url}") from error
        self._raise_if_rate_limited()
        expect(self.page.locator("main:visible").first).to_be_visible(timeout=30_000)

    def _assert_shipping_copy(self, locator) -> None:
        text = " ".join(locator.inner_text().split())
        assert text == self.QUALIFIED_SHIPPING_COPY or self.SHIPPING_COPY.fullmatch(text), (
            f"购物车包邮文案不符合线上规则：{text!r}"
        )

    @staticmethod
    def _assert_cart_image_loaded(image) -> None:
        expect(image).to_be_visible()
        assert image.evaluate("img => img.complete && img.naturalWidth > 0"), (
            "购物车中的生成图片未成功加载"
        )
