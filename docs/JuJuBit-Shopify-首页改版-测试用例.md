# JuJuBit Shopify 首页改版测试用例

## 1. 测试范围与口径

- 依据：`Shopify 首页改版技术文档`、`JuJuBit Shopify 首页改版 PRD v1`。
- 终端口径：PC 为视口宽度 `> 768px`，H5 为 `<= 768px`；必须覆盖 768px 与 769px 边界。
- 优先级：P0 为发布阻断或核心转化；P1 为主要体验；P2 为增强、兼容和配置校验。
- 自动化标识：`UI` 适合 pytest + Playwright；`API` 适合接口/响应校验；`人工` 涉及 Theme Editor、视觉或分析平台。

## 2. 功能与交互用例

| 模块 | 优先级 | 场景与前置数据 | 操作 | 预期结果 | 自动化 |
|---|---|---|---|---|---|
| 页面基础 | P0 | 正常网络，访问首页 | 分别以 PC、H5 打开首页 | HTTP 200；无 404/500 文案；核心内容可见 | UI/API |
| 响应式 | P0 | 视口 768px、769px | 刷新并观察布局 | 768px 使用 H5 布局；769px 使用 PC 布局，无重叠或横向溢出 | UI |
| 公告栏 | P1 | 配置 1 至 5 条公告 | 等待自动切换 | 公告垂直轮播；前后按钮位置固定；页面无布局偏移 | UI |
| 公告栏 | P1 | 至少 2 条公告 | 点击上一条或下一条，再等待一个自动周期 | 立即切换到相邻公告；手动操作后停止自动轮播 | UI |
| 公告栏 | P1 | 公告为超长单行文本 | 观察一个完整滚动周期 | 不换行；跑马灯滚动；首尾各停顿约 500ms；内容不被永久截断 | UI/人工 |
| 公告栏 | P0 | 公告分别配置站内与站外链接 | 点击公告 | 站内链接正常；编辑端不能产生站外公告链接 | UI/人工 |
| 公告栏 | P1 | 分别配置 0、1、5、6 条 | 预览首页 | 0 条时区域合理隐藏；1/5 条正确展示；最多接收 5 条，超限有约束 | 人工 |
| Header | P0 | 默认配置 | 点击 Logo | Logo 链接到 `/`；图片 alt 或链接 aria-label 包含正确品牌名 `JuJuBit` | UI |
| Header | P0 | 默认导航 | 遍历 PC/H5 导航入口 | 仅展示一级和二级；所有入口为真实 `<a href>` 且目标有效 | UI |
| Header | P1 | 二级菜单含商品预览 | PC 悬停一级菜单，H5 展开菜单 | 商品图、名称、链接完整；键盘可操作；不出现第三级 | UI/人工 |
| Header | P0 | Create 链接已配置 | 点击 Create | 跳转产品定义的目标页且非 404；来源参数/埋点可识别 | UI |
| Hero | P0 | 同一 slide 同时配置图片和视频 | 打开首页 | 优先展示图片，视频不抢占播放或 LCP | UI/人工 |
| Hero | P0 | 分别只配置图片、视频、GIF | 打开首页 | 对应媒体正确渲染；PC/H5 使用各自媒体；无破图 | UI/人工 |
| Hero | P1 | 配置多个 slide | 等待轮播并点击圆点 | 自动切换且进度点同步；点击其他点后暂停；再次点击当前点恢复 | UI |
| Hero | P1 | 配置不同文案对齐 | PC/H5 检查左右/居中对齐 | 各端采用独立配置，文本和按钮不遮挡主体 | 人工 |
| Hero | P1 | 上传不符合建议比例的媒体 | PC/H5 打开首页 | PC 回退 16:9，H5 回退 4:5；裁切稳定且无 CLS | UI/人工 |
| Hero | P0 | slide 有标题 | 检查 DOM | 每个 slide 标题使用 H2；全页仍只有一个 H1 | UI |
| Hero | P1 | 按钮文案为空但媒体有链接 | 点击媒体 | 按钮隐藏；媒体整体仍可点击并到达配置链接 | UI/人工 |
| 模板入口 | P1 | 配置 3 条及以上卡片 | 自动轮播并连续切换 | 无限循环，无明显跳回和空白；卡片顺序正确 | UI |
| 模板入口 | P1 | 配置 0、1、2、3 条卡片 | 查看区域 | 少于 3 条时静态展示；3 条起启用轮播；0 条合理隐藏 | UI/人工 |
| 模板入口 | P1 | PC 与 H5 | PC hover/focus；H5 拖拽 | PC 暂停并在移出后恢复；H5 触摸拖拽期间暂停 | UI |
| 模板入口 | P0 | 卡片配置有效链接 | 键盘 Tab 并点击全部卡片 | 卡片为 `<a>`，可聚焦、可跳转、无空 href | UI |
| How It Works | P1 | 配置 1 至 5 步 | 首次进入区域 | 默认选中第一步，文字与对应图片一致 | UI |
| How It Works | P1 | PC | hover 第二步，点击第三步，再移开 | hover 临时预览第二步；点击后第三步保持选中 | UI |
| How It Works | P1 | H5 | 点击不同步骤 | 仅点击/触摸切换，不依赖 hover；图文同步 | UI |
| How It Works | P2 | 配置 0、5、6 步 | 预览首页 | 0 步不展示交互区；最多 5 步；超限受到约束 | 人工 |
| Showcase | P1 | 默认配置 | 检查 tab | 固定显示六个分类，名称、顺序符合需求 | UI |
| Showcase | P1 | 各分类有不同卡片 | 逐个切换 tab | 仅显示当前分类数据；整张卡片链接一致且可访问 | UI |
| Showcase | P2 | PC | hover 卡片 | 展示规定的信息层，不影响点击与键盘焦点 | UI/人工 |
| Showcase | P2 | 分别配置/不配置 View More | 查看并点击 | 有配置时展示并正确跳转；无配置时按钮隐藏且不留空位 | UI/人工 |
| Brand Highlights | P1 | H5，至少 3 项 | 横向滑动 | 可连续滑动，无页面误滚动；图标与文字不截断 | UI |
| Brand Highlights | P1 | SVG/icon font | 检查无障碍树 | 每个有意义图标有准确 aria-label，装饰图标不重复朗读 | UI |
| Reviews | P1 | 多条评价 | 等待、点击和滑动轮播 | 卡片轮播正常，顺序稳定，无空卡 | UI |
| Reviews | P1 | 星级含小数 | 查看星级 | 星级按需求规则四舍五入展示，数值和图形一致 | UI |
| Reviews | P1 | 评价超过两行 | PC/H5 查看 | 最多两行并显示省略号，不撑高卡片 | UI |
| Reviews | P1 | PC | 点击评价卡片，关闭弹窗 | 打开完整内容弹窗；焦点受控；Esc/关闭按钮有效 | UI |
| Reviews | P0 | 配置 make same 链接 | 点击入口 | 使用真实 `<a>` 并到达对应定制页 | UI |
| Reviews | P1 | `review_images` 含空格、空片段与全角分隔符 | 查看评价图片 | 按 `｜` 拆分、去首尾空格、忽略空项；图片顺序正确 | UI/人工 |
| Reviews | P1 | 日期跨 UTC 日期边界 | 查看日期 | 按 UTC 规则格式化，和源数据一致 | UI/人工 |
| Social | P1 | 多个视频 | 切换高亮视频 | 只有当前高亮视频播放，其余均暂停 | UI |
| Social | P0 | 视频已展示 | 检查 DOM 属性 | 视频具有 `muted`、`playsinline`、`loop` | UI |
| FAQ | P1 | 多分类、多问题 | PC 切分类；H5 切 tab | 当前分类突出显示；仅展示匹配分类的问题 | UI |
| FAQ | P1 | 同分类至少 2 项 | 依次展开两个 FAQ | 同一时间最多一项展开，答案与问题匹配 | UI |
| FAQ | P0 | 正常 FAQ | 检查 DOM | 使用 `<details><summary><h3>` 语义结构，可键盘操作 | UI |
| FAQ | P1 | FAQ 的 `category_id` 不存在 | 打开首页 | 不匹配项不展示，也不进入结构化数据 | UI/人工 |
| FAQ | P0 | 页面含 FAQ JSON-LD | 对比可见问题与 JSON-LD | 问题、答案和数量一致，无隐藏或过期条目 | UI |
| Footer | P0 | 默认配置 | 检查并点击本地化切换器 | 展示当前地区和币种；可展开至少两个选项并正常收起 | UI |
| Footer | P0 | 固定社交入口 | 遍历外链 | href 正确；新窗口外链包含 `noopener noreferrer` | UI |
| Trending | P1 | collection 有 1、15、16 个商品 | 查看首页 | 最多渲染 15 个，顺序与 collection 一致 | UI/人工 |
| Trending | P1 | 商品带 `new` tag | 查看卡片 | 显示 `NEW`；无 tag 商品不显示 | UI |
| Trending | P1 | PC 商品至少两张图 | hover 卡片 | 切换为第二张图，移出恢复且无布局跳动 | UI |
| Trending | P1 | PC/H5 | 鼠标拖拽/触摸滑动 | 水平浏览稳定，点击和拖拽不会互相误触 | UI |
| Category | P1 | 多分类卡片 | PC/H5 拖拽或滑动 | 可横向浏览；卡片不丢失、不重复 | UI |
| Category | P1 | 分别配置/不配置 CTA | 查看区域 | CTA 按配置显隐；有 CTA 时链接有效 | UI/人工 |
| Category | P1 | 多张分类图片 | 检查 alt | 每张图片 alt 唯一且描述对应分类，不使用文件名 | UI |
| 动态区块 | P0 | Theme Editor 中改变业务区块顺序 | 保存并访问前台 | 公告/Header/Footer 固定；Hero 始终为第一个业务区块；其他区块独立可排序 | 人工 |
| 动态区块 | P1 | 单独禁用任一业务区块 | 保存并访问前台 | 仅目标区块隐藏，其他区块和样式不受影响 | 人工 |

