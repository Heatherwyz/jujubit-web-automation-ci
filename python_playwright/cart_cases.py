"""购物车自动化用例清单的唯一结构化来源。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CartAutomationCase:
    """一条可被 pytest 收集、报告展示并生成文档的购物车用例。"""

    case_id: str
    test_function: str
    title: str
    priority: str
    precondition: str
    steps: str
    expected: str

    @property
    def report_title(self) -> str:
        return f"{self.case_id}: {self.title}"


CART_CASES = (
    CartAutomationCase(
        "CART-01",
        "test_cart_tc01_header_create_opens_creator",
        "首页 Header Create 可进入创作页",
        "P0",
        "JuJuBit 首页可访问。",
        "关闭优惠弹窗，点击 Header 左上角 Create。",
        "进入 /products/customize-your-own；创作组件挂载，上传框、Create、Gallery 和 Generate 控件存在。",
    ),
    CartAutomationCase(
        "CART-02",
        "test_cart_tc02_upload_result_has_2d_and_3d",
        "上传图片后 Gallery 展示本次 2D 与 3D 结果",
        "P0",
        "账号登录态有效且生成服务、账号配额可用。",
        "记录 History 数量，上传固定图片，只点击一次 Generate，等待本次任务完成。",
        "History 增加；2D 图片真实加载；3D renderer 完成并可在 2D/3D 间切换。",
    ),
    CartAutomationCase(
        "CART-03",
        "test_cart_tc03_gallery_add_opens_drawer",
        "Gallery 模型加购后打开半屏购物车",
        "P0",
        "账号 Gallery 中存在已完成且可购买的 2D/3D 资产。",
        "清空购物车，从 Gallery 点击 Add to Cart。",
        "cart/add.js 成功；仍停留创作页；半屏购物车展示商品、SKU、价格、数量 1 和 Checkout (1)。",
    ),
    CartAutomationCase(
        "CART-04",
        "test_cart_tc04_drawer_checkout_opens_checkout",
        "半屏购物车可进入 Checkout",
        "P0",
        "半屏购物车内有 1 件 Gallery 生成商品。",
        "记录购物车商品后点击半屏 Checkout。",
        "直接进入 /checkout 或 /checkouts/...；页面主体和当前商品摘要可见，不提交订单或支付。",
    ),
    CartAutomationCase(
        "CART-05",
        "test_cart_tc05_header_opens_full_cart",
        "Header Cart 可进入全屏购物车",
        "P0",
        "Gallery 商品已加购，半屏购物车内有 1 件商品。",
        "记录半屏数据并关闭半屏，点击右上角 Cart。",
        "进入 /cart；全屏购物车商品、数量、金额和包邮状态与半屏一致。",
    ),
    CartAutomationCase(
        "CART-06",
        "test_cart_tc06_full_cart_checkout_opens_checkout",
        "全屏购物车可进入 Checkout",
        "P0",
        "全屏购物车内有 Gallery 生成商品。",
        "点击全屏购物车 Checkout。",
        "进入 Checkout；页面主体和当前商品摘要可见，不提交订单或支付。",
    ),
    CartAutomationCase(
        "CART-07",
        "test_cart_tc07_header_badge_boundaries",
        "Cart 角标覆盖 0、1、99 与 100",
        "P0",
        "同一 SKU 可调整到 100 件。",
        "依次验证空车、加购 1 件、输入 99 件和输入 100 件。",
        "0 不显示角标；1 和 99 直显；100 显示 99+，且 Checkout 件数同步。",
    ),
    CartAutomationCase(
        "CART-08",
        "test_cart_tc08_drawer_and_full_cart_content",
        "半屏与全屏购物车核心内容完整",
        "P0",
        "购物车内有 1 件 Gallery 生成商品。",
        "分别检查半屏和全屏的标题、关闭入口、包邮区、商品卡、Subtotal、You Save 与 Checkout。",
        "实际线上文案和必需控件完整；优惠字段仅在有优惠时显示；两种视图数据一致。",
    ),
    CartAutomationCase(
        "CART-09",
        "test_cart_tc09_free_shipping_boundaries",
        "包邮金额覆盖 98.99、99.00 与 99.01 临界值",
        "P0",
        "购物车前端组件已加载。",
        "向线上购物车组件注入 9899、9900、9901 美分的可控 subtotal 并刷新包邮区。",
        "98.99 显示还差 $0.01；99.00 和 99.01 显示已获包邮；进度分别小于 100% 和等于 100%。",
    ),
    CartAutomationCase(
        "CART-10",
        "test_cart_tc10_quantity_buttons_update_totals",
        "数量加减后购物车汇总实时联动",
        "P0",
        "半屏购物车内同一 SKU 数量为 1。",
        "点击 + 到 2，再点击 - 回到 1。",
        "数量、角标、Subtotal、包邮提示和 Checkout (n) 同步；数量 1/2 时删除与减号图标正确切换。",
    ),
    CartAutomationCase(
        "CART-11",
        "test_cart_tc11_delete_last_item_shows_empty_cart",
        "删除最后商品后展示空购物车",
        "P0",
        "半屏购物车内只有 1 件商品。",
        "点击数量左侧垃圾桶删除最后一件商品。",
        "商品和角标消失；展示 Your Cart is Empty 与差额 $99.00；进度为 0，Checkout 禁用。",
    ),
    CartAutomationCase(
        "CART-12",
        "test_cart_tc12_quantity_input_caps_at_100",
        "数量输入上限为 100",
        "P0",
        "半屏购物车内有同一 SKU。",
        "数量框输入 101 并提交。",
        "数量自动回正 100；角标为 99+；Checkout (100)；加号不可用，H5 输入框使用数字输入属性。",
    ),
    CartAutomationCase(
        "CART-13",
        "test_cart_tc13_views_stay_consistent_and_full_cart_closes",
        "半屏与全屏数据一致且全屏 Close 正确返回",
        "P1",
        "从 Gallery 加购并将同一 SKU 调整为 2。",
        "记录半屏快照，关闭半屏后由 Header 进入全屏，再点击全屏 Close。",
        "两种视图的商品、SKU、数量、Subtotal 和包邮状态一致；Close 返回原 Gallery，商品不丢失。",
    ),
    CartAutomationCase(
        "CART-14",
        "test_cart_tc14_checkout_summary_matches_cart",
        "Checkout 订单摘要与购物车一致",
        "P0",
        "半屏购物车内同一 Gallery 商品数量为 2。",
        "记录商品、数量和 Subtotal 后进入 Checkout。",
        "Checkout 展示同一商品与数量，页面金额可见；不点击提交或支付按钮。",
    ),
    CartAutomationCase(
        "CART-15",
        "test_cart_tc15_failures_do_not_create_false_cart_state",
        "失败请求不产生假购物车状态或非法金额",
        "P1",
        "存在可复用 Gallery 资产；浏览器支持路由模拟。",
        "分别模拟 cart/add.js 与 cart/change.js 返回 500；change 用真实加号触发，并检查用户可见页面与服务端购物车。",
        "不出现假加购、白屏或 NaN/null 金额；商品、角标、Subtotal、包邮提示和 Checkout 件数保持失败前状态，服务端数据不被错误修改。",
    ),
)


CART_CASES_BY_FUNCTION = {case.test_function: case for case in CART_CASES}

# 每日回归在 H5 端只保留一组稳定且能覆盖主链路的关键用例。
# 这里使用业务 Case ID，而不是把函数名散落在运行脚本或 shell 的 ``-k``
# 表达式里；新增/改名时由结构化清单统一维护，pytest hook 再解析为函数名。
DAILY_H5_CASE_IDS = frozenset(
    {
        "CART-01",  # Header Create 入口
        "CART-02",  # 2D/3D 生成结果
        "CART-03",  # Gallery 加购与半屏购物车
        "CART-06",  # 全屏购物车 Checkout
        "CART-10",  # 数量与金额联动
        "CART-15",  # 失败请求状态保护
    }
)
DAILY_H5_CASE_FUNCTIONS = frozenset(
    case.test_function for case in CART_CASES if case.case_id in DAILY_H5_CASE_IDS
)
