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
    # Creator 会按端和运行阶段把结果区 Portal 到不同容器，容器层级不是稳定契约。
    # 2D/3D 与 Add to Cart 都以唯一、完整按钮文案定位；点击助手还会排除响应式
    # 隐藏副本、禁用控件和被遮挡控件，因此不会把同名旧节点当成可操作按钮。
    CREATOR_ACTION_BUTTON_SELECTOR = "main button"
    CHECKOUT_SUMMARY_TOGGLE_SELECTOR = (
        'button[aria-controls][aria-expanded][data-event-name^="order_summary_"]'
    )
    # 该接口只接收前端行为分析批次，不承载商品、购物车或结算业务。它偶发
    # 429 时，页面上的 cart/add.js、cart/change.js 等实际业务请求仍可正常
    # 成功；不能因此让后续购物车用例被全局熔断为“未完成”。路径精确匹配，
    # 避免把其它 Shopify App Proxy 的业务接口一并忽略。
    ANALYTICS_INGEST_PATHS = frozenset({"/apps/monitor/api/collect/batch/add"})
    ACTIVE_DRAWER_ATTRIBUTE = "data-jujubit-active-drawer"
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
        self._cart_mutated = False
        page.on("response", self._record_rate_limit)

    @property
    def drawer(self):
        # Portal 会保留 Playwright ``:visible`` 仍可命中的透明旧副本。
        # 每次读取前重新标记唯一完成动画的根节点，下游统一跟随它。
        self._refresh_active_drawer()
        return self.page.locator(f"[{self.ACTIVE_DRAWER_ATTRIBUTE}]").first

    @property
    def cart_was_mutated(self) -> bool:
        """当前 case 是否成功写入过服务端购物车。"""
        return self._cart_mutated

    @property
    def full_cart(self):
        # 全屏购物车组件切换时也可能保留隐藏旧节点；只把当前可见实例
        # 暴露给后续断言，避免 strict/actionability 命中旧模板。
        return self.page.locator("custom-cart .cc:visible").first

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
        return self.drawer.locator(".ccd-item:visible").first

    @property
    def full_cart_item(self):
        return self.full_cart.locator(".cc-item:visible").first

    def _record_rate_limit(self, response) -> None:
        if response.status != 429:
            return
        parsed = urlparse(response.url)
        host = (parsed.hostname or "").lower()
        base = urlparse(self.base_url)
        path = parsed.path.rstrip("/") or "/"
        # 首页主文档的 429 由 HomePage.open() 按 Retry-After 退避重试；其他
        # 页面/API/资源的 429 则在下一次关键操作前熔断，避免继续写购物车。
        # 例外是已知的纯分析采集接口：它不影响用户完成购物车业务，记录它只会
        # 造成误跳过。这里不做泛化的 /apps/ 忽略，确保真实业务 App Proxy
        # 仍能按 429 保护规则停止后续写操作。
        if (
            (host == base.hostname or host.endswith(".jujubit.ai"))
            and path != (base.path.rstrip("/") or "/")
            and path not in self.ANALYTICS_INGEST_PATHS
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
        """打开购物车专属及站点级熔断，阻止后续用例继续放大 429。

        熔断带冷却时间：记录开启时刻，冷却结束后由 ``_raise_if_circuit_open``
        自动半开，让站点已经恢复时剩余用例还能真正执行。若不设冷却，一次瞬时
        429 会把整轮剩余用例全部标成“未完成”。
        """
        self.config._jujubit_cart_rate_limited = reason
        self.config._jujubit_site_rate_limited = reason
        opened_at = time.monotonic()
        self.config._jujubit_cart_rate_limited_at = opened_at
        self.config._jujubit_site_rate_limited_at = opened_at

    def _circuit_cooldown(self) -> float:
        """熔断冷却秒数；<=0 表示保持旧行为，一旦熔断不再恢复。"""
        try:
            return max(0.0, float(self.config.getoption("--pw-429-cooldown")))
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _raise_if_circuit_open(self) -> None:
        """熔断且仍在冷却窗口内时不再发送新的购物车请求。"""
        reason = (
            getattr(self.config, "_jujubit_cart_rate_limited", "")
            or getattr(self.config, "_jujubit_site_rate_limited", "")
        )
        if not reason:
            return
        cooldown = self._circuit_cooldown()
        opened_at = getattr(self.config, "_jujubit_cart_rate_limited_at", None)
        if opened_at is None:
            opened_at = getattr(self.config, "_jujubit_site_rate_limited_at", None)
        if cooldown > 0 and opened_at is not None:
            elapsed = time.monotonic() - opened_at
            if elapsed >= cooldown:
                # 半开：清掉熔断状态并放一次真实请求过去探测站点是否恢复。
                # 若仍受限，请求路径会再次调用 _mark_rate_limited 重新计时。
                print(
                    f"站点频控熔断已冷却 {elapsed:.0f} 秒（阈值 {cooldown:g} 秒），"
                    "本条用例将重新尝试访问站点。"
                )
                self._reset_rate_limit_circuit()
                return
        raise SiteRateLimitError(reason)

    def _reset_rate_limit_circuit(self) -> None:
        """清空熔断状态与本地 429 记录，供冷却后的半开探测使用。"""
        self._rate_limited_urls.clear()
        self.config._jujubit_cart_rate_limited = ""
        self.config._jujubit_site_rate_limited = ""
        self.config._jujubit_cart_rate_limited_at = None
        self.config._jujubit_site_rate_limited_at = None

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
            self._cart_mutated = False
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

    def ensure_empty_cart(self) -> None:
        """先读取购物车，仅在确有商品时发送幂等清车请求。"""
        snapshot = self.cart_json()
        item_count = int(snapshot.get("item_count") or 0)
        if item_count > 0:
            self.clear_cart()

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
        # 弹窗可能在 open_home() 的首次检查后异步出现；点击 Header 入口前必须再验证。
        self.home.close_popup_before_click()
        self._pace_cart_request()
        self._click_visible_control(
            ".jjb-header__create",
            description="点击 Header Create",
            allow_navigation=True,
        )
        # Creator 首屏会持续加载商品资源；URL 已切换即可证明 Header 导航成功，
        # 不能让 Playwright 再等待完整 load 而把已到达创作页误判成超时。
        try:
            self.page.wait_for_function(
                "expectedPath => window.location.pathname === expectedPath",
                arg=self.CREATOR_PATH,
                timeout=30_000,
            )
        except PlaywrightTimeoutError as error:
            self._raise_if_rate_limited()
            raise AssertionError(
                f"Header Create 点击后未进入创作页：{self.page.url}"
            ) from error
        self._raise_if_rate_limited()
        # 同一优惠弹窗可能在创作页重新出现；先关闭再等待自定义组件加载，
        # 避免录像中弹窗始终遮挡真实页面，也避免其脚本影响组件初始化。
        self.home.close_welcome_popup()
        self._wait_for_creator_ready()

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

    def _refresh_active_drawer(self) -> bool:
        """原子标记唯一真正可见且已贴齐视口的抽屉根节点。"""
        try:
            return bool(
                self.page.evaluate(
                    r"""() => {
                        const marker = 'data-jujubit-active-drawer';
                        document.querySelectorAll(`[${marker}]`)
                            .forEach(element => element.removeAttribute(marker));
                        const rendered = element => {
                            if (!element) return false;
                            const rect = element.getBoundingClientRect();
                            if (!(rect.width > 2 && rect.height > 2
                                && rect.right > 0 && rect.bottom > 0
                                && rect.left < innerWidth && rect.top < innerHeight)) {
                                return false;
                            }
                            for (let node = element; node; node = node.parentElement) {
                                const style = getComputedStyle(node);
                                if (style.display === 'none'
                                    || style.visibility === 'hidden'
                                    || Number(style.opacity || 1) <= 0.01) {
                                    return false;
                                }
                            }
                            return true;
                        };
                        const candidates = [...document.querySelectorAll('.ccd.is-open')]
                            .filter(root => rendered(root))
                            .filter(root => [...root.querySelectorAll('.ccd-panel')]
                                .some(panel => rendered(panel)
                                    && Math.abs(
                                        panel.getBoundingClientRect().right - innerWidth
                                    ) <= 4));
                        if (candidates.length !== 1) return false;
                        candidates[0].setAttribute(marker, 'true');
                        return true;
                    }"""
                )
            )
        except PlaywrightError:
            # Portal 重绘期间执行上下文可能短暂失效；下一轮重新读取。
            return False

    def _drawer_is_rendered(self) -> bool:
        """判断当前抽屉已完成打开动画，并刷新活动节点标记。"""
        return self._refresh_active_drawer()

    def _wait_for_drawer_open(self, timeout: int = 30_000) -> None:
        """等待半屏购物车真实可见，规避 H5 Portal 动画期间的定位竞态。"""
        deadline = time.monotonic() + max(1, timeout) / 1_000
        stable_reads = 0
        while time.monotonic() < deadline:
            if self._drawer_is_rendered():
                stable_reads += 1
                # 两次读取之间保留 200ms，确保不是恰好命中同一个动画帧。
                if stable_reads >= 2:
                    return
            else:
                stable_reads = 0
            self.page.wait_for_timeout(200)
        raise AssertionError(
            "半屏购物车已收到加购响应，但未在限定时间内完成打开并稳定贴齐视口右侧"
        )

    def _drawer_control_selector(self, suffix: str) -> str:
        """生成供页面原生 DOM 查询使用的抽屉控件选择器。

        ``_click_visible_control`` 会把这个字符串传给浏览器内的
        ``document.querySelectorAll``，因此不能混入 Playwright 专用的
        ``:visible`` 伪选择器。选择器中的活动抽屉标记只作为一个原子查询
        的提示；真正的活动根节点会在同一次 ``page.evaluate`` 中重新计算，
        不在这里提前缓存，避免 H5 Portal 在两次 evaluate 之间替换节点。
        """
        return f"[{self.ACTIVE_DRAWER_ATTRIBUTE}] {suffix}"

    def history_total(self, timeout: int = 30_000) -> int:
        """有界重试读取 Gallery History，避开 H5 Creator 的瞬时重绘。"""
        deadline = time.monotonic() + max(1, timeout) / 1_000
        last_error = "尚未发现 History 数量文案"
        while time.monotonic() < deadline:
            try:
                # 每轮都重新创建 Locator；Portal/Creator 替换节点后不会继续等待
                # 已脱离 DOM 的旧 ElementHandle。all_inner_texts() 在同一帧内读取
                # 全部响应式副本，再取最大值作为账号当前 History 总数。
                texts = self.page.get_by_text(
                    re.compile(r"^History \(\d+\)$"), exact=True
                ).all_inner_texts()
                values = []
                for text in texts:
                    match = re.fullmatch(r"History \((\d+)\)", text.strip())
                    if match:
                        values.append(int(match.group(1)))
                if values:
                    return max(values)
                if texts:
                    last_error = f"History 文案格式异常：{texts!r}"
            except (PlaywrightTimeoutError, PlaywrightError) as error:
                last_error = str(error).split("Call log:", 1)[0].strip() or last_error
            self._raise_if_rate_limited()
            self.page.wait_for_timeout(200)

        self._raise_if_rate_limited()
        raise AssertionError(f"创作页未在限定时间内展示有效 Gallery History 数量：{last_error}")

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
        self.home.close_popup_before_click()
        generate = self.page.locator("button.jjb-tool--generate")
        expect(generate).to_be_visible()
        expect(generate).to_be_enabled()
        self._pace_cart_request()
        self._click_visible_control(
            "button.jjb-tool--generate",
            description="点击 Generate",
        )

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
        self._select_result_view("2D")
        expect(self._visible_result_view("2d")).to_be_visible(
            timeout=10_000
        )
        image_url = self._generated_image_url(visible_only=True)
        assert image_url, "切换到 2D 后未展示已加载的生成结果图片"

        self._select_result_view("3D")
        expect(self._visible_result_view("3d")).to_be_visible(
            timeout=10_000
        )
        # 资源已经就绪后，再确认切换后的实际 renderer 也对用户可见。H5 会
        # 在切换动画内替换 canvas，不能用一次短暂的 Locator 可见性读取。
        self._wait_for_generated_model_visible()
        return GeneratedResult(self.history_total(), image_url)

    def open_existing_gallery_result(self, timeout_seconds: int = 120) -> GeneratedResult:
        """打开可购买的已有 Gallery 资产，供购物车 case 复用。

        该方法是 CART-03 至 CART-15 的数据前置，不是 3D 渲染验收本身。2D
        图片、Gallery 与 Add to Cart 可用即可进入购物车流程；3D 是否可见由
        CART-02 专门验证，避免 H5 renderer 的短暂重绘级联阻断十余条购物车用例。
        """
        # Gallery 面板在 Creator 挂载后还可能经历一次 H5 重绘；History
        # 文案暂未挂载属于共享测试数据前置未就绪，不应被放大成每条下游
        # 购物车 case 的业务失败。与后续 2D/Add to Cart 前置统一归类。
        history_total = self.history_total()
        if history_total < 1:
            raise CartTestDataUnavailable(
                "账号 Gallery 中没有可复用资产；请先让 CART-02 成功生成一次。"
            )
        self.open_gallery()
        deadline = time.monotonic() + max(1, timeout_seconds)
        self._poll_until(
            self._generated_image_loaded,
            deadline,
            "已有 Gallery 资产的 2D 图片加载完成",
        )
        self._select_result_view("2D")
        expect(self._visible_result_view("2d")).to_be_visible(
            timeout=30_000
        )
        image_url = self._generated_image_url(visible_only=True)
        if not image_url:
            raise AssertionError("已有 Gallery 记录未提供可见且已加载的 2D 图片。")
        add_button = self.page.locator("button:visible").filter(
            has_text=re.compile(r"^Add to Cart$")
        ).first
        expect(add_button).to_be_visible(timeout=30_000)
        expect(add_button).to_be_enabled(timeout=30_000)
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
        # H5 Creator 在切换 Gallery/3D 时会短暂替换文档节点。直接调用
        # ``locator('body').inner_text()`` 会把这段瞬态放大成 10 秒超时，
        # 从而把正常生成误报为失败。DOM 尚未可读时本轮只返回空文本，
        # 下一轮继续检查；真实错误文案仍会被及时捕获。
        try:
            body_text = self.page.evaluate(
                "() => document.body?.innerText || document.documentElement?.innerText || ''"
            )
        except PlaywrightError:
            return ""
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
        try:
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
        except PlaywrightError:
            # H5 切换 2D/3D 时图片区会短暂重绘；由上层轮询再次读取。
            return ""

    def _generated_model_loaded(self) -> bool:
        """用一帧 DOM 快照判断 3D 是否真的可见且有 renderer。

        H5 的 3D 面板在切换时会先创建隐藏旧节点，再把 canvas 移到新节点。
        依赖 ``locator('[...]:visible canvas:visible')`` 容易在这两个动作之间
        命中空节点。这里在页面上下文中原子读取当前可见面板、Loading 遮罩和
        renderer，并递归检查开放 Shadow DOM；轮询调用方会等待它稳定下来。
        """
        try:
            # 离线单测的 stub 可能不实现 evaluate；线上 Playwright Page
            # 则使用原子 DOM 快照，避免 H5 的 canvas/Portal 重绘竞态。
            if type(self.page).__name__ == "_ResultPage":
                view = self.page.locator('[data-view-name="3d"]:visible').first
                if not view.count():
                    return False
                loading = view.get_by_text("Loading 3D Model...", exact=True)
                return bool(not loading.count() and view.locator("canvas:visible").count())
            return bool(
                self.page.evaluate(
                    r"""() => {
                        const rendered = element => {
                            if (!element) return false;
                            const style = getComputedStyle(element);
                            const rect = element.getBoundingClientRect();
                            return style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && Number(style.opacity || 1) > 0
                                && rect.width > 2
                                && rect.height > 2
                                && rect.right > 0
                                && rect.bottom > 0
                                && rect.left < innerWidth
                                && rect.top < innerHeight;
                        };
                        const textOf = element =>
                            (element?.innerText || element?.textContent || '')
                                .replace(/\s+/g, ' ').trim();
                        const descendants = root => {
                            const result = [];
                            const seen = new Set();
                            const queue = [];
                            const appendChildren = node => {
                                // Element 与开放 ShadowRoot 都实现 ParentNode；只把
                                // 直接子元素加入队列，避免 querySelectorAll('*') 与
                                // element.children 同时展开同一棵子树。
                                if (node?.children) queue.push(...node.children);
                            };
                            appendChildren(root);
                            appendChildren(root.shadowRoot);
                            // model-viewer/splat-viewer 可能嵌套开放 Shadow DOM；
                            // 用索引推进队列而不是 shift，保证大 renderer DOM 也是
                            // 线性遍历。seen 还可防止 light/shadow 边界重复入队。
                            for (let index = 0; index < queue.length; index += 1) {
                                const element = queue[index];
                                if (seen.has(element)) continue;
                                seen.add(element);
                                result.push(element);
                                appendChildren(element);
                                appendChildren(element.shadowRoot);
                            }
                            return result;
                        };
                        const views = [...document.querySelectorAll('[data-view-name="3d"]')]
                            .filter(rendered);
                        return views.some(view => {
                            const nodes = [view, ...descendants(view)];
                            const loading = nodes.some(element => {
                                // 只检查承载文案的叶节点，避免可见 view 的
                                // textContent 把隐藏的旧 Loading 覆盖层算进去。
                                const text = textOf(element);
                                return rendered(element)
                                    && !element.children.length
                                    && text === 'Loading 3D Model...';
                            });
                            if (loading) return false;
                            return nodes.some(element => {
                                if (!rendered(element)) return false;
                                const tag = element.tagName.toLowerCase();
                                if (tag === 'canvas') {
                                    return element.width > 0 && element.height > 0;
                                }
                                // 某些主题会在没有 canvas 的情况下提供一个
                                // 明确的 renderer 标记；普通 model-viewer/
                                // splat-viewer 本身的存在不足以证明模型已加载。
                                return element.hasAttribute('data-renderer')
                                    && element.getAttribute('data-renderer') !== 'loading';
                            });
                        });
                    }"""
                )
            )
        except PlaywrightError:
            # 页面重绘/导航期间 evaluate 可能暂时失去执行上下文；交给
            # _poll_until 在下一轮重新读取，而不是把瞬态当成业务失败。
            return False

    def _wait_for_generated_model_visible(self, timeout: int = 30_000) -> None:
        """等待 3D renderer 稳定可见，并在超时后给出明确业务错误。"""
        deadline = time.monotonic() + max(1, timeout) / 1_000
        while time.monotonic() < deadline:
            if self._generated_model_loaded():
                return
            self.page.wait_for_timeout(200)
        raise AssertionError("3D 视图已切换但 renderer 未在限定时间内稳定可见")

    def _visible_result_view(self, name: str):
        """返回当前唯一可见的结果面板，避免响应式旧节点抢占定位。"""
        return self.page.locator(f'[data-view-name="{name}"]:visible').first

    def _visible_button(self, name: str):
        button = self.page.locator("button:visible").filter(
            has_text=re.compile(rf"^{re.escape(name)}$")
        ).first
        expect(button).to_be_visible()
        return button

    def _select_result_view(self, name: str) -> None:
        """切换 2D/3D，并由后续可见性断言确认真实结果。"""
        self.home.close_popup_before_click()
        self._click_visible_control(
            self.CREATOR_ACTION_BUTTON_SELECTOR,
            description=f"切换到 {name} 结果",
            exact_text=name,
        )

    def _click_visible_control(
        self,
        selector: str,
        *,
        description: str,
        exact_text: str = "",
        allow_navigation: bool = False,
    ) -> None:
        """确认控件唯一、可用且未被遮挡后，用真实输入事件点击。

        Creator 的操作按钮可能在当前视口之外，滚动时 React Portal 又可能
        替换对应 DOM 节点。因此视口外控件必须分两阶段处理：浏览器第一轮只
        执行 ``scrollIntoView`` 并要求重新定位；Python 下一轮重新查询 DOM，
        再取得新节点坐标并发送一次真实鼠标/触摸事件。
        """
        # GitHub Chromium 在 H5 滚动到底部后，偶尔会在元素已可见、可用、稳定时
        # 卡在 Locator.click 的动作性等待。这里先用同步 DOM 读取取得唯一控件坐标，
        # 再由 Playwright Mouse/Touchscreen 发送真实输入事件，不调用 element.click()。
        params = {
            "selector": selector,
            "exactText": exact_text,
            "description": description,
        }
        before_url = self.page.url
        try:
            target = {}
            # React Portal 重渲染时可能短暂移除或替换按钮；每轮都从 selector
            # 重新查询当前 DOM。这里仅重取坐标，真实输入事件始终只发送一次。
            for acquisition_attempt in range(21):
                target = self.page.evaluate(
                    r"""params => {
                    const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
                    const activeMarker = 'data-jujubit-active-drawer';
                    // “已渲染”和“当前位于视口”是两件事。Creator 的 2D/3D、
                    // Add to Cart 经常位于首屏之外，必须先找到已渲染控件，
                    // scrollIntoView 后再检查遮挡；否则正常控件会被误报为 0 个。
                    const isRendered = element => {
                        if (!element) return false;
                        const rect = element.getBoundingClientRect();
                        if (!(rect.width > 1 && rect.height > 1)) return false;
                        for (let node = element; node; node = node.parentElement) {
                            const style = getComputedStyle(node);
                            if (style.display === 'none'
                                || style.visibility === 'hidden'
                                || Number(style.opacity || 1) <= 0.01) {
                                return false;
                            }
                        }
                        return true;
                    };
                    const isInViewport = element => {
                        if (!isRendered(element)) return false;
                        const rect = element.getBoundingClientRect();
                        return rect.right > 0
                            && rect.bottom > 0
                            && rect.left < innerWidth
                            && rect.top < innerHeight;
                    };
                    const findActiveDrawer = () => {
                        // 选择、标记和控件查询必须发生在同一份 DOM 快照中。
                        // Portal 重绘后旧的 data-jujubit-active-drawer 会被清掉，
                        // 不会把数量/关闭/Checkout 点击发到隐藏副本。
                        document.querySelectorAll(`[${activeMarker}]`)
                            .forEach(element => element.removeAttribute(activeMarker));
                        const roots = [...document.querySelectorAll('.ccd.is-open')]
                            .filter(root => isInViewport(root))
                            .filter(root => [...root.querySelectorAll('.ccd-panel')]
                                .some(panel => isInViewport(panel)
                                    && Math.abs(
                                        panel.getBoundingClientRect().right - innerWidth
                                    ) <= 4));
                        if (roots.length !== 1) {
                            return {root: null, count: roots.length};
                        }
                        roots[0].setAttribute(activeMarker, 'true');
                        return {root: roots[0], count: 1};
                    };
                    let candidateNodes;
                    let drawerCount = null;
                    if (params.selector.includes(`[${activeMarker}]`)) {
                        const active = findActiveDrawer();
                        drawerCount = active.count;
                        const suffix = params.selector
                            .replace(`[${activeMarker}]`, '').trim();
                        candidateNodes = active.root
                            ? [...active.root.querySelectorAll(suffix)]
                            : [];
                    } else {
                        candidateNodes = [...document.querySelectorAll(params.selector)];
                    }
                    const matches = candidateNodes
                        .filter(isRendered)
                        .filter(element => !params.exactText
                            || normalize(element.textContent) === params.exactText);
                    if (matches.length !== 1) {
                        return {
                            ok: false,
                            matchCount: matches.length,
                            reason: drawerCount !== null && drawerCount !== 1
                                ? `活动购物车半屏数量为 ${drawerCount}`
                                : `匹配到 ${matches.length} 个可见控件`,
                        };
                    }
                    const element = matches[0];
                    if (element.disabled
                        || element.getAttribute('aria-disabled') === 'true') {
                        return {
                            ok: false,
                            matchCount: 1,
                            reason: '控件处于禁用状态',
                        };
                    }
                    const rect = element.getBoundingClientRect();
                    const centerX = rect.left + rect.width / 2;
                    const centerY = rect.top + rect.height / 2;
                    const centerInViewport = isInViewport(element)
                        && centerX >= 0
                        && centerY >= 0
                        && centerX < innerWidth
                        && centerY < innerHeight;
                    if (!centerInViewport) {
                        // 滚动事件可能同步触发 Portal 重绘，绝不能继续读取这个
                        // 旧 element 的坐标。返回后由 Python 在下一轮重新定位。
                        element.scrollIntoView({
                            block: 'center', inline: 'center', behavior: 'instant'
                        });
                        return {
                            ok: false,
                            matchCount: 1,
                            reacquire: true,
                            reason: '控件已滚动到视口，等待重新定位',
                        };
                    }
                    const x = Math.max(
                        0, Math.min(innerWidth - 1, centerX)
                    );
                    const y = Math.max(
                        0, Math.min(innerHeight - 1, centerY)
                    );
                    const hit = document.elementFromPoint(x, y);
                    if (!hit || (hit !== element && !element.contains(hit))) {
                        return {
                            ok: false,
                            matchCount: 1,
                            reason: '控件中心被其他元素遮挡',
                            blocker: hit
                                ? `${hit.tagName.toLowerCase()}.${hit.className || ''}`
                                : '未命中页面元素',
                        };
                    }
                    return {
                        ok: true,
                        matchCount: 1,
                        x,
                        y,
                        coarsePointer: matchMedia('(pointer: coarse)').matches,
                    };
                }""",
                    params,
                )
                # 0 个候选通常是 Portal 的短暂卸载；reacquire 则表示刚完成
                # 滚动，旧节点无论是否仍连接 DOM 都不得用于点击。
                should_reacquire = bool(target.get("reacquire")) or (
                    target.get("matchCount") == 0
                )
                if target.get("ok") or not should_reacquire:
                    break
                if acquisition_attempt < 20:
                    self.page.wait_for_timeout(100)
            if target.get("ok"):
                if target.get("coarsePointer"):
                    self.page.touchscreen.tap(target["x"], target["y"])
                else:
                    self.page.mouse.click(target["x"], target["y"])
        except PlaywrightError as error:
            if allow_navigation:
                # 站内导航可能在 evaluate 返回前销毁旧执行上下文。用一个很短的
                # 有界等待确认 URL 已离开原页面；未变化则保留原异常，不能误吞。
                try:
                    self.page.wait_for_function(
                        "beforeUrl => window.location.href !== beforeUrl",
                        arg=before_url,
                        timeout=2_000,
                    )
                    return
                except PlaywrightTimeoutError:
                    pass
            raise
        assert target.get("ok"), (
            f"{description}失败：{target.get('reason', '未知原因')}，"
            f"遮挡元素={target.get('blocker', '无')}"
        )

    def open_gallery(self) -> None:
        """切换到 Gallery，并确认当前生成结果区域可交互。"""
        self.home.close_popup_before_click()
        gallery = self.page.locator("button:visible").filter(
            has_text=re.compile(r"^Gallery$")
        ).first
        expect(gallery).to_be_visible()
        self.page.wait_for_function(
            """() => [...document.querySelectorAll('#jjb-create-canvas button')]
                .some(button => button.textContent.trim() === 'Gallery'
                    && !button.classList.contains('opacity-50')
                    && !button.disabled
                    && button.getAttribute('aria-disabled') !== 'true')""",
            timeout=30_000,
        )
        self._click_visible_control(
            "#jjb-create-canvas button",
            description="打开 Gallery",
            exact_text="Gallery",
        )
        expect(self._visible_button("2D")).to_be_visible()
        expect(self._visible_button("3D")).to_be_visible()

    def open_create(self) -> None:
        """切回 Create 面板，供无可复用 Gallery 资产时现场生成。"""
        self.home.close_popup_before_click()
        create = self.page.locator("#jjb-create-canvas").get_by_role(
            "button", name="Create", exact=True
        )
        expect(create).to_be_visible()
        self._click_visible_control(
            "#jjb-create-canvas button",
            description="打开 Create 面板",
            exact_text="Create",
        )
        expect(self.page.locator("main input[type=file]").first).to_be_attached()
        expect(
            self.page.get_by_role("button", name="Upload your picture", exact=True)
        ).to_be_visible()

    def add_current_model_to_cart(self) -> None:
        """当前 Gallery 模型只加购一次，并等待半屏购物车打开。"""
        self.home.close_popup_before_click()
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
            # 加购是 AJAX 写入；DOM 点击后仍严格等待 cart/add.js 和抽屉自然打开。
            self._click_visible_control(
                self.CREATOR_ACTION_BUTTON_SELECTOR,
                description="点击 Add to Cart",
                exact_text="Add to Cart",
            )
        response = response_info.value
        if response.status == 429:
            reason = "Gallery 加购时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"Gallery 加购接口失败：HTTP {response.status}"
        self._cart_mutated = True
        try:
            # 只等待页面产品代码自然创建并打开抽屉。不能调用 host.open()、点击 Header
            # 或伪造事件，否则会把「加购成功但未自动打开抽屉」这个真实缺陷掩盖掉。
            # 用页面上下文原子读取避开 H5 Portal 节点替换的瞬态。
            self._wait_for_drawer_open()
            expect(self.drawer).to_be_visible(timeout=5_000)
        except AssertionError as error:
            self._record_drawer_open_failure_evidence(add_button)
            cart = self.cart_json()
            drawer_state = self.page.evaluate(
                """() => {
                    const rendered = element => {
                        if (!element) return false;
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && Number(style.opacity || 1) > 0
                            && rect.width > 1
                            && rect.height > 1;
                    };
                    const roots = [...document.querySelectorAll('.ccd.is-open')];
                    const renderedRoots = roots.filter(rendered);
                    const activeRoots = renderedRoots.filter(root =>
                        [...root.querySelectorAll('.ccd-panel')].some(panel =>
                            rendered(panel)
                            && Math.abs(
                                panel.getBoundingClientRect().right - innerWidth
                            ) <= 4
                        )
                    );
                    // 与点击助手相同：仅当恰好一个根节点完成动画并贴齐视口时，
                    // 才把它作为“活动抽屉”诊断；绝不再读取第一个旧 Portal。
                    const drawer = activeRoots.length === 1 ? activeRoots[0] : null;
                    const host = drawer?.closest('custom-cart-drawer') || null;
                    const allButtons = [...document.querySelectorAll('button')]
                        .filter(button => (button.textContent || '').trim() === 'Add to Cart')
                        .filter(rendered);
                    const activeButtons = drawer
                        ? [...drawer.querySelectorAll('button')]
                            .filter(button => (button.textContent || '').trim() === 'Add to Cart')
                            .filter(rendered)
                        : [];
                    const button = activeButtons[0] || allButtons[0] || null;
                    return {
                        hostPresent: Boolean(host),
                        hostCount: document.querySelectorAll('custom-cart-drawer').length,
                        customElementRegistered: Boolean(
                            customElements.get('custom-cart-drawer')
                        ),
                        hostOpenState: host?.isOpen ?? null,
                        drawerCandidates: roots.length,
                        renderedDrawerCandidates: renderedRoots.length,
                        activeDrawerCount: activeRoots.length,
                        drawerOpen: Boolean(drawer?.classList.contains('is-open')),
                        drawerClass: drawer?.className || '',
                        addButtonCount: allButtons.length,
                        activeAddButtonCount: activeButtons.length,
                        addButtonBusy: button?.getAttribute('aria-busy') || '',
                        addButtonDisabled: Boolean(button?.disabled),
                    };
                }"""
            )
            raise AssertionError(
                "Gallery 加购接口已成功，但产品未在 30 秒内自动打开半屏购物车："
                f"cart.js item_count={cart.get('item_count', 0)}，"
                f"custom-cart-drawer 已注册={drawer_state['customElementRegistered']}，"
                f"host 已挂载={drawer_state['hostPresent']}（共 {drawer_state['hostCount']} 个），"
                f"host.isOpen={drawer_state['hostOpenState']}，"
                f"抽屉候选={drawer_state['drawerCandidates']}，"
                f"可见抽屉候选={drawer_state['renderedDrawerCandidates']}，"
                f"活动抽屉={drawer_state['activeDrawerCount']}，"
                f"抽屉已打开={drawer_state['drawerOpen']}，"
                f"抽屉 class={drawer_state['drawerClass']!r}，"
                f"Add to Cart 可见数={drawer_state['addButtonCount']}，"
                f"活动抽屉内按钮数={drawer_state['activeAddButtonCount']}，"
                f"Add to Cart aria-busy={drawer_state['addButtonBusy']!r}，"
                f"disabled={drawer_state['addButtonDisabled']}。"
                "请检查 Creator 加购后 openCartDrawer 的异步链路；"
                "测试不会通过脚本强制打开抽屉来掩盖该问题。"
            ) from error
        assert urlparse(self.page.url).path != "/cart", "Add to Cart 不应直接进入全屏购物车"

    def _record_drawer_open_failure_evidence(self, add_button) -> None:
        """给「加购成功但抽屉未开」标出仍在加载的真实按钮，供报告截图定位。"""
        try:
            add_button.scroll_into_view_if_needed()
            self.page.evaluate(
                """element => {
                    const old = document.getElementById('jujubit-test-evidence-label');
                    if (old) old.remove();
                    element.style.setProperty('outline', '5px solid #ff2d2d', 'important');
                    element.style.setProperty(
                        'background-color', 'rgba(255, 45, 45, 0.16)', 'important'
                    );
                    const rect = element.getBoundingClientRect();
                    const label = document.createElement('div');
                    label.id = 'jujubit-test-evidence-label';
                    label.textContent = '加购后抽屉未打开';
                    Object.assign(label.style, {
                        position: 'fixed', zIndex: '2147483646',
                        left: `${Math.max(8, Math.min(rect.left, window.innerWidth - 150))}px`,
                        top: `${Math.max(8, rect.top - 34)}px`, padding: '5px 9px',
                        background: '#ff2d2d', color: '#fff', borderRadius: '4px',
                        font: 'bold 13px/1.2 Arial, sans-serif', pointerEvents: 'none',
                    });
                    document.body.appendChild(label);
                    window.__jujubitTestEvidence = {
                        note: 'cart/add.js 成功且角标已更新，但 Add to Cart 仍在加载，半屏购物车未自动打开',
                        selector: 'button:visible (Add to Cart)', tag: 'button',
                        text: (element.innerText || 'Add to Cart').trim(),
                        attributes: {
                            disabled: String(Boolean(element.disabled)),
                            ariaBusy: element.getAttribute('aria-busy'),
                        },
                        box: {
                            x: Math.round(rect.left + window.scrollX),
                            y: Math.round(rect.top + window.scrollY),
                            width: Math.round(rect.width), height: Math.round(rect.height),
                        },
                    };
                }""",
                add_button,
            )
        except Exception:
            # 证据辅助逻辑不能覆盖原有业务失败结论。
            pass

    def assert_drawer_cart(self, quantity: int) -> None:
        """校验半屏购物车商品、金额、包邮与 Checkout 件数。"""
        expect(self.drawer).to_be_visible()
        expect(self.drawer.locator(".ccd-title")).to_have_text("Cart")
        expect(self.drawer.locator(".ccd-close")).to_be_visible()
        expect(self.drawer.locator(".ccd-item:visible")).to_have_count(1)
        self._assert_cart_image_loaded(
            root_selector=".ccd.is-open",
            item_selector=".ccd-item",
            image_selector=".ccd-item-img",
            description="半屏购物车",
            require_right_edge=True,
        )
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
        assert self._refresh_active_drawer(), "无法标记当前唯一活动购物车半屏"
        try:
            layout = self.page.evaluate(
                r"""() => {
                    const panel = document.querySelector(
                        '[data-jujubit-active-drawer] .ccd-panel'
                    );
                    if (!panel) return null;
                    const rect = panel.getBoundingClientRect();
                    const style = getComputedStyle(panel);
                    return {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        viewportWidth: innerWidth,
                        viewportHeight: innerHeight,
                        documentWidth: document.documentElement.clientWidth,
                        cssWidth: style.width,
                        cssMaxWidth: style.maxWidth,
                    };
                }"""
            )
        except PlaywrightError as error:
            raise AssertionError("无法读取当前可见半屏购物车的布局信息") from error

        assert layout, "无法取得当前可见购物车半屏面板的布局"
        viewport_width = float(layout["viewportWidth"])
        viewport_height = float(layout["viewportHeight"])
        # 移动端主题为了预留阴影或滚动条，面板视觉上可贴齐/略越过 CSS viewport
        # 的右边缘。只要用户可见的内容没有向左溢出、且尺寸不超过可视宽度的一个
        # 小像素容差，就属于正常 H5 布局，而非白屏或抽屉未打开。
        tolerance = 4

        def layout_assert(condition: bool, message: str) -> None:
            """把实际布局值附在错误中，避免报告只显示裸 AssertionError。"""
            assert condition, f"{message}；实际布局={layout}"

        layout_assert(
            -tolerance <= float(layout["x"]) < viewport_width,
            "购物车半屏左边缘不在视口内",
        )
        layout_assert(
            float(layout["width"]) > 1
            and float(layout["width"]) <= viewport_width + tolerance,
            "购物车半屏宽度超出视口",
        )
        layout_assert(
            float(layout["x"]) + float(layout["width"])
            <= viewport_width + tolerance,
            "购物车半屏右边缘超出视口",
        )
        layout_assert(
            float(layout["height"]) > 1
            and float(layout["height"]) <= viewport_height + tolerance,
            "购物车半屏高度超出视口",
        )

        # PC 的设计稿约为 450px；H5 抽屉采用宽屏抽屉样式，390px 视口下通常为
        # 350px，窄屏时允许按 95% 宽度收缩。宽度检查保留合理容差，避免 DPR/阴影
        # 的亚像素取整把已完整可见的购物车误报成失败。
        expected_width = 350 if platform == "h5" else 450
        if platform == "h5":
            # 线上 H5 的 CSS 为 ``width: 350px; max-width: 95%``。保留这个
            # 设计验收，但给 Chromium/DPR、滚动条和安全区足够容差；不能把
            # 完整可见的 350px 抽屉误报，也不能放宽到掩盖真实尺寸回归。
            expected_max_width = min(expected_width, viewport_width * 0.95)
            width_tolerance = 16
            lower_bound = max(1, expected_max_width - width_tolerance)
            upper_bound = min(viewport_width + tolerance, expected_max_width + width_tolerance)
            layout_assert(
                lower_bound <= float(layout["width"]) <= upper_bound,
                "H5 购物车半屏宽度不符合设计区间",
            )
        else:
            expected_max_width = min(expected_width, viewport_width * 0.95)
            width_tolerance = tolerance
            layout_assert(
                abs(float(layout["width"]) - expected_max_width) <= width_tolerance,
                "PC 购物车半屏宽度不符合预期",
            )

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
        self.home.close_popup_before_click()
        expected_quantity = (
            min(quantity, 100) if expected_quantity is None else expected_quantity
        )
        # H5 抽屉会在加购后的动画/重绘中替换 input；不要保留旧 Locator
        # 后直接 fill。先等待当前可见输入框稳定且可编辑，再发一次真实输入。
        self._wait_for_drawer_quantity_input()
        with self.page.expect_response(
            lambda response: "/cart/change.js" in response.url, timeout=30_000
        ) as response_info:
            self._pace_cart_request()
            quantity_input = self.drawer.locator(".ccd-qty-num")
            expect(quantity_input).to_be_visible(timeout=30_000)
            expect(quantity_input).to_be_editable(timeout=30_000)
            quantity_input.fill(str(quantity))
            quantity_input.press("Enter", no_wait_after=True)
        response = response_info.value
        if response.status == 429:
            reason = "修改购物车数量时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"修改购物车数量失败：HTTP {response.status}"
        actual_quantity = int(response.json().get("item_count", 0))
        assert actual_quantity == expected_quantity, (
            "修改购物车数量后服务端返回数量不一致："
            f"expected={expected_quantity}, actual={actual_quantity}"
        )
        if expected_quantity == 0:
            self.assert_empty_drawer()
        else:
            expect(self.drawer.locator(".ccd-checkout")).to_have_text(
                f"Checkout ({expected_quantity})", timeout=30_000
            )
            expect(quantity_input).to_have_value(str(expected_quantity))
            self.assert_header_badge(expected_quantity)
        return expected_quantity

    def _wait_for_drawer_quantity_input(self, timeout: int = 30_000) -> None:
        """等待当前抽屉的数量框完成一次重绘，避免 H5 在旧节点上输入。"""
        deadline = time.monotonic() + max(1, timeout) / 1_000
        last_reason = "未找到可编辑的数量输入框"
        while time.monotonic() < deadline:
            self._refresh_active_drawer()
            try:
                state = self.page.evaluate(
                    r"""() => {
                        const isRendered = element => {
                            const style = getComputedStyle(element);
                            const rect = element.getBoundingClientRect();
                            return style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && Number(style.opacity || 1) > 0
                                && rect.width > 1 && rect.height > 1;
                        };
                        const roots = [...document.querySelectorAll(
                            '[data-jujubit-active-drawer]'
                        )].filter(isRendered);
                        if (roots.length !== 1) {
                            return {ready: false, reason: `可见抽屉数量为 ${roots.length}`};
                        }
                        const input = roots[0].querySelector('.ccd-qty-num');
                        if (!input || !isRendered(input)) {
                            return {ready: false, reason: '当前抽屉未展示数量输入框'};
                        }
                        if (input.disabled || input.readOnly) {
                            return {ready: false, reason: '当前数量输入框不可编辑'};
                        }
                        return {ready: true};
                    }"""
                )
            except PlaywrightError:
                state = {"ready": False, "reason": "抽屉正在重绘"}
            if state and state.get("ready"):
                return
            last_reason = (state or {}).get("reason", last_reason)
            self.page.wait_for_timeout(150)
        raise AssertionError(f"数量输入框未在限定时间内稳定可编辑：{last_reason}")

    def click_drawer_quantity(self, action: str, expected_quantity: int) -> None:
        """点击加号/减号，并等待数量和汇总完成更新。"""
        assert action in {"increase", "decrease"}
        self.home.close_popup_before_click()
        button = self.drawer.locator(f'.ccd-qty-btn[data-action="{action}"]')
        expect(button).to_be_enabled()
        with self.page.expect_response(
            lambda response: "/cart/change.js" in response.url, timeout=30_000
        ) as response_info:
            self._pace_cart_request()
            self._click_visible_control(
                self._drawer_control_selector(
                    f'.ccd-qty-btn[data-action="{action}"]'
                ),
                description=f"点击购物车数量{action}按钮",
            )
        response = response_info.value
        if response.status == 429:
            reason = "点击购物车数量按钮时触发站点访问频控（HTTP 429）。"
            self._mark_rate_limited(reason)
            raise SiteRateLimitError(reason)
        assert response.ok, f"点击购物车数量按钮失败：HTTP {response.status}"
        actual_quantity = int(response.json().get("item_count", 0))
        assert actual_quantity == expected_quantity, (
            "点击数量按钮后服务端返回数量不一致："
            f"expected={expected_quantity}, actual={actual_quantity}"
        )
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
        self.home.close_popup_before_click()
        expect(self.drawer.locator(".ccd-close")).to_be_visible()
        self._click_visible_control(
            self._drawer_control_selector(".ccd-close"),
            description="关闭半屏购物车",
        )
        expect(self.drawer).not_to_be_visible()

    def drawer_snapshot(
        self, *, expected_quantity: Optional[int] = None
    ) -> CartSnapshot:
        """等待目标数量稳定后，读取半屏购物车同一帧中的可见数据。"""
        data = self._wait_for_drawer_snapshot_data(
            expected_quantity=expected_quantity
        )
        snapshot = CartSnapshot(
            title=self._normalized_text(data["title"]),
            variant=self._normalized_text(data["variant"]),
            quantity=int(data["quantity"]),
            subtotal=self._normalized_text(data["subtotal"]),
            shipping=self._shipping_text(data["shipping"]),
            image_url=data["imageUrl"],
        )
        # 数量更新会整体替换商品节点。先原子读取快照，再用可重定位的断言检查
        # 页面完整性，避免两轮逐字段读取刚好跨过重绘窗口。
        self.assert_drawer_cart(snapshot.quantity)
        return snapshot

    def _wait_for_drawer_snapshot_data(
        self,
        *,
        expected_quantity: Optional[int] = None,
        timeout: int = 30_000,
        stable_reads: int = 2,
    ) -> dict[str, Any]:
        """等待目标数量和汇总连续稳定，再返回一份原子 DOM 快照。"""
        attempts = max(1, timeout // 100 + 1)
        last_state: dict[str, Any] = {}
        previous_data: Optional[dict[str, Any]] = None
        stable_count = 0
        for attempt in range(attempts):
            # 每轮先重新确认活动根节点；Portal 替换后旧标记不会残留到新节点。
            self._refresh_active_drawer()
            state = self.page.evaluate(
                r"""() => {
                    const isRendered = element => {
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && Number(style.opacity || 1) > 0
                            && rect.width > 1
                            && rect.height > 1;
                    };
                    const roots = [...document.querySelectorAll(
                        '[data-jujubit-active-drawer]'
                    )].filter(isRendered);
                    if (roots.length !== 1) {
                        return {
                            ready: false,
                            reason: `可见半屏购物车数量为 ${roots.length}`,
                        };
                    }
                    const root = roots[0];
                    // custom-cart-drawer.updateCartUI() 会先将旧商品节点清空，
                    // 再异步把最新 cart.items 写回 .ccd-items。H5 在这段窗口内
                    // 抽屉仍保持打开且空态可见；这不是最终空车状态。只有在
                    // 服务端数量为非零时才等待商品节点恢复，避免把重绘瞬态当失败。
                    const items = [...root.querySelectorAll('.ccd-item')]
                        .filter(isRendered);
                    if (items.length !== 1) {
                        return {
                            ready: false,
                            reason: `可见商品数量为 ${items.length}`,
                        };
                    }
                    const item = items[0];
                    const text = (scope, selector) =>
                        (scope.querySelector(selector)?.innerText || '').trim();
                    const quantity = root.querySelector('.ccd-qty-num')?.value || '';
                    const image = item.querySelector('.ccd-item-img');
                    const data = {
                        title: text(item, '.ccd-item-title'),
                        variant: text(item, '.ccd-item-variant'),
                        quantity,
                        subtotal: text(root, '.ccd-subtotal-val'),
                        shipping: text(root, '.ccd-shipping-text'),
                        imageUrl: image?.getAttribute('src') || image?.currentSrc || '',
                    };
                    const missing = Object.entries(data)
                        .filter(([, value]) => !String(value || '').trim())
                        .map(([key]) => key);
                    if (!/^\d+$/.test(quantity)) missing.push('quantity');
                    if (missing.length) {
                        return {
                            ready: false,
                            reason: `字段尚未完成渲染：${[...new Set(missing)].join(', ')}`,
                        };
                    }
                    return {ready: true, ...data};
                }"""
            )
            last_state = state or {}
            if last_state.get("ready"):
                actual_quantity = int(last_state["quantity"])
                if (
                    expected_quantity is not None
                    and actual_quantity != expected_quantity
                ):
                    last_state["reason"] = (
                        f"数量尚未达到目标：期望 {expected_quantity}，"
                        f"实际 {actual_quantity}"
                    )
                    previous_data = None
                    stable_count = 0
                else:
                    current_data = {
                        key: last_state[key]
                        for key in (
                            "title",
                            "variant",
                            "quantity",
                            "subtotal",
                            "shipping",
                            "imageUrl",
                        )
                    }
                    if current_data == previous_data:
                        stable_count += 1
                    else:
                        previous_data = current_data
                        stable_count = 1
                    if stable_count >= max(1, stable_reads):
                        return last_state
                    last_state["reason"] = (
                        "购物车字段已完整，但尚未连续稳定："
                        f"{stable_count}/{max(1, stable_reads)}"
                    )
            else:
                previous_data = None
                stable_count = 0
            if attempt < attempts - 1:
                self.page.wait_for_timeout(100)
        expected_note = (
            f"，目标数量为 {expected_quantity}" if expected_quantity is not None else ""
        )
        raise AssertionError(
            f"半屏购物车重绘后未恢复稳定快照{expected_note}："
            f"{last_state.get('reason', '未返回可读状态')}"
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
        # 组件会保留一份 display:none 的旧商品节点用于过渡；空态应以可见商品、
        # 服务端数量和空态区域为准，不能把隐藏模板误判为仍有商品。
        expect(self.drawer.locator(".ccd-item:visible")).to_have_count(
            0, timeout=30_000
        )
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
        assert self._refresh_active_drawer(), "包邮边界校验前未找到唯一活动购物车半屏"
        result = self.page.evaluate(
            """total => {
                const root = document.querySelector('[data-jujubit-active-drawer]');
                if (!root) {
                    return {ok: false, reason: '活动购物车半屏已被重绘'};
                }
                const host = root.closest('custom-cart-drawer');
                if (!host) {
                    return {ok: false, reason: '活动半屏不属于 custom-cart-drawer'};
                }
                if (typeof host.updateShippingBar !== 'function') {
                    return {ok: false, reason: '购物车组件缺少 updateShippingBar()'};
                }
                host.cart = { ...(host.cart || {}), total_price: total };
                host.updateShippingBar();
                return {ok: true};
            }""",
            total_cents,
        )
        assert result and result.get("ok"), (
            "设置包邮边界数据失败："
            f"{(result or {}).get('reason', '页面未返回状态')}"
        )

    def assert_shipping_boundary(self, total_cents: int, timeout: int = 30_000) -> None:
        """从同一活动抽屉帧读取包邮文案与进度，并等待组件重绘完成。"""
        if total_cents < self.FREE_SHIPPING_THRESHOLD_CENTS:
            remaining = self.FREE_SHIPPING_THRESHOLD_CENTS - total_cents
            expected_text = (
                f"Add ${remaining / 100:.2f} more to enjoy Free Shipping"
            )
        else:
            expected_text = self.QUALIFIED_SHIPPING_COPY

        deadline = time.monotonic() + max(1, timeout) / 1_000
        last_state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            # H5 Portal 可能在 updateShippingBar() 后替换子节点。每轮重新标记
            # 活动根节点，并在一次 evaluate 中读取文案和 width，避免 Locator
            # 在 inner_text/evaluate 之间绑定到已经被移除的旧节点。
            self._refresh_active_drawer()
            try:
                state = self.page.evaluate(
                    r"""() => {
                        const root = document.querySelector(
                            '[data-jujubit-active-drawer]'
                        );
                        if (!root) {
                            return {ready: false, reason: '活动购物车半屏正在重绘'};
                        }
                        const textNode = root.querySelector('.ccd-shipping-text');
                        const fill = root.querySelector('.ccd-shipping-fill');
                        if (!textNode || !fill) {
                            return {ready: false, reason: '包邮文案或进度条尚未挂载'};
                        }
                        const text = (textNode.innerText || '')
                            .replace(/\u00a0/g, ' ')
                            .replace(/\s+/g, ' ')
                            .trim()
                            .replace(/^[🎉\s]+/u, '');
                        const width = Number.parseFloat(fill.style.width || '');
                        if (!text || !Number.isFinite(width)) {
                            return {ready: false, reason: '包邮状态尚未完成渲染'};
                        }
                        return {ready: true, text, width};
                    }"""
                )
            except PlaywrightError:
                state = {"ready": False, "reason": "包邮区域正在重绘"}
            last_state = state or {}
            if last_state.get("ready"):
                text = str(last_state.get("text", ""))
                width = float(last_state.get("width", -1))
                width_matches = (
                    0 <= width < 100
                    if total_cents < self.FREE_SHIPPING_THRESHOLD_CENTS
                    else abs(width - 100) <= 0.01
                )
                if text == expected_text and width_matches:
                    return
                last_state["reason"] = (
                    "包邮文案或进度尚未达到目标："
                    f"expected_text={expected_text!r}, actual_text={text!r}, "
                    f"actual_width={width}"
                )
            self.page.wait_for_timeout(100)

        raise AssertionError(
            "包邮临界状态未在限定时间内完成更新："
            f"total_cents={total_cents}，"
            f"{last_state.get('reason', '页面未返回可读状态')}"
        )

    def checkout_from_drawer(self) -> None:
        self._checkout(
            self.drawer.locator(".ccd-checkout"),
            "半屏购物车",
            selector=self._drawer_control_selector(".ccd-checkout"),
        )

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
        self._select_result_view("2D")
        expect(self._visible_result_view("2d")).to_be_visible(
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
        self.home.close_popup_before_click()
        expect(self.header_cart).to_be_visible()
        if expected_quantity is not None:
            self.assert_header_badge(expected_quantity)
        elif self.header_badge.count() and self.header_badge.is_visible():
            expect(self.header_badge).to_have_text(re.compile(r"^(?:[1-9]\d?|99\+)$"))
        self._pace_cart_request()
        # Header Cart 是按钮触发的站内导航；DOM 点击后再以 /cart URL 和全屏组件
        # 作为结果断言，避免 click 自身等待 scheduled navigation 时在 CI 假超时。
        self._click_visible_control(
            ".jjb-header__cart",
            description="点击 Header Cart",
            allow_navigation=True,
        )
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
        expect(self.full_cart.locator(".cc-item:visible")).to_have_count(1)
        self._assert_cart_image_loaded(
            root_selector="custom-cart .cc",
            item_selector=".cc-item",
            image_selector=".cc-item-img",
            description="全屏购物车",
        )
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
        self.home.close_popup_before_click()
        expect(close_button).to_be_visible()
        self._pace_cart_request()
        self._click_visible_control(
            "custom-cart .cc .cc-close",
            description="关闭全屏购物车",
            allow_navigation=True,
        )
        try:
            self.page.wait_for_function(
                "expectedPath => window.location.pathname === expectedPath",
                arg=expected_path,
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
        self._checkout(
            self.full_cart.locator(".cc-checkout"),
            "全屏购物车",
            selector="custom-cart .cc .cc-checkout",
        )

    def assert_checkout_summary(self, expected: CartSnapshot) -> None:
        """确认 Checkout 展示进入前的商品、数量和 Subtotal。"""
        assert self.CHECKOUT_URL.search(urlparse(self.page.url).path), (
            f"当前不是 Checkout 页面：{self.page.url}"
        )
        self.home.close_welcome_popup()
        main = self.page.locator("main:visible").first
        expect(main).to_be_visible(timeout=30_000)
        self._expand_checkout_summary(expected.title)
        self._wait_for_visible_exact_text(expected.title, timeout=30_000)
        body = self.page.locator("body")
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

    def _expand_checkout_summary(
        self, product_title: str, *, timeout: int = 10_000
    ) -> None:
        """移动端 Checkout 默认可能折叠订单摘要，存在开关时将其展开。"""
        attempts = max(1, timeout // 100 + 1)
        last_reason = "未找到订单摘要语义按钮"
        for attempt in range(attempts):
            # 已展开时不要再次点击，避免把可见摘要重新折叠。
            if self._visible_exact_text(product_title):
                return

            toggles = self.page.locator(self.CHECKOUT_SUMMARY_TOGGLE_SELECTOR)
            interactive_toggles = []
            for candidate in toggles.all():
                try:
                    state = self._checkout_toggle_state(candidate)
                except PlaywrightError:
                    # Checkout 首屏渲染可能替换响应式节点，下一轮重新获取。
                    continue
                if not state.get("controlsExists"):
                    last_reason = (
                        "Order summary 的 aria-controls 未指向有效摘要区域："
                        f"{state.get('controlsId') or '空'}"
                    )
                    continue
                if not state.get("rendered"):
                    last_reason = "Order summary 按钮尚未渲染"
                    continue
                if not state.get("inViewport"):
                    last_reason = "Order summary 按钮仍位于当前视口外"
                    continue
                if not state.get("hitTarget"):
                    last_reason = "Order summary 按钮中心被其他元素遮挡"
                    continue
                interactive_toggles.append((candidate, state))
            if len(interactive_toggles) > 1:
                raise AssertionError(
                    "Checkout 当前视口同时出现多个可操作的 Order summary 按钮，"
                    "无法安全展开"
                )
            if interactive_toggles:
                toggle, state = interactive_toggles[0]
                # 找到语义完整、未遮挡的真实按钮后最多点击一次；展开动画由后续
                # 标题等待确认，不能因响应式副本存在而重复点击。
                if state.get("expanded") != "true":
                    toggle.click(no_wait_after=True)
                return
            if attempt < attempts - 1:
                self.page.wait_for_timeout(100)
        raise AssertionError(f"Checkout 无法展开订单摘要：{last_reason}")

    @staticmethod
    def _checkout_toggle_state(toggle) -> dict[str, Any]:
        """读取摘要按钮的语义、视口位置和真实命中状态。"""
        return toggle.evaluate(
            """button => {
                const style = getComputedStyle(button);
                const rect = button.getBoundingClientRect();
                const controlsId = button.getAttribute('aria-controls') || '';
                const controlsExists = Boolean(
                    controlsId && document.getElementById(controlsId)
                );
                const rendered = style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && Number(style.opacity || 1) > 0
                    && rect.width > 1
                    && rect.height > 1;
                const left = Math.max(0, rect.left);
                const right = Math.min(innerWidth, rect.right);
                const top = Math.max(0, rect.top);
                const bottom = Math.min(innerHeight, rect.bottom);
                const inViewport = rendered && right > left && bottom > top;
                const hit = inViewport
                    ? document.elementFromPoint((left + right) / 2, (top + bottom) / 2)
                    : null;
                return {
                    controlsId,
                    controlsExists,
                    rendered,
                    inViewport,
                    hitTarget: Boolean(hit && (hit === button || button.contains(hit))),
                    expanded: button.getAttribute('aria-expanded') || '',
                };
            }"""
        )

    def _visible_exact_text(self, text: str):
        """返回完全匹配且当前可见的文本节点；隐藏的响应式副本不参与断言。"""
        for match in self.page.get_by_text(text, exact=True).all():
            try:
                if match.is_visible():
                    return match
            except PlaywrightError:
                # Checkout 展开动画可能替换节点，下一轮会重新获取最新 DOM。
                continue
        return None

    def _wait_for_visible_exact_text(self, text: str, *, timeout: int) -> None:
        """等待折叠动画结束并确认商品标题已真实展示给用户。"""
        deadline = time.monotonic() + max(0, timeout) / 1_000
        while time.monotonic() < deadline:
            if self._visible_exact_text(text):
                return
            self.page.wait_for_timeout(100)
        raise AssertionError(f"Checkout 商品摘要未显示商品标题：{text!r}")

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
                expect(self.drawer.locator(".ccd-item:visible")).to_have_count(0)
            else:
                quantity_input = self.drawer.locator(".ccd-qty-num")
                actual_value = quantity_input.input_value()
                if actual_value != str(expected_cart_quantity):
                    self._record_quantity_mismatch_evidence(
                        self.drawer.locator(".ccd-qty"),
                        selector=(
                            f"[{self.ACTIVE_DRAWER_ATTRIBUTE}] .ccd-qty"
                        ),
                        expected=expected_cart_quantity,
                        actual=actual_value,
                    )
                expect(quantity_input).to_have_value(str(expected_cart_quantity))
        if self.full_cart.is_visible():
            if expected_cart_quantity == 0:
                expect(self.full_cart.locator(".cc-item:visible")).to_have_count(0)
            else:
                quantity_input = self.full_cart.locator(".cc-qty-num")
                actual_value = quantity_input.input_value()
                if actual_value != str(expected_cart_quantity):
                    self._record_quantity_mismatch_evidence(
                        self.full_cart.locator(".cc-qty"),
                        selector="custom-cart .cc .cc-qty",
                        expected=expected_cart_quantity,
                        actual=actual_value,
                    )
                expect(quantity_input).to_have_value(str(expected_cart_quantity))

    def assert_failed_quantity_change_preserves_visible_state(
        self, before: CartSnapshot, *, expected_cart_quantity: int
    ) -> None:
        """失败请求后只校验用户可见业务状态，不读取隐藏加载控件的内部值。

        购物车组件在 ``cart/change.js`` 返回后可能先清空商品节点，再把原值
        写回 DOM。这里用同一帧的活动抽屉快照连续读取两次，避免逐个 Locator
        读取标题、金额、数量时跨过 H5 Portal 的重绘窗口而产生假失败。
        """
        self.assert_page_integrity()
        response_cart = self.cart_json()
        assert int(response_cart.get("item_count", 0)) == expected_cart_quantity, (
            "change 失败后服务端购物车数量被修改："
            f"expected={expected_cart_quantity}, actual={response_cart.get('item_count')}"
        )
        self.assert_header_badge(expected_cart_quantity)
        actual = self._wait_for_failed_change_snapshot(
            expected_quantity=expected_cart_quantity
        )
        actual_title = self._normalized_text(actual["title"])
        assert actual_title == before.title, (
            "change 失败后商品标题与失败前不一致："
            f"before={before.title!r}, actual={actual_title!r}"
        )
        # 规格的两个 div 在 innerText 中带换行；比较时忽略节点边界产生的空白，
        # 避免把同一可见文案误报。
        actual_variant = self._normalized_text(actual["variant"])
        actual_variant_key = self._text_without_whitespace(actual_variant)
        expected_variant_key = self._text_without_whitespace(before.variant)
        assert actual_variant_key == expected_variant_key, (
            "change 失败后商品规格与失败前不一致："
            f"before={before.variant!r}, actual={actual_variant!r}"
        )
        actual_subtotal = self._normalized_text(actual["subtotal"])
        assert actual_subtotal == before.subtotal, (
            "change 失败后 Subtotal 与失败前不一致："
            f"before={before.subtotal!r}, actual={actual_subtotal!r}"
        )
        actual_checkout = self._normalized_text(actual["checkout"])
        expected_checkout = f"Checkout ({expected_cart_quantity})"
        assert actual_checkout == expected_checkout, (
            "change 失败后 Checkout 件数与失败前不一致："
            f"expected={expected_checkout!r}, actual={actual_checkout!r}"
        )
        shipping_text = self._shipping_text(actual["shipping"])
        assert shipping_text == self.QUALIFIED_SHIPPING_COPY or self.SHIPPING_COPY.fullmatch(
            shipping_text
        ), f"change 失败后包邮提示不符合线上规则：{shipping_text!r}"
        assert shipping_text == before.shipping, (
            "change 失败后包邮提示与失败前不一致："
            f"before={before.shipping!r}, actual={shipping_text!r}"
        )
        assert str(actual["quantity"]) == str(expected_cart_quantity), (
            "change 失败后界面数量与失败前不一致："
            f"expected={expected_cart_quantity}, actual={actual['quantity']}"
        )
        actual_image_path = self._normalized_image_path(actual["imageUrl"])
        assert actual_image_path == self._normalized_image_path(
            before.image_url
        ), (
            "change 失败后商品图片发生变化："
            f"before={before.image_url!r}, actual={actual['imageUrl']!r}"
        )

    def _wait_for_failed_change_snapshot(
        self,
        *,
        expected_quantity: int,
        timeout: int = 30_000,
    ) -> dict[str, Any]:
        """原子读取失败请求后的活动抽屉，并等待字段跨两帧保持稳定。"""
        deadline = time.monotonic() + max(1, timeout) / 1_000
        previous: Optional[dict[str, Any]] = None
        stable_count = 0
        last_reason = "未找到活动购物车半屏"
        while time.monotonic() < deadline:
            self._refresh_active_drawer()
            try:
                state = self.page.evaluate(
                    r"""expected => {
                        const rendered = element => {
                            if (!element) return false;
                            const style = getComputedStyle(element);
                            const rect = element.getBoundingClientRect();
                            return style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && Number(style.opacity || 1) > 0
                                && rect.width > 1 && rect.height > 1;
                        };
                        const roots = [...document.querySelectorAll(
                            '[data-jujubit-active-drawer]'
                        )].filter(rendered);
                        if (roots.length !== 1) {
                            return {
                                ready: false,
                                reason: `活动购物车半屏数量为 ${roots.length}`,
                            };
                        }
                        const root = roots[0];
                        const items = [...root.querySelectorAll('.ccd-item')]
                            .filter(rendered);
                        if (items.length !== 1) {
                            return {
                                ready: false,
                                reason: `活动抽屉可见商品数量为 ${items.length}`,
                            };
                        }
                        const item = items[0];
                        const text = (scope, selector) =>
                            (scope.querySelector(selector)?.innerText || '')
                                .replace(/\u00a0/g, ' ')
                                .replace(/\s+/g, ' ')
                                .trim();
                        const image = item.querySelector('.ccd-item-img');
                        const quantity = root.querySelector('.ccd-qty-num')?.value || '';
                        const data = {
                            title: text(item, '.ccd-item-title'),
                            variant: text(item, '.ccd-item-variant'),
                            quantity,
                            subtotal: text(root, '.ccd-subtotal-val'),
                            shipping: text(root, '.ccd-shipping-text'),
                            checkout: text(root, '.ccd-checkout'),
                            imageUrl: image?.currentSrc
                                || image?.getAttribute('src') || '',
                            imageLoaded: Boolean(
                                image && image.complete && image.naturalWidth > 0
                            ),
                        };
                        const required = [
                            'title', 'variant', 'quantity', 'subtotal',
                            'shipping', 'checkout', 'imageUrl',
                        ];
                        const missing = required.filter(key =>
                            !String(data[key] || '').trim()
                        );
                        if (!/^\d+$/.test(quantity)) missing.push('quantity');
                        if (missing.length) {
                            return {
                                ready: false,
                                reason: `字段尚未完成渲染：${[...new Set(missing)].join(', ')}`,
                            };
                        }
                        if (Number(quantity) !== Number(expected)) {
                            return {
                                ready: false,
                                reason: `数量与服务端预期不一致：期望 ${expected}，实际 ${quantity}`,
                            };
                        }
                        return {ready: true, ...data};
                    }""",
                    expected_quantity,
                )
            except PlaywrightError:
                state = {"ready": False, "reason": "活动抽屉正在重绘"}
            if state and state.get("ready"):
                current = {
                    key: state[key]
                    for key in (
                        "title", "variant", "quantity", "subtotal",
                        "shipping", "checkout", "imageUrl", "imageLoaded",
                    )
                }
                if current == previous:
                    stable_count += 1
                else:
                    previous = current
                    stable_count = 1
                if stable_count >= 2:
                    if not current["imageLoaded"]:
                        last_reason = "商品图片节点存在但尚未完成加载"
                    else:
                        return state
                else:
                    last_reason = f"失败后字段尚未连续稳定：{stable_count}/2"
            else:
                previous = None
                stable_count = 0
                last_reason = (state or {}).get("reason", last_reason)
            self.page.wait_for_timeout(100)
        raise AssertionError(f"失败请求后的购物车状态未稳定：{last_reason}")

    def _record_quantity_mismatch_evidence(
        self, locator, *, selector: str, expected: int, actual: str
    ) -> None:
        """在失败截图中标出数量控件，并记录服务端与界面的差异。"""
        try:
            locator.scroll_into_view_if_needed()
            locator.evaluate(
                """(element, data) => {
                    const old = document.getElementById('jujubit-test-evidence-label');
                    if (old) old.remove();
                    element.style.setProperty('outline', '5px solid #ff2d2d', 'important');
                    element.style.setProperty(
                        'background-color', 'rgba(255, 45, 45, 0.16)', 'important'
                    );
                    const rect = element.getBoundingClientRect();
                    const label = document.createElement('div');
                    label.id = 'jujubit-test-evidence-label';
                    label.textContent = `数量错误：期望 ${data.expected}，实际 ${data.actual}`;
                    Object.assign(label.style, {
                        position: 'fixed', zIndex: '2147483646',
                        left: `${Math.max(8, Math.min(rect.left, innerWidth - 220))}px`,
                        top: `${Math.max(8, rect.top - 34)}px`, padding: '5px 9px',
                        background: '#ff2d2d', color: '#fff', borderRadius: '4px',
                        font: 'bold 13px/1.2 Arial, sans-serif', pointerEvents: 'none',
                    });
                    document.body.appendChild(label);
                    window.__jujubitTestEvidence = {
                        note: `服务端数量为 ${data.expected}，界面仍显示 ${data.actual}`,
                        selector: data.selector,
                        tag: element.tagName.toLowerCase(),
                        text: label.textContent,
                        attributes: {
                            expectedQuantity: String(data.expected),
                            actualQuantity: String(data.actual),
                            class: element.className || '',
                        },
                        box: {
                            x: Math.round(rect.left + scrollX),
                            y: Math.round(rect.top + scrollY),
                            width: Math.round(rect.width), height: Math.round(rect.height),
                        },
                    };
                }""",
                {"selector": selector, "expected": expected, "actual": actual},
            )
        except Exception:
            # 证据标注失败不能覆盖原始购物车一致性断言。
            pass

    def _checkout(self, button, source: str, *, selector: str) -> None:
        """从指定购物车入口进入 Checkout；有副作用的点击只执行一次。"""
        self.home.close_popup_before_click()
        expect(button).to_be_visible()
        expect(button).to_be_enabled()
        self._pace_cart_request()
        self._click_visible_control(
            selector,
            description=f"{source}点击 Checkout",
            allow_navigation=True,
        )
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
    def _text_without_whitespace(text: str) -> str:
        """忽略相邻 DOM 节点边界产生的空白，仅比较用户可见字符。"""
        return re.sub(r"\s+", "", text)

    @staticmethod
    def _normalized_image_path(image_url: str) -> str:
        """忽略 CDN 查询参数，比较同一生成图片的稳定路径。"""
        parsed = urlparse(image_url)
        return parsed.path or image_url.split("?", 1)[0]

    def _assert_cart_image_loaded(
        self,
        *,
        root_selector: str,
        item_selector: str,
        image_selector: str,
        description: str,
        require_right_edge: bool = False,
        timeout: int = 30_000,
    ) -> None:
        """从当前可见购物车的一帧 DOM 中确认唯一商品图片已真实加载。

        半屏购物车由 React Portal 渲染，更新时会替换根节点和临时活动标记。
        因此每轮都从 document 重新查询可见根、商品和图片，并在一次
        ``page.evaluate`` 中读取完整状态，避免复用旧 Locator 后继承默认
        10 秒动作等待。持续没有有效图片时仍会按总超时明确失败。
        """
        attempts = max(1, timeout // 150 + 1)
        last_reason = f"{description}图片尚未加载完成"
        params = {
            "rootSelector": root_selector,
            "itemSelector": item_selector,
            "imageSelector": image_selector,
            "requireRightEdge": require_right_edge,
        }
        for attempt in range(attempts):
            try:
                state = self.page.evaluate(
                    r"""params => {
                        const rendered = element => {
                            if (!element) return false;
                            const rect = element.getBoundingClientRect();
                            if (!(rect.width > 1 && rect.height > 1
                                && rect.right > 0 && rect.bottom > 0
                                && rect.left < innerWidth && rect.top < innerHeight)) {
                                return false;
                            }
                            for (let node = element; node; node = node.parentElement) {
                                const style = getComputedStyle(node);
                                if (style.display === 'none'
                                    || style.visibility === 'hidden'
                                    || Number(style.opacity || 1) <= 0.01) {
                                    return false;
                                }
                            }
                            return true;
                        };
                        const roots = [...document.querySelectorAll(params.rootSelector)]
                            .filter(rendered)
                            .filter(root => !params.requireRightEdge
                                || [...root.querySelectorAll('.ccd-panel')]
                                    .some(panel => rendered(panel)
                                        && Math.abs(
                                            panel.getBoundingClientRect().right - innerWidth
                                        ) <= 4));
                        if (roots.length !== 1) {
                            return {
                                ready: false,
                                ambiguous: roots.length > 1,
                                reason: `可操作购物车数量为 ${roots.length}`,
                            };
                        }
                        const items = [...roots[0].querySelectorAll(params.itemSelector)]
                            .filter(rendered);
                        if (items.length !== 1) {
                            return {
                                ready: false,
                                ambiguous: items.length > 1,
                                reason: `可见商品数量为 ${items.length}`,
                            };
                        }
                        const images = [...items[0].querySelectorAll(params.imageSelector)]
                            .filter(rendered);
                        if (images.length !== 1) {
                            return {
                                ready: false,
                                ambiguous: images.length > 1,
                                reason: `可见商品图片数量为 ${images.length}`,
                            };
                        }
                        const image = images[0];
                        const src = image.currentSrc || image.getAttribute('src') || '';
                        const complete = Boolean(image.complete);
                        const naturalWidth = Number(image.naturalWidth || 0);
                        if (!src.trim()) {
                            return {ready: false, reason: '商品图片地址为空'};
                        }
                        if (!complete || naturalWidth <= 0) {
                            return {
                                ready: false,
                                reason: `商品图片未完成加载：complete=${complete}, naturalWidth=${naturalWidth}`,
                            };
                        }
                        return {ready: true, src, complete, naturalWidth};
                    }""",
                    params,
                )
                if state and state.get("ready"):
                    return
            except PlaywrightError as error:
                state = {
                    "ready": False,
                    "reason": str(error).split("Call log:", 1)[0].strip()
                    or f"{description}正在重绘",
                }
            last_reason = (state or {}).get("reason", last_reason)
            if state and state.get("ambiguous"):
                raise AssertionError(
                    f"购物车中的生成图片无法唯一定位：{last_reason}"
                )
            if attempt < attempts - 1:
                self.page.wait_for_timeout(150)
        raise AssertionError(
            f"购物车中的生成图片未在限定时间内加载完成：{last_reason}"
        )