## 3. SEO、性能、可访问性与数据用例

| 模块 | 优先级 | 场景与操作 | 预期结果 | 自动化 |
|---|---|---|---|---|
| SEO | P0 | 获取首页 title | 精确为 `JuJuBit \| Custom Figurines, Crystal Bracelets & Art Toys` | UI/API |
| SEO | P0 | 获取 meta description | 精确为需求文案，不为空且仅一个 | UI/API |
| SEO | P0 | 检查 H1 | 全页唯一，文本为 `Create Your Own Custom Figurine From a Photo` | UI |
| SEO | P0 | 禁用 JavaScript 后请求首页 HTML | H1、导航、主要区块和链接存在于服务端 HTML | API |
| SEO | P1 | 检查 Organization、WebSite JSON-LD | JSON 可解析；名称、URL 等与可见内容同源一致 | UI/API |
| 链接 | P0 | 关闭优惠弹窗，读取并遍历首页实际配置的公告、Header、Hero、主要区块与 Footer 站内链接 | 每个实际 href 均非 404/5xx，响应正文不为空且无白屏；不预设固定路径 | UI/API |
| 链接 | P0 | 关闭优惠弹窗后，真实点击当前配置的 Create 导航与 Hero CTA | 跳转到配置目标；页面正文非空，无白屏或错误页 | UI |
| 性能 | P0 | 检查首个 Hero/LCP 图片 | 不含 `loading=lazy`；资源优先级合理 | UI |
| 性能 | P0 | 加载并记录布局偏移 | 图片具备 width/height 或 aspect-ratio；CLS `<= 0.1` | UI/性能工具 |
| 可访问性 | P0 | 键盘遍历 Header、轮播、tab、FAQ、弹窗 | 顺序合理；焦点可见；全部核心操作可完成 | UI/人工 |
| 可访问性 | P1 | 扫描图片替代文本与控件名称 | 功能图片有描述性 alt；装饰图空 alt；图标按钮有名称 | UI |
| 兼容性 | P1 | Chrome、Safari、Firefox 最新两个主版本 | 核心功能、视频、拖拽和布局一致，无阻断错误 | UI/人工 |
| 数据埋点 | P0 | 首次打开首页并滚动通过各区块 | 产生一次 PV；各区块曝光按规则去重，字段完整 | UI/分析平台 |
| 数据埋点 | P0 | 点击公告、导航、Hero CTA、模板卡、步骤、Category、Review、Social、FAQ、Footer | 各交互上报对应事件；元素、位置、目标、终端字段正确 | UI/分析平台 |
| 数据埋点 | P1 | 从不同来源进入并完成创建漏斗 | 漏斗可按来源拆分，来源参数贯穿后续步骤 | UI/分析平台 |
| 稳定性 | P1 | 慢网、图片失败、视频失败 | 文案和 CTA 仍可用；有占位/降级；无无限 loading 与大幅 CLS | UI/人工 |
| 安全 | P0 | 检查所有外链及可配置富文本 | 外链隔离 opener；不执行脚本 URL 或注入 HTML | UI/人工 |

