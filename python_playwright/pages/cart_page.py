"""购物车主流程页面对象。"""

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    expect,
)

from python_playwright.pages.home_page import HomePage, SiteRateLimitError


@dataclass(frozen=True)
class GeneratedResult:
    """本次新生成并已在 Gallery 展示的结果。"""

    history_total: int
    image_url: str


@dataclass(frozen=True)
class CartSnapshot:
    """用于比较半屏、全屏和 Checkout 前数据的一组购物车快照。"""

    title: str
    variant: str
    quantity: int
    subtotal: str
    shipping: str
    image_url: str


class CartTestDataUnavailable(RuntimeError):
    """账号中不存在下游用例可复用的已完成 Gallery 资产。"""


class CartPage:
    """从首页创作到两种购物车入口和 Checkout 的操作集合。"""

    DEFAULT_IMAGE_URL = (
        "https://jujubit.ai/cdn/shop/files/pod_1800x1800.png?v=1770294841"
    )
    CREATOR_PATH = "/products/customize-your-own"
    CHECKOUT_URL = re.compile(r"/checkouts?(?:/|[?#]|$)")
    CART_URL = re.compile(r"/cart(?:[?#]|$)")
    FREE_SHIPPING_THRESHOLD_CENTS = 9_900
    EMPTY_CART_COPY = "Your Cart is Empty"
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

    @property
    def drawer_panel(self):
        return self.drawer.locator(".ccd-panel")

    @property
    def drawer_item(self):
        return self.drawer.locator(".ccd-item").first

    @property
    def full_cart_item(self):
        return self.full_cart.locator(".cc-item").first

    def _record_rate_limit(self, response) -> None:
        if response.status != 429:
            return
        parsed = urlparse(response.url)
        host = (parsed.hostname or "").lower()
        base = urlparse(self.base_url)
        # 首页主文档的 429 由 HomePage.open() 按 Retry-After 退避重试；其他
        # 页面/API/资源的 429 则在下一次关键操作前熔断，避免继续写购物车。
        if (
            (host == base.hostname or host.endswith(".jujubit.ai"))
            and parsed.path != (base.path or "/")
        ):
            self._rate_limited_urls.append(response.url)

    def _raise_if_rate_limited(self) -> None:
        if not self._rate_limited_urls:
            return
        parsed = urlparse(self._rate_limited_urls[-1])
        reason = (
            "站点访问频控（HTTP 429）："
            f"{parsed.netloc}{parsed.path} 未完成，本条购物车用例不计为业务失败。"
        )
        self._mark_rate_limited(reason)
        raise SiteRateLimitError(reason)

    def _mark_rate_limited(self, reason: str) -> None:
        """打开购物车专属及站点级熔断，阻止后续用例继续放大 429。"""
        self.config._jujubit_cart_rate_limited = reason
        self.config._jujubit_site_rate_limited = reason

    def _raise_if_circuit_open(self) -> None:
        """熔断后不再发送新的购物车请求。"""
        reason = (
            getattr(self.config, "_jujubit_cart_rate_limited", "")
            or getattr(self.config, "_jujubit_site_rate_limited", "")
        )
        if reason:
            raise SiteRateLimitError(reason)

    def _pace_cart_request(self) -> None:
        """让购物车关键请求与上一条请求之间保留最小间隔。"""
        # 页面响应监听器可能刚收到异步 429；必须在下一次点击/请求之前消费。
        self._raise_if_rate_limited()
        self._raise_if_circuit_open()
        pacer = getattr(self.config, "_jujubit_cart_pacer", None)
        if pacer is not None:
            pacer.wait()

    def _request_with_rate_limit_retry(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs,
    ):
        """仅重试可以安全重复的 GET/清空请求，并遵循 Retry-After。"""
        parsed = urlparse(url)
        is_safe_clear = method == "post" and parsed.path.rstrip("/") == "/cart/clear.js"
        if method != "get" and not is_safe_clear:
            raise AssertionError(
                "429 自动重试只允许 GET 或 cart/clear.js；"
                f"禁止重放可能产生副作用的请求：{method.upper()} {parsed.path}"
            )
        retries = max(0, self.config.getoption("--pw-429-retries"))
        for attempt in range(retries + 1):
            self._pace_cart_request()
            response = getattr(self.page.request, method)(url, **kwargs)
            if response.status != 429:
                return response
            if attempt < retries:
                delay = self.home._retry_delay(
                    attempt, response.headers.get("retry-after")
                )
                print(
                    f"{operation}触发 HTTP 429，等待 {delay:g} 秒后"
                    f"第 {attempt + 1} 次重试。"
                )
                time.sleep(delay)
                continue
            reason = (
                f"{operation}触发站点访问频控（HTTP 429），"
                f"{retries + 1} 次请求后仍未解除。"
            )
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        raise AssertionError(f"{operation}请求未返回结果")

    def clear_cart(self, *, ignore_errors: bool = False) -> None:
        """清空当前 browser context 的 Shopify 购物车，隔离历史数据。"""
        try:
            response = self._request_with_rate_limit_retry(
                "post",
                urljoin(f"{self.base_url}/", "cart/clear.js"),
                operation="清空购物车时",
                data={},
                timeout=30_000,
            )
            if not response.ok:
                raise AssertionError(f"清空购物车失败：HTTP {response.status}")
        except (AssertionError, PlaywrightError, SiteRateLimitError):
            if not ignore_errors:
                raise

    def cart_json(self) -> dict[str, Any]:
        """读取当前 context 的 Shopify cart，用于服务端状态断言。"""
        response = self._request_with_rate_limit_retry(
            "get",
            urljoin(f"{self.base_url}/", "cart.js"),
            operation="读取购物车时",
            timeout=30_000,
        )
        assert response.ok, f"读取购物车失败：HTTP {response.status}"
        return response.json()

    def open_home(self) -> None:
        """从首页开始主流程，并关闭可能遮挡入口的优惠弹窗。"""
        # HomePage 与购物车使用同一个频控异常类型，测试层可统一跳过而非记业务失败。
        self.home.open()
        self.home.close_welcome_popup()

    def open_creator_from_header(self) -> None:
        """点击首页左上角 Create，并确认创作组件完成挂载。"""
        create_link = self.page.locator(".jjb-header__create:visible").first
        expect(create_link).to_be_visible()
        expect(create_link).to_have_attribute("href", self.CREATOR_PATH)
        self._pace_cart_request()
        create_link.click()
        self.page.wait_for_url(re.compile(r"/products/customize-your-own(?:[?#]|$)"))
        self._raise_if_rate_limited()
        self._wait_for_creator_ready()
        self.home.close_welcome_popup()

    def assert_creator_controls(self) -> None:
        """确认创作页真实可操作，而不只验证 URL 已改变。"""
        root = self.page.locator("#jjb-create-canvas")
        expect(root).to_have_attribute("data-jjb-create-mount-status", "mounted")
        expect(self.page.locator("main input[type=file]").first).to_be_attached()
        expect(self.page.locator("button.jjb-tool--generate")).to_be_attached()
        expect(
            root.locator("button").filter(has_text=re.compile(r"^Create$")).first
        ).to_be_attached()
        expect(
            root.locator("button").filter(has_text=re.compile(r"^Gallery$")).first
        ).to_be_attached()

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
            response = self._request_with_rate_limit_retry(
                "get",
                image_source,
                operation="下载购物车测试图片时",
                fail_on_status_code=False,
                timeout=60_000,
            )
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
        self._pace_cart_request()
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

        # 生成流程会在 2D 完成后自动切到 3D 构建；资源加载判断不能依赖当前面板可见。
        self._poll_until(
            self._generated_image_loaded,
            deadline,
            "本次结果的 2D 图片加载完成",
        )
        self._poll_until(
            self._generated_model_loaded,
            deadline,
            "本次结果的 3D 视图可用",
        )

        # 两类资源均已完成后再主动切换，分别验证用户实际可以看到 2D 和 3D。
        self._visible_button("2D").click()
        expect(self.page.locator('[data-view-name="2d"]:visible')).to_be_visible(
            timeout=10_000
        )
        image_url = self._generated_image_url(visible_only=True)
        assert image_url, "切换到 2D 后未展示已加载的生成结果图片"

        self._visible_button("3D").click()
        expect(self.page.locator('[data-view-name="3d"]:visible')).to_be_visible(
            timeout=10_000
        )
        # 资源已经就绪后，再确认切换后的实际渲染节点也对用户可见。
        expect(
            self.page.locator('[data-view-name="3d"]:visible canvas:visible').first
        ).to_be_visible(timeout=10_000)
        return GeneratedResult(self.history_total(), image_url)

    def open_existing_gallery_result(self, timeout_seconds: int = 120) -> GeneratedResult:
        """打开账号中已有的成功资产，供不需要重复生成的购物车 case 复用。"""
        history_total = self.history_total()
        if history_total < 1:
            raise CartTestDataUnavailable(
                "账号 Gallery 中没有可复用资产；请先让 CART-02 成功生成一次。"
            )
        self.open_gallery()
        deadline = time.monotonic() + max(1, timeout_seconds)
        try:
            self._poll_until(
                self._generated_image_loaded,
                deadline,
                "已有 Gallery 资产的 2D 图片加载完成",
            )
            # 历史记录可能默认停在 2D；3D 就绪判断只检查当前可见的 renderer。
            self._visible_button("3D").click()
            expect(self.page.locator('[data-view-name="3d"]:visible')).to_be_visible()
            self._poll_until(
                self._generated_model_loaded,
                deadline,
                "已有 Gallery 资产的 3D 视图可用",
            )
        except (AssertionError, PlaywrightError) as error:
            raise CartTestDataUnavailable(
                f"账号最新 Gallery 记录不可用于购物车回归：{error}"
            ) from error

        self._visible_button("2D").click()
        expect(self.page.locator('[data-view-name="2d"]:visible')).to_be_visible()
        image_url = self._generated_image_url(visible_only=True)
        if not image_url:
            raise CartTestDataUnavailable("已有 Gallery 记录未提供可见 2D 图片。")
        self._visible_button("3D").click()
        expect(self.page.locator('[data-view-name="3d"]:visible')).to_be_visible()
        expect(
            self.page.locator('[data-view-name="3d"]:visible canvas:visible').first
        ).to_be_visible()
        return GeneratedResult(history_total, image_url)

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
        return bool(self._generated_image_url())

    def _generated_image_url(self, *, visible_only: bool = False) -> str:
        """返回已加载的 2D 结果地址；生成阶段允许面板被前端自动隐藏。"""
        selector = (
            '[data-view-name="2d"]:visible img:visible'
            if visible_only
            else '[data-view-name="2d"] img'
        )
        return (
            self.page.locator(selector).evaluate_all(
                """images => {
                    const loaded = image => {
                        const source = image.currentSrc || image.getAttribute('src') || '';
                        return Boolean(source && image.complete && image.naturalWidth > 0);
                    };
                    const preferred = images.find(image =>
                        image.getAttribute('alt') === 'Generated Toy Result' && loaded(image)
                    );
                    const result = preferred || images.find(loaded);
                    return result
                        ? (result.currentSrc || result.getAttribute('src') || '')
                        : '';
                }"""
            )
            or ""
        )

    def _generated_model_loaded(self) -> bool:
        view = self.page.locator('[data-view-name="3d"]:visible').first
        if not view.count():
            return False

        # Playwright 定位器可以穿透 model-viewer 的开放 Shadow DOM，兼容普通
        # 模型和 Splat；Loading 遮罩消失后才把已出现的画布视为真正完成。
        loading = view.get_by_text("Loading 3D Model...", exact=True)
        renderer = view.locator("canvas:visible")
        return bool(
            not loading.count()
            and renderer.count()
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
            self._pace_cart_request()
            add_button.click()
        response = response_info.value
        if response.status == 429:
            reason = "Gallery 加购时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"Gallery 加购接口失败：HTTP {response.status}"
        expect(self.drawer).to_be_visible(timeout=30_000)
        assert urlparse(self.page.url).path != "/cart", "Add to Cart 不应直接进入全屏购物车"

    def assert_drawer_cart(self, quantity: int) -> None:
        """校验半屏购物车商品、金额、包邮与 Checkout 件数。"""
        expect(self.drawer).to_be_visible()
        expect(self.drawer.locator(".ccd-title")).to_have_text("Cart")
        expect(self.drawer.locator(".ccd-close")).to_be_visible()
        expect(self.drawer.locator(".ccd-item")).to_have_count(1)
        self._assert_cart_image_loaded(self.drawer_item.locator(".ccd-item-img"))
        expect(self.drawer_item.locator(".ccd-item-title")).to_have_text(re.compile(r"\S"))
        expect(self.drawer_item.locator(".ccd-item-variant")).to_have_text(
            re.compile(r"\S+\s*:\s*\S+")
        )
        expect(self.drawer_item.locator(".ccd-item-price")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.drawer.locator(".ccd-subtotal-val")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.drawer.locator(".ccd-qty-num")).to_have_value(str(quantity))
        expect(self.drawer.locator(".ccd-checkout")).to_have_text(f"Checkout ({quantity})")
        self._assert_shipping_copy(self.drawer.locator(".ccd-shipping-text"))
        self.assert_header_badge(quantity)

    def assert_drawer_layout(self, platform: str) -> None:
        """半屏面板必须处于视口内，并符合线上 PC/H5 宽度规则。"""
        box = self.drawer_panel.bounding_box()
        viewport = self.page.viewport_size
        assert box and viewport, "无法取得购物车半屏面板或视口尺寸"
        assert 0 <= box["x"] < viewport["width"]
        assert box["x"] + box["width"] <= viewport["width"] + 1
        assert box["height"] <= viewport["height"] + 1
        expected_width = 350 if platform == "h5" else 450
        assert abs(box["width"] - min(expected_width, viewport["width"] * 0.95)) <= 2

    def assert_header_badge(self, quantity: int) -> None:
        """按 0、1-99、100+ 的线上规则校验 Header 角标。"""
        if quantity <= 0:
            expect(self.header_badge).not_to_be_visible()
            return
        expect(self.header_badge).to_be_visible()
        expect(self.header_badge).to_have_text("99+" if quantity >= 100 else str(quantity))

    def set_drawer_quantity(
        self, quantity: int, *, expected_quantity: Optional[int] = None
    ) -> int:
        """直接提交数量，并等待服务端 cart/change.js 与整套 UI 联动完成。"""
        assert quantity >= 0, "数量输入不能为负数"
        expected_quantity = (
            min(quantity, 100) if expected_quantity is None else expected_quantity
        )
        quantity_input = self.drawer.locator(".ccd-qty-num")
        with self.page.expect_response(
            lambda response: "/cart/change.js" in response.url, timeout=30_000
        ) as response_info:
            self._pace_cart_request()
            quantity_input.fill(str(quantity))
            quantity_input.press("Enter")
        response = response_info.value
        if response.status == 429:
            reason = "修改购物车数量时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"修改购物车数量失败：HTTP {response.status}"
        if expected_quantity == 0:
            self.assert_empty_drawer()
        else:
            expect(self.drawer.locator(".ccd-checkout")).to_have_text(
                f"Checkout ({expected_quantity})", timeout=30_000
            )
            expect(quantity_input).to_have_value(str(expected_quantity))
            self.assert_header_badge(expected_quantity)
        return expected_quantity

    def click_drawer_quantity(self, action: str, expected_quantity: int) -> None:
        """点击加号/减号，并等待数量和汇总完成更新。"""
        assert action in {"increase", "decrease"}
        button = self.drawer.locator(f'.ccd-qty-btn[data-action="{action}"]')
        expect(button).to_be_enabled()
        with self.page.expect_response(
            lambda response: "/cart/change.js" in response.url, timeout=30_000
        ) as response_info:
            self._pace_cart_request()
            button.click()
        response = response_info.value
        if response.status == 429:
            reason = "点击购物车数量按钮时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"点击购物车数量按钮失败：HTTP {response.status}"
        if expected_quantity == 0:
            self.assert_empty_drawer()
            return
        expect(self.drawer.locator(".ccd-qty-num")).to_have_value(
            str(expected_quantity), timeout=30_000
        )
        expect(self.drawer.locator(".ccd-checkout")).to_have_text(
            f"Checkout ({expected_quantity})"
        )
        self.assert_header_badge(expected_quantity)
        self._assert_shipping_copy(self.drawer.locator(".ccd-shipping-text"))

    def assert_drawer_quantity_control(self, quantity: int) -> None:
        """数量 1 显示垃圾桶，2-99 显示减号，100 时加号禁用。"""
        decrease = self.drawer.locator('.ccd-qty-btn[data-action="decrease"]')
        increase = self.drawer.locator('.ccd-qty-btn[data-action="increase"]')
        expect(decrease).to_be_visible()
        expect(increase).to_be_visible()
        if quantity == 1:
            assert decrease.locator("path").count() > 0, "数量 1 时未展示垃圾桶图标"
            assert decrease.locator("line").count() == 0, "数量 1 时仍展示减号"
        else:
            assert decrease.locator("line").count() > 0, "数量大于 1 时未展示减号"
        if quantity >= 100:
            expect(increase).to_be_disabled()
        else:
            expect(increase).to_be_enabled()

    def close_drawer(self) -> None:
        """关闭半屏购物车，但保留服务端购物车数据。"""
        expect(self.drawer.locator(".ccd-close")).to_be_visible()
        self.drawer.locator(".ccd-close").click()
        expect(self.drawer).not_to_be_visible()

    def drawer_snapshot(self) -> CartSnapshot:
        """读取半屏购物车的用户可见数据。"""
        self.assert_drawer_cart(int(self.drawer.locator(".ccd-qty-num").input_value()))
        return CartSnapshot(
            title=self._normalized_text(self.drawer_item.locator(".ccd-item-title")),
            variant=self._normalized_text(self.drawer_item.locator(".ccd-item-variant")),
            quantity=int(self.drawer.locator(".ccd-qty-num").input_value()),
            subtotal=self._normalized_text(self.drawer.locator(".ccd-subtotal-val")),
            shipping=self._shipping_text(self.drawer.locator(".ccd-shipping-text")),
            image_url=self.drawer_item.locator(".ccd-item-img").get_attribute("src") or "",
        )

    def assert_drawer_discount_fields(self) -> None:
        """优惠字段按线上数据条件显示，不把无优惠商品误判为缺字段。"""
        savings_row = self.drawer.locator(".ccd-row-savings")
        if savings_row.is_visible():
            expect(savings_row.locator(".ccd-savings-label")).to_have_text("You Save")
            expect(savings_row.locator(".ccd-savings-val")).to_have_text(
                re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
            )
            expect(self.drawer_item.locator(".ccd-item-original")).to_have_text(
                re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
            )
            expect(self.drawer_item.locator(".ccd-item-discount")).to_have_text(
                re.compile(r"^Save \$[\d,]+(?:\.\d{2})?$")
            )

    def assert_empty_drawer(self) -> None:
        """校验线上最终空态文案、包邮状态和不可结算状态。"""
        expect(self.drawer).to_be_visible()
        expect(self.drawer.locator(".ccd-item")).to_have_count(0, timeout=30_000)
        expect(self.drawer.locator(".ccd-empty.is-visible")).to_be_visible()
        expect(self.drawer.locator(".ccd-empty-img")).to_be_visible()
        expect(self.drawer.locator(".ccd-empty-label")).to_have_text(self.EMPTY_CART_COPY)
        expect(self.drawer.locator(".ccd-shipping-text")).to_have_text(
            "Add $99.00 more to enjoy Free Shipping"
        )
        expect(self.drawer.locator(".ccd-shipping-fill")).to_have_attribute(
            "style", re.compile(r"width:\s*0%")
        )
        expect(self.drawer.locator(".ccd-checkout")).to_be_disabled()
        self.assert_header_badge(0)

    def set_shipping_boundary_total(self, total_cents: int) -> None:
        """只改前端组件 subtotal，稳定覆盖无法用真实 SKU 造出的分币边界。"""
        assert total_cents >= 0
        self.page.wait_for_function(
            "() => customElements.get('custom-cart-drawer') !== undefined",
            timeout=30_000,
        )
        self.page.evaluate(
            """total => {
                const host = document.querySelector('custom-cart-drawer');
                if (!host) throw new Error('custom-cart-drawer is missing');
                host.cart = { ...(host.cart || {}), total_price: total };
                host.updateShippingBar();
                host.open();
            }""",
            total_cents,
        )
        expect(self.drawer).to_be_visible()

    def assert_shipping_boundary(self, total_cents: int) -> None:
        """校验包邮临界文案与进度条。"""
        text = self._shipping_text(self.drawer.locator(".ccd-shipping-text"))
        width = self.drawer.locator(".ccd-shipping-fill").evaluate(
            "element => parseFloat(element.style.width || '0')"
        )
        if total_cents < self.FREE_SHIPPING_THRESHOLD_CENTS:
            remaining = self.FREE_SHIPPING_THRESHOLD_CENTS - total_cents
            assert text == (
                f"Add ${remaining / 100:.2f} more to enjoy Free Shipping"
            )
            assert 0 <= width < 100
        else:
            assert text == self.QUALIFIED_SHIPPING_COPY
            assert width == 100

    def checkout_from_drawer(self) -> None:
        self._checkout(self.drawer.locator(".ccd-checkout"), "半屏购物车")

    def return_to_gallery(self, gallery_url: str, result: GeneratedResult) -> None:
        """从 Checkout 返回刚才的 Gallery，并确认生成记录仍可见。"""
        self._pace_cart_request()
        response = self.page.goto(gallery_url, wait_until="commit")
        if response is not None and response.status == 429:
            reason = "返回 Gallery 时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
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
        expect(self.page.locator('[data-view-name="2d"]:visible')).to_be_visible(
            timeout=10_000
        )
        self._poll_until(
            lambda: bool(self._generated_image_url(visible_only=True)),
            time.monotonic() + 30,
            "返回 Gallery 后 2D 图片可见",
        )
        actual_url = self._generated_image_url(visible_only=True)
        assert urlparse(actual_url).path == urlparse(result.image_url).path, (
            "返回 Gallery 后未恢复刚才生成的 2D 结果"
        )

    def open_full_cart_from_header(
        self, expected_quantity: Optional[int] = None
    ) -> None:
        """点击 Header Cart，并确认进入全屏 /cart。"""
        self.home.close_welcome_popup()
        expect(self.header_cart).to_be_visible()
        if expected_quantity is not None:
            self.assert_header_badge(expected_quantity)
        elif self.header_badge.count() and self.header_badge.is_visible():
            expect(self.header_badge).to_have_text(re.compile(r"^(?:[1-9]\d?|99\+)$"))
        self._pace_cart_request()
        self.header_cart.click()
        self.page.wait_for_url(self.CART_URL, timeout=30_000)
        self._raise_if_rate_limited()
        self.home.close_welcome_popup()
        expect(self.full_cart).to_be_visible(timeout=30_000)

    def assert_full_cart_page(self, quantity: int) -> None:
        """兼容主流程调用，校验全屏购物车的完整内容。"""
        self.assert_full_cart_content(quantity)

    def assert_full_cart_content(self, quantity: int) -> None:
        """校验全屏购物车商品、汇总、包邮区和 Checkout 控件。"""
        expect(self.full_cart).to_be_visible()
        expect(self.full_cart.locator(".cc-title")).to_have_text("Cart")
        expect(self.full_cart.locator(".cc-close")).to_be_visible()
        expect(self.full_cart.locator(".cc-close")).to_have_attribute(
            "aria-label", "Close"
        )
        expect(self.full_cart.locator(".cc-item")).to_have_count(1)
        self._assert_cart_image_loaded(self.full_cart_item.locator(".cc-item-img"))
        expect(self.full_cart_item.locator(".cc-item-title")).to_have_text(
            re.compile(r"\S")
        )
        expect(self.full_cart_item.locator(".cc-item-variant")).to_have_text(
            re.compile(r"\S+\s*:\s*\S+")
        )
        expect(self.full_cart_item.locator(".cc-item-price")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.full_cart.locator(".cc-qty-num")).to_have_value(str(quantity))
        expect(self.full_cart.locator(".cc-subtotal-val")).to_have_text(
            re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
        )
        expect(self.full_cart.locator(".cc-row-subtotal")).to_contain_text("Subtotal")
        checkout = self.full_cart.locator(".cc-checkout")
        expect(checkout).to_have_text(f"Checkout ({quantity})", timeout=30_000)
        expect(checkout).to_be_enabled(timeout=30_000)
        expect(self.full_cart.locator(".cc-disclaimer")).to_have_text(
            "Shipping, taxes, and discount codes calculated at checkout."
        )
        self._assert_shipping_copy(self.full_cart.locator(".cc-shipping-text"))
        self._assert_full_cart_discount_fields()

    def _assert_full_cart_discount_fields(self) -> None:
        """有优惠时校验全屏购物车的原价、优惠金额和 You Save。"""
        savings_row = self.full_cart.locator(".cc-row-savings")
        if savings_row.is_visible():
            expect(savings_row.locator(".cc-savings-label")).to_have_text("You Save")
            expect(savings_row.locator(".cc-savings-val")).to_have_text(
                re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
            )
            expect(self.full_cart_item.locator(".cc-item-original")).to_have_text(
                re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
            )
            expect(self.full_cart_item.locator(".cc-item-discount")).to_have_text(
                re.compile(r"^Save \$[\d,]+(?:\.\d{2})?$")
            )

    def full_cart_snapshot(self) -> CartSnapshot:
        """读取全屏购物车的一组用户可见数据。"""
        quantity = int(self.full_cart.locator(".cc-qty-num").input_value())
        self.assert_full_cart_content(quantity)
        return CartSnapshot(
            title=self._normalized_text(
                self.full_cart_item.locator(".cc-item-title")
            ),
            variant=self._normalized_text(
                self.full_cart_item.locator(".cc-item-variant")
            ),
            quantity=quantity,
            subtotal=self._normalized_text(
                self.full_cart.locator(".cc-subtotal-val")
            ),
            shipping=self._shipping_text(
                self.full_cart.locator(".cc-shipping-text")
            ),
            image_url=(
                self.full_cart_item.locator(".cc-item-img").get_attribute("src") or ""
            ),
        )

    @classmethod
    def assert_snapshots_equal(
        cls, expected: CartSnapshot, actual: CartSnapshot
    ) -> None:
        """比较两个视图中的核心购物车数据，并输出明确的差异字段。"""
        for field_name in ("title", "variant", "quantity", "subtotal", "shipping"):
            expected_value = getattr(expected, field_name)
            actual_value = getattr(actual, field_name)
            assert actual_value == expected_value, (
                f"购物车视图的 {field_name} 不一致："
                f"expected={expected_value!r}, actual={actual_value!r}"
            )

        expected_image = cls._normalized_image_path(expected.image_url)
        actual_image = cls._normalized_image_path(actual.image_url)
        assert expected_image and actual_image, "购物车快照缺少商品图片地址"
        assert actual_image == expected_image, (
            "购物车视图的商品图片不一致："
            f"expected={expected_image!r}, actual={actual_image!r}"
        )

    def assert_full_cart_matches(self, expected: CartSnapshot) -> None:
        """确认全屏购物车与传入的半屏快照一致。"""
        self.assert_snapshots_equal(expected, self.full_cart_snapshot())

    def close_full_cart(self, expected_url: Optional[str] = None) -> None:
        """点击全屏 Close，返回同站来源页或首页，并保留购物车。"""
        current_url = self.page.url
        referrer = self.page.evaluate("() => document.referrer") or ""
        current_host = urlparse(current_url).netloc
        referrer_host = urlparse(referrer).netloc
        target_url = expected_url
        if target_url is None:
            target_url = referrer if referrer and referrer_host == current_host else self.base_url
        expected_path = urlparse(target_url).path or "/"

        close_button = self.full_cart.locator(".cc-close")
        expect(close_button).to_be_visible()
        self._pace_cart_request()
        close_button.click()
        try:
            self.page.wait_for_function(
                "expectedPath => window.location.pathname === expectedPath",
                expected_path,
                timeout=30_000,
            )
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError(
                "全屏购物车 Close 未返回预期页面："
                f"expected_path={expected_path!r}, actual={self.page.url!r}"
            ) from error
        self._raise_if_rate_limited()
        self.home.close_welcome_popup()

    def checkout_from_full_cart(self) -> None:
        self._checkout(self.full_cart.locator(".cc-checkout"), "全屏购物车")

    def assert_checkout_summary(self, expected: CartSnapshot) -> None:
        """确认 Checkout 展示进入前的商品、数量和 Subtotal。"""
        assert self.CHECKOUT_URL.search(urlparse(self.page.url).path), (
            f"当前不是 Checkout 页面：{self.page.url}"
        )
        self.home.close_welcome_popup()
        self._expand_checkout_summary()
        main = self.page.locator("main:visible").first
        expect(main).to_be_visible(timeout=30_000)
        body = self.page.locator("body")
        expect(body).to_contain_text(expected.title, timeout=30_000)
        title_matches = self.page.get_by_text(expected.title, exact=True).all()
        assert any(match.is_visible() for match in title_matches), (
            f"Checkout 商品摘要未显示商品标题：{expected.title!r}"
        )
        # Shopify 的 PC 订单摘要可能位于 main 外侧的 aside；body.inner_text 只包含
        # 实际展示的文本，因此可以同时覆盖 PC 和移动端展开后的摘要。
        summary_text = self._normalized_text(body)

        expected_money = self._normalized_money(expected.subtotal)
        actual_money = self._normalized_money(summary_text)
        assert expected_money in actual_money, (
            "Checkout 未展示购物车 Subtotal："
            f"expected={expected.subtotal!r}, checkout={summary_text!r}"
        )
        assert self._checkout_quantity_is_visible(expected.title, expected.quantity), (
            "Checkout 未展示购物车商品数量："
            f"title={expected.title!r}, quantity={expected.quantity}"
        )
        self.assert_page_integrity()

    def _expand_checkout_summary(self) -> None:
        """移动端 Checkout 默认可能折叠订单摘要，存在开关时将其展开。"""
        toggle = self.page.get_by_role(
            "button",
            name=re.compile(r"(?:show|view|open).*order summary", re.IGNORECASE),
        ).first
        if not toggle.count() or not toggle.is_visible():
            return
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()

    def _checkout_quantity_is_visible(self, title: str, quantity: int) -> bool:
        """在 Checkout 商品行中寻找可见的数量标记。"""
        title_locator = self.page.get_by_text(title, exact=True)
        for match in title_locator.all():
            if not match.is_visible():
                continue
            item = match.locator(
                "xpath=ancestor::*[self::tr or @role='row' "
                "or contains(@class, 'product') "
                "or contains(@class, 'line-item')][1]"
            )
            if not item.count():
                continue
            quantity_nodes = item.locator(
                ".product__quantity, [class*='quantity'], "
                "[aria-label*='quantity' i], [data-testid*='quantity']"
            )
            for node in quantity_nodes.all():
                if not node.is_visible():
                    continue
                evidence = " ".join(
                    filter(
                        None,
                        (
                            self._normalized_text(node),
                            node.get_attribute("aria-label"),
                            node.get_attribute("value"),
                        ),
                    )
                )
                if re.search(rf"(?:^|\D){quantity}(?:\D|$)", evidence):
                    return True

            item_text = self._normalized_text(item)
            if re.search(
                rf"\b(?:quantity\s*:?\s*{quantity}|{quantity}\s*[x×])\b",
                item_text,
                re.IGNORECASE,
            ):
                return True
        return False

    def assert_page_integrity(
        self, expected_cart_quantity: Optional[int] = None
    ) -> None:
        """失败请求后不得白屏、出现非法值或形成与服务端不一致的 UI。"""
        body = self.page.locator("body")
        expect(body).to_be_visible()
        body_text = self._normalized_text(body)
        assert body_text, "购物车请求失败后页面变成白屏"
        assert not re.search(
            r"(?:\$\s*)?\b(?:nan|null|undefined)\b|"
            r"checkout\s*\(\s*(?:nan|null|undefined)\s*\)",
            body_text,
            re.IGNORECASE,
        ), f"购物车页面出现 NaN/null/undefined：{body_text!r}"
        assert not re.search(
            r"this page (?:isn't|is not) working|http error \d+",
            body_text,
            re.IGNORECASE,
        ), f"购物车请求失败后进入浏览器错误页：{body_text!r}"

        if expected_cart_quantity is None:
            return
        actual_quantity = int(self.cart_json().get("item_count", 0))
        assert actual_quantity == expected_cart_quantity, (
            "购物车服务端数量与预期不一致："
            f"expected={expected_cart_quantity}, actual={actual_quantity}"
        )
        self.assert_header_badge(expected_cart_quantity)
        if self.drawer.is_visible():
            if expected_cart_quantity == 0:
                expect(self.drawer.locator(".ccd-item")).to_have_count(0)
            else:
                expect(self.drawer.locator(".ccd-qty-num")).to_have_value(
                    str(expected_cart_quantity)
                )
        if self.full_cart.is_visible():
            if expected_cart_quantity == 0:
                expect(self.full_cart.locator(".cc-item")).to_have_count(0)
            else:
                expect(self.full_cart.locator(".cc-qty-num")).to_have_value(
                    str(expected_cart_quantity)
                )

    def _checkout(self, button, source: str) -> None:
        """从指定购物车入口进入 Checkout；有副作用的点击只执行一次。"""
        self.home.close_welcome_popup()
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        self._pace_cart_request()
        button.click()
        try:
            self.page.wait_for_url(self.CHECKOUT_URL, timeout=60_000)
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError(f"{source}点击 Checkout 后未进入结算页：{self.page.url}") from error
        self._raise_if_rate_limited()
        expect(self.page.locator("main:visible").first).to_be_visible(timeout=30_000)

    def _assert_shipping_copy(self, locator) -> None:
        text = self._shipping_text(locator)
        assert text == self.QUALIFIED_SHIPPING_COPY or self.SHIPPING_COPY.fullmatch(text), (
            f"购物车包邮文案不符合线上规则：{text!r}"
        )

    @classmethod
    def _shipping_text(cls, locator) -> str:
        """去掉包邮成功文案前的装饰字符，保留用户可读正文。"""
        return cls._normalized_text(locator).lstrip("🎉 ")

    @staticmethod
    def _normalized_text(locator_or_text) -> str:
        """统一 DOM 文本中的空白，供跨页面快照比较。"""
        if isinstance(locator_or_text, str):
            value = locator_or_text
        else:
            value = locator_or_text.inner_text()
        return " ".join(value.replace("\xa0", " ").split())

    @staticmethod
    def _normalized_money(text: str) -> str:
        """金额比较忽略千分位和空白，但保留币种符号与小数。"""
        return re.sub(r"[\s,]", "", text)

    @staticmethod
    def _normalized_image_path(image_url: str) -> str:
        """忽略 CDN 查询参数，比较同一生成图片的稳定路径。"""
        parsed = urlparse(image_url)
        return parsed.path or image_url.split("?", 1)[0]

    @staticmethod
    def _assert_cart_image_loaded(image) -> None:
        expect(image).to_be_visible()
        assert image.evaluate("img => img.complete && img.naturalWidth > 0"), (
            "购物车中的生成图片未成功加载"
        )