## 4. 待确认疑点

1. 响应式断点存在冲突：技术文档规定 `768px` 使用 PC，而 PRD 和本用例原口径规定 `<= 768px` 使用 H5。需设计/产品确认后再固定自动化断言。
2. PRD/技术文档和文案都要求 Create 指向 `/pages/create`，当前线上及原自动化断言指向 `/products/customize-your-own`。需产品确认最终 URL，以及 Hero、Header、卡片是否统一。
3. 公告栏“点击箭头停止自动轮播”是永久停止到刷新，还是用户无操作一段时间后恢复，文档未定义。
4. Hero“点击同一圆点恢复”中的同一圆点，是当前已选圆点还是上次手动选择的圆点，需要明确状态机。
5. 星级“四舍五入”的精度未明确：整数、0.5 星还是其他步长。
6. FAQ JSON-LD 是否只包含当前 tab 可见问题，还是包含所有可切换分类中的前台可见问题，需要 SEO 确认。
7. 埋点事件名称、公共字段、曝光阈值、去重周期和验收环境尚未最终确定，暂不能形成稳定自动化断言。
8. PC/H5 独立媒体缺失一端配置时的回退优先级未明确。
9. “Hero 始终第一业务区块”与商家在 Theme Editor 中拖动 Hero 到其他位置时，系统应禁止拖动还是保存后强制纠正，需要明确。
10. Header Categories 当前已确认的核心入口为 Art Toys、FDM LAMPS、Crystal Bracelets、Keycaps、Photo Boards；线上还配置了 Keychains，不能因为额外入口而判错。
11. `review_images` 仅规定全角 `｜`；是否兼容半角 `|` 和历史逗号格式需确认。

## 5. 自动化实施分层

- 已有冒烟层：15 个场景按 PC/H5 参数化，共 30 条，覆盖加载、公告、Header、Hero、模板、步骤、分类和商品。
- 新增需求验收层：SEO 精确值、Logo 品牌名称、Hero LCP、实际配置链接、Footer、社交外链/视频、FAQ 语义与 Hero 标题层级。
- 配置层：Theme Editor 数量上限、动态排序、媒体优先级、空数据与异常数据，建议固定测试主题后再自动化。
- 分析层：待事件协议确定后，通过 Playwright 监听网络请求并断言事件名与 payload。

## 6. 本次需求补充（已确认）

本节根据首页技术文档、PRD、SEO 技术与设计实现要求、首页文案整理。已具备稳定前台验收条件的场景已加入 Playwright；标记为“人工/待确认”的项目仍需配置固定测试数据或确认口径后再自动化。

| 需求来源 | 补充场景 | 优先级 | 预期结果 | 自动化 |
|---|---|---|---|---|
| 文案/SEO | 首页元数据 | P0 | `title` 精确为 `JuJuBit \| Custom Figurines, Crystal Bracelets & Art Toys`；meta description 精确为 `JuJuBit makes custom figurines from your photo, crystal bracelets, and art toys. AI-assisted design, worldwide shipping. Turn your photo into a 3D collectible.`，且各仅一个 | UI/API |
| 文案/SEO | Hero 的页面主题 | P0 | 全页仅一个 H1，精确为 `Create Your Own Custom Figurine From a Photo`；H1 为 SSR HTML 真实文字，非图片叠字；每个 slide 标题为 H2 或普通文字 | UI/API |
| 技术文档 | Logo 无障碍文本 | P0 | Logo 图片 `alt` 精确为 `JuJuBit - Custom 3D Figurines`；Logo 链接到 `/` | UI |
| PRD/文案 | Header 入口及品类二级菜单 | P0 | Header 有真实文字 `<a>`；一级导航均可点击；Categories 至少包含当前配置的 Art Toys、FDM LAMPS、Crystal Bracelets、Keycaps、Photo Boards；额外的 Keychains 等入口不判错；不渲染三级菜单 | UI/API |
| 文案/PRD | Header URL 基准 | P0 | Create 使用主题实际配置的有效地址；Templates=`/collections/templates-create-your-own`，How It Works=`/pages/how-it-works`；当前品类链接分别为 `art-toy`、`fdm`、`crystal-bracelets`、`keycaps`、`photo-board` | UI/API |
| 技术文档/文案 | Hero 图片与 CTA | P0 | 首屏媒体优先加载且不使用 `loading=lazy`；产品图 alt 使用描述性文本，装饰背景 `alt=""`；CTA 为真实链接，默认文案 `Create Your Figurine`，并能打开主题实际配置的有效页面 | UI |
| PRD/文案 | Template Entry | P1 | 卡片名为 HTML 文字；每卡至少一个有意义的 `<a>`；默认风格入口可访问，查看全部链接至 `/collections/templates-create-your-own` | UI/API |
| PRD/文案 | How It Works 与 HowTo 数据源 | P0 | 四步标题及描述均在 SSR HTML 中可见；若输出 HowTo JSON-LD，Schema 步骤文本与页面对应字段逐字一致 | UI/API |
| PRD/文案 | Reviews 静态可抓取 | P1 | 推荐评价以静态 HTML 的文本和图片输出，不依赖 Judge.me JS widget；图片 alt 不包含 `cure`、`heal`、`medical` | UI/API |
| PRD/文案 | Social 静态层 | P1 | 静态引用包含真实文字、作者和描述；动态 embed 不作为唯一内容来源；社交外链带 `rel="noopener noreferrer"` | UI |
| PRD/文案 | Brand Highlights | P1 | 四个信任点为 HTML 真实文字且全量展示、不折叠；不使用未经确认的客户数或评分数字 | UI/人工 |
| PRD/文案 | FAQ 与 FAQPage | P0 | 所有 FAQ 问答均在原始 HTML 中；FAQPage `acceptedAnswer.text` 与页面答案同源一致；全部入口指向 `/pages/faqs` | UI/API |
| 文案 | Footer 社交项 | P1 | 当前配置的 Instagram、TikTok、YouTube、X 图标均有可被辅助技术读取的平台名称（`aria-label`、`title` 或 fallback 文本任一有效），链接匹配文案清单且外链隔离 opener；当前未配置的 Snapchat 不作为必需入口 | UI |
| PRD | Dynamic section 独立性 | P1 | Template、How It Works、Category、Reviews、Social、Brand Highlights、FAQ 可独立隐藏/排序/复用；任一调整不影响其他模块渲染 | 人工 |
| PRD | Hero 排序约束 | P0 | Hero 保持第一个业务 section；Announcement/Header/Footer 固定，不参与业务区块排序 | 人工 |
| PRD | 埋点最低字段 | P1 | section 曝光带 `section_handle` 和屏位；公告点击带活动 slug；导航、Hero、Template、Category、Review、Social、FAQ、Footer 点击带 PRD 指定业务字段 | UI/分析平台 |

### 6.1 补充详细用例

| 用例 ID | 模块 | 优先级 | 前置条件 | 操作步骤 | 预期结果 | 自动化 |
|---|---|---|---|---|---|---|
| HOME-SEO-001 | SSR | P0 | 首页可访问 | 使用不执行 JavaScript 的 HTTP 客户端获取首页原始 HTML | 状态码 200；原始 HTML 包含 title、meta description、唯一 H1、主导航、主要 section 标题和真实链接 | API |
| HOME-SEO-002 | H1 | P0 | Hero 配置多个 slide | 分别检查初始 DOM、轮播后 DOM及原始 HTML | 页面始终只有一个 H1，精确为 `Create Your Own Custom Figurine From a Photo`；slide 切换不新增或替换页面 H1 | UI/API |
| HOME-SEO-003 | JSON-LD | P0 | 页面输出结构化数据 | 遍历所有 `application/ld+json` 并解析 | JSON 均可解析；Organization、WebSite、FAQPage、HowTo 类型不重复、不使用空字段，URL 与当前正式域名一致 | UI/API |
| HOME-SEO-004 | 图片 alt | P1 | 首页所有业务图片已配置 | 收集所有 `img`，区分功能图和装饰图 | 功能图 alt 非空、不重复、不使用文件名；装饰图 alt 为空；所有 alt 不含医疗功效禁用词 | UI |
| HOME-HDR-001 | Header | P0 | 主菜单按文案配置 | PC 展开 Categories，H5 打开菜单，收集一级/二级入口 | 两端均包含规定入口；入口均为真实 `<a href>`；PC/H5 目标 URL 一致；无三级菜单节点 | UI |
| HOME-HDR-002 | Header | P0 | Categories 配置核心品类 | 逐个真实点击当前核心品类链接并记录落地 URL | Art Toys、FDM LAMPS、Crystal Bracelets、Keycaps、Photo Boards 展示名和目标集合匹配；均非 404/5xx；额外入口不判错 | UI/API |
| HOME-HDR-003 | Header | P1 | 导航中配置三级菜单 | PC hover、键盘展开及 H5 展开二级菜单 | 第三级不渲染；二级入口仍可聚焦、点击和关闭，布局无溢出 | UI/人工 |
| HOME-HERO-001 | Hero | P0 | 同一端同时配置图片和视频 | PC/H5 分别加载首页并监控媒体请求和可见元素 | 图片优先展示；视频不自动播放且不抢占 LCP；另一端的媒体不被错误展示 | UI |
| HOME-HERO-002 | Hero | P1 | PC 或 H5 仅配置一种媒体，另一端为空 | 分别以 769px、768px 加载 | 按最终确认的跨端回退规则展示；无破图、空白容器或重复媒体 | UI/待确认 |
| HOME-HERO-003 | Hero | P0 | 首个 slide 为图片 | 检查图片属性和 Performance 记录 | 首图不含 `loading=lazy`；具备尺寸或比例约束；为页面 LCP 候选且不因轮播发生明显 CLS | UI/性能工具 |
| HOME-HERO-004 | Hero | P1 | 至少两个 slide 且开启自动轮播 | 等待一个周期、点其他 dot、等待、再点当前 dot | 自动切换与进度同步；手动切换后暂停；再次点当前 dot 恢复且计时重新开始 | UI |
| HOME-TPL-001 | Template | P1 | 配置五个默认模板卡 | 校验卡片名、按钮和 href，逐个请求目标页 | Mini Pop、Cinematic、Realistic、TRPG、Two-Person 卡片为 HTML 文字；每卡至少一个有效锚点；目标页非错误页 | UI/API |
| HOME-TPL-002 | Template | P1 | 分别配置 0、1、2、3、20、21 张卡 | 在 Theme Editor 保存并预览 | 0 张合理隐藏；少于 3 张静态展示；3 张起轮播；最多 20 张；超限配置受到 schema 约束 | 人工 |
| HOME-HOW-001 | How It Works | P0 | 配置四个步骤和 HowTo Schema | 对比可见步骤与 JSON-LD `step` 数组 | 顺序、名称、描述和数量逐项一致；页面不只展示标题或图标；文字在原始 HTML 可见 | UI/API |
| HOME-HOW-002 | How It Works | P1 | 配置生产和物流时效文本 | 对比首页、HowTo Schema、FAQ 和 shipping policy | 生产、美国标准、国际标准和加急时效口径一致；任何一处缺失或冲突均失败 | API/人工 |
| HOME-REV-001 | Reviews | P1 | 禁用 Judge.me 脚本或拦截第三方请求 | 加载首页并检查评价区 | 评价文字、评分和图片仍存在于静态 HTML；核心内容不因第三方脚本失败而消失 | UI/API |
| HOME-REV-002 | Reviews | P1 | 评价图片和文本已配置 | 检查隐私、截断和弹窗 | 卡片不显示真实全名；两行截断仅影响视觉，完整文本可在弹窗读取；弹窗焦点与关闭行为正确 | UI/人工 |
| HOME-SOC-001 | Social | P1 | 配置静态引用和动态 embed | 拦截 Instagram/TikTok embed 后加载首页 | 静态引用、作者、描述和站外入口仍完整可见；页面无无限 loading 或空白占位 | UI |
| HOME-SOC-002 | Social | P0 | 配置当前四个平台入口 | 校验 href、可访问名称、target 和 rel | Instagram、TikTok、YouTube、X 的 URL 与文案清单一致；名称可被辅助技术读取；新窗口链接隔离 opener；不把当前未配置的 Snapchat 判为失败 | UI |
| HOME-FAQ-001 | FAQ | P0 | 配置 FAQ 并开启 Schema | 获取原始 HTML，展开每项并对比 JSON-LD | 当前配置的全部问答均在 SSR HTML；页面与 Schema 问题、答案、顺序和数量一致；答案不被截断 | UI/API |
| HOME-FAQ-002 | FAQ | P1 | 关闭 FAQPage Schema setting | 重新加载并检查结构化数据和交互 | 页面 FAQ 仍可见并可交互；FAQPage JSON-LD 不输出；其他 Schema 不受影响 | UI |
| HOME-DYN-001 | Dynamic section | P1 | 可编辑测试主题 | 逐个隐藏 Template、How It Works、Category、Reviews、Social、Brand Highlights、FAQ | 仅目标 section 消失；前后区块样式、间距、交互和 Schema 不残留、不报错 | 人工 |
| HOME-DYN-002 | Dynamic section | P0 | 可编辑测试主题 | 重排所有可动态 section 并尝试移动 Hero | 可动态 section 按保存顺序呈现且互不依赖；Hero 仍为第一个业务 section；固定 group 位置不变 | 人工 |
| HOME-DATA-001 | 埋点 | P1 | 测试环境启用埋点 | 依次触发曝光和所有核心点击，并捕获网络请求/dataLayer | 事件各产生一次；包含 PRD 指定业务字段、section、位置、终端和目标；无空关键字段 | UI/分析平台 |
| HOME-DATA-002 | 漏斗来源 | P1 | 可完成创建漏斗 | 分别从 Header、Hero、Template 进入并推进到加购 | 来源参数贯穿创建和加购步骤，可按入口拆分；刷新或站内跳转不被错误覆盖 | UI/分析平台 |

### 6.2 后续脚本实施建议

1. 先将 P0 项拆入 `test_home_requirements.py`：SSR 元数据/H1、链接、Hero LCP、FAQ Schema 以及 Header/Category URL。
2. 配置一个稳定的 Shopify 测试主题和测试数据后，再实现数量上限、空数据、排序和媒体优先级等配置层用例。
3. 数据团队确认事件协议、测试环境和曝光去重规则后，再监听网络请求实现埋点断言。
