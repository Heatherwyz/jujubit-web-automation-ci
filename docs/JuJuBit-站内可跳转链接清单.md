# JuJuBit 站内及外部可跳转链接清单

> 抓取日期：2026-08-19（Asia/Shanghai）
> 站点：<https://jujubit.ai/>
> 逻辑唯一固定链接：**191 条**

## 1. 抓取与去重说明

- 使用真实浏览器读取页面最终 DOM 中的 `a[href]`，共检查 14 个页面入口。
- “页面唯一链接”按当前页面的最终绝对地址去重；“逻辑唯一固定链接”再跨页面去重，公共 Header、Mega Menu、Footer 只在首页首次列出。
- 同一路径在不同区域出现多次时只保留一行，链接文字合并取代表性文字；可见性为“该页面至少有一个同目的地链接当前可见”。
- Shopify Account 地址已移除临时 `buyer_flags`，统一记录为 `https://shopify.com/95408849267/account`。
- `javascript:void(0);` 是非跳转占位，已排除，不计入 191 条固定链接。
- 当前表格共列 191 个固定目的地，其中站内页面/媒体 182 个，站外网站、账户或邮件入口 9 个。
- Checkout、语言/币种/地区切换属于运行时操作：Checkout 由购物车状态生成 `/checkout` 或 `/checkouts/...`；切换器通过表单/脚本提交，均不伪造固定 URL。
- 本清单是“已抓取页面 DOM 中实际存在的链接”，不是 Shopify sitemap 全量商品目录。分页第二页、登录后页面、弹窗交互后动态加载内容和结账会话地址不在固定链接统计中。

## 2. 页面抓取统计

| 页面 | 最终地址 | DOM 唯一 href | 页面逻辑唯一 href | 当前可见 href |
| --- | --- | ---: | ---: | ---: |
| 首页 | [https://jujubit.ai/](https://jujubit.ai/) | 95 | 94 | 67 |
| 购物车 | [https://jujubit.ai/cart](https://jujubit.ai/cart) | 80 | 80 | 48 |
| 创作/生成页 | [https://jujubit.ai/products/customize-your-own?variant=62485711716723](https://jujubit.ai/products/customize-your-own?variant=62485711716723) | 91 | 89 | 59 |
| 集合总览页 | [https://jujubit.ai/collections](https://jujubit.ai/collections) | 104 | 103 | 73 |
| 模板集合页 | [https://jujubit.ai/collections/templates-create-your-own](https://jujubit.ai/collections/templates-create-your-own) | 93 | 92 | 62 |
| How It Works | [https://jujubit.ai/pages/how-it-works](https://jujubit.ai/pages/how-it-works) | 73 | 72 | 42 |
| Tracking | [https://jujubit.ai/pages/tracking](https://jujubit.ai/pages/tracking) | 73 | 72 | 42 |
| Contact Us | [https://jujubit.ai/pages/contact](https://jujubit.ai/pages/contact) | 75 | 74 | 44 |
| FAQs | [https://jujubit.ai/pages/faqs](https://jujubit.ai/pages/faqs) | 74 | 73 | 42 |
| Refund & Exchange Policy | [https://jujubit.ai/pages/refund-exchange-policy](https://jujubit.ai/pages/refund-exchange-policy) | 73 | 72 | 42 |
| About Us | [https://jujubit.ai/pages/about-us](https://jujubit.ai/pages/about-us) | 73 | 72 | 42 |
| Join Us | [https://jujubit.ai/pages/join-us](https://jujubit.ai/pages/join-us) | 72 | 71 | 43 |
| 搜索页 | [https://jujubit.ai/search](https://jujubit.ai/search) | 71 | 70 | 42 |
| 会员页 | [https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart](https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart) | 71 | 71 | 42 |

## 3. 首页

页面：<https://jujubit.ai/>

公共 Header、Mega Menu 和 Footer 在本节完整列出。后续页面继承这些链接，后续章节只列该页面新增的目的地。

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/#MainContent](https://jujubit.ai/#MainContent) | 页面内锚点 | 可见 |
| 2 | 公告栏 | Create Your Own Design — Get 15% OFF / Create | [https://jujubit.ai/products/customize-your-own](https://jujubit.ai/products/customize-your-own) | 站内链接 | 可见 |
| 3 | 语言/地区/首页入口 | 首页 Logo；语言/地区选择器的当前页地址 | [https://jujubit.ai/](https://jujubit.ai/) | 站内链接 | 可见 |
| 4 | 公共 Header / Mega Menu | Templates / Trending | [https://jujubit.ai/collections/templates-create-your-own](https://jujubit.ai/collections/templates-create-your-own) | 站内链接 | 可见 |
| 5 | 公共 Header / Mega Menu | New / NEW | [https://jujubit.ai/collections/%F0%9F%94%A5-new](https://jujubit.ai/collections/%F0%9F%94%A5-new) | 站内链接 | 可见 |
| 6 | 公共 Header / Mega Menu | TRPG | [https://jujubit.ai/collections/trpg-pod](https://jujubit.ai/collections/trpg-pod) | 站内链接 | 可见 |
| 7 | 公共 Header / Mega Menu | CHIBI | [https://jujubit.ai/collections/chibi](https://jujubit.ai/collections/chibi) | 站内链接 | 可见 |
| 8 | 公共 Header / Mega Menu | Occasions / OCCASIONS | [https://jujubit.ai/collections/occasions-pod](https://jujubit.ai/collections/occasions-pod) | 站内链接 | 可见 |
| 9 | 公共 Header / Mega Menu | More services / MORE SERVICES | [https://jujubit.ai/collections/more-service](https://jujubit.ai/collections/more-service) | 站内链接 | 可见 |
| 10 | 公共 Header / Mega Menu | Categories / View All | [https://jujubit.ai/collections](https://jujubit.ai/collections) | 站内链接 | 可见 |
| 11 | 公共 Header / Mega Menu | Figurines / FIGURINES | [https://jujubit.ai/collections/art-toy](https://jujubit.ai/collections/art-toy) | 站内链接 | 可见 |
| 12 | 公共 Header / Mega Menu | Keychains / KEYCHAINS | [https://jujubit.ai/collections/keychain-pod](https://jujubit.ai/collections/keychain-pod) | 站内链接 | 可见 |
| 13 | 公共 Header / Mega Menu | FDM LAMPS / EXPLORE | [https://jujubit.ai/collections/fdm](https://jujubit.ai/collections/fdm) | 站内链接 | 可见 |
| 14 | 公共 Header / Mega Menu | Crystal Bracelets / CRYSTAL BRACELETS | [https://jujubit.ai/collections/crystal-bracelets](https://jujubit.ai/collections/crystal-bracelets) | 站内链接 | 可见 |
| 15 | 公共 Header / Mega Menu | Keycaps / KEYCAPS | [https://jujubit.ai/collections/keycaps](https://jujubit.ai/collections/keycaps) | 站内链接 | 可见 |
| 16 | 公共 Header / Mega Menu | Photo Boards / PHOTO BOARDS | [https://jujubit.ai/collections/photo-board](https://jujubit.ai/collections/photo-board) | 站内链接 | 可见 |
| 17 | 公共 Header / Mega Menu | How It Works / View All | [https://jujubit.ai/pages/how-it-works](https://jujubit.ai/pages/how-it-works) | 站内链接 | 可见 |
| 18 | 公共 Header / Mega Menu | Tracking / TRACKING | [https://jujubit.ai/pages/tracking](https://jujubit.ai/pages/tracking) | 站内链接 | 可见 |
| 19 | 公共 Header / Mega Menu | Contact Us / CONTACT US | [https://jujubit.ai/pages/contact](https://jujubit.ai/pages/contact) | 站内链接 | 可见 |
| 20 | 公共 Header / Mega Menu | FAQs / FAQS | [https://jujubit.ai/pages/faqs](https://jujubit.ai/pages/faqs) | 站内链接 | 可见 |
| 21 | 公共 Header / Mega Menu | Refund & Exchange Policy / REFUND & EXCHANGE POLICY | [https://jujubit.ai/pages/refund-exchange-policy](https://jujubit.ai/pages/refund-exchange-policy) | 站内链接 | 可见 |
| 22 | 公共 Header / Mega Menu | About Us | [https://jujubit.ai/pages/about-us](https://jujubit.ai/pages/about-us) | 站内链接 | 可见 |
| 23 | 公共 Header / Mega Menu | Join Us / JOIN US | [https://jujubit.ai/pages/join-us](https://jujubit.ai/pages/join-us) | 站内链接 | 可见 |
| 24 | 商品变体入口 | JuJuBit Customized Figurine-Create Your Own | [https://jujubit.ai/products/customize-your-own?variant=62418107728243](https://jujubit.ai/products/customize-your-own?variant=62418107728243) | 站内链接 | DOM 中存在，当前未显示 |
| 25 | 商品变体入口 | JuJuBit Customized Figurine-Create Your Own | [https://jujubit.ai/products/customize-your-own?variant=62485711716723](https://jujubit.ai/products/customize-your-own?variant=62485711716723) | 站内链接 | DOM 中存在，当前未显示 |
| 26 | 公共 Header / Mega Menu | 账户入口（运行时 buyer_flags 已移除） | [https://shopify.com/95408849267/account](https://shopify.com/95408849267/account) | 外部账户 | 可见 |
| 27 | 公共 Header / Mega Menu | Custom Figurine of Yourself \| Turn Your Photo into a 3D Printed Figure $29.99 | [https://jujubit.ai/products/custom-figurine-of-yourself](https://jujubit.ai/products/custom-figurine-of-yourself) | 站内链接 | 可见 |
| 28 | 公共 Header / Mega Menu | Custom TRPG Miniature – Create Your Own Tabletop RPG Character Figure $29.99 / Create Now | [https://jujubit.ai/products/custom-trpg-miniature-create-your-own-tabletop-rpg-character-figure](https://jujubit.ai/products/custom-trpg-miniature-create-your-own-tabletop-rpg-character-figure) | 站内链接 | 可见 |
| 29 | 公共 Header / Mega Menu | Custom Special Force Figurine \| Turn Yourself into a special force soldier $69.99 | [https://jujubit.ai/products/custom-special-force-figurine-turn-yourself-into-a-3d-secret-agent](https://jujubit.ai/products/custom-special-force-figurine-turn-yourself-into-a-3d-secret-agent) | 站内链接 | DOM 中存在，当前未显示 |
| 30 | 公共 Header / Mega Menu | Custom Voxel Figurine \| Turn Yourself into a 3D Pixelated character $49.99 | [https://jujubit.ai/products/custom-voxel-figurine-turn-yourself-into-a-3d-pixelated-character](https://jujubit.ai/products/custom-voxel-figurine-turn-yourself-into-a-3d-pixelated-character) | 站内链接 | DOM 中存在，当前未显示 |
| 31 | 公共 Header / Mega Menu | Custom Cowboy & Cowgirl Figurine \| Personalized Your Western American Stylish Avatar $69.99 | [https://jujubit.ai/products/custom-cowboy-cowgirl-figurine-personalized-your-western-american-stylish-avatar](https://jujubit.ai/products/custom-cowboy-cowgirl-figurine-personalized-your-western-american-stylish-avatar) | 站内链接 | DOM 中存在，当前未显示 |
| 32 | 公共 Header / Mega Menu | Custom TRPG Character Miniature \| Create Your Own Tabletop RPG Hero $29.99 | [https://jujubit.ai/products/custom-trpg-miniature-create-your-own-trpg-hero-figure](https://jujubit.ai/products/custom-trpg-miniature-create-your-own-trpg-hero-figure) | 站内链接 | DOM 中存在，当前未显示 |
| 33 | 公共 Header / Mega Menu | Custom TRPG Creature Miniature \| Create Your Own Monster, Familiar or Boss Figure $29.99 / More Workflow | [https://jujubit.ai/products/custom-trpg-creature-miniature-create-your-own-monster-familiar-or-boss-figure](https://jujubit.ai/products/custom-trpg-creature-miniature-create-your-own-monster-familiar-or-boss-figure) | 站内链接 | 可见 |
| 34 | 公共 Header / Mega Menu | Custom Classic Chibi Figurine \| Turn Your Photo into a Collectible Mini Figure $29.99 | [https://jujubit.ai/products/custom-classic-chibi-figurine](https://jujubit.ai/products/custom-classic-chibi-figurine) | 站内链接 | DOM 中存在，当前未显示 |
| 35 | 公共 Header / Mega Menu | Custom Soft Chibi Figurine \| Turn Your Memories into a Collectible 3D Figure $29.99 | [https://jujubit.ai/products/custom-soft-chibi-figurine](https://jujubit.ai/products/custom-soft-chibi-figurine) | 站内链接 | DOM 中存在，当前未显示 |
| 36 | 公共 Header / Mega Menu | Personalized Mini Pop Couple Figure \| Custom Two-Person Collectible $59.99 | [https://jujubit.ai/products/personalized-mini-pop-couple-figure-custom-two-person-collectible](https://jujubit.ai/products/personalized-mini-pop-couple-figure-custom-two-person-collectible) | 站内链接 | DOM 中存在，当前未显示 |
| 37 | 公共 Header / Mega Menu | Pet Season Special \| Custom Realistic 3D Figurine for Your Beloved Pet $29.99 | [https://jujubit.ai/products/custom-realistic-figurine-create-3d-figurine-for-your-beloved-pet](https://jujubit.ai/products/custom-realistic-figurine-create-3d-figurine-for-your-beloved-pet) | 站内链接 | DOM 中存在，当前未显示 |
| 38 | 公共 Header / Mega Menu | Parent & Child Custom Figurine \| Turn Family Love Into a 3D Collectible $29.99 | [https://jujubit.ai/products/parent-child-custom-figurine-turn-family-love-into-a-3d-collectible](https://jujubit.ai/products/parent-child-custom-figurine-turn-family-love-into-a-3d-collectible) | 站内链接 | DOM 中存在，当前未显示 |
| 39 | 公共 Header / Mega Menu | 3D Model Services \| Download $7.99 $12.99 | [https://jujubit.ai/products/3d-model-services-download](https://jujubit.ai/products/3d-model-services-download) | 站内链接 | DOM 中存在，当前未显示 |
| 40 | 公共 Header / Mega Menu | 3D Model Services \| Customize, Refine & Download $15.99 $29.99 | [https://jujubit.ai/products/3d-model-services-customize-refine-download](https://jujubit.ai/products/3d-model-services-customize-refine-download) | 站内链接 | DOM 中存在，当前未显示 |
| 41 | 公共 Header / Mega Menu | 3D Model Services \| Customize $34.00 | [https://jujubit.ai/products/3d-model-services-customize](https://jujubit.ai/products/3d-model-services-customize) | 站内链接 | DOM 中存在，当前未显示 |
| 42 | 公共 Header / Mega Menu | Mini Pop! Fashion - Sunny Bloom Belle $24.99 | [https://jujubit.ai/products/mini-pop-fashion-sunny-bloom-belle](https://jujubit.ai/products/mini-pop-fashion-sunny-bloom-belle) | 站内链接 | 可见 |
| 43 | 公共 Header / Mega Menu | LUMI — JuJuBit Collectible Art Toy for Gifting, Desk Decor & Display $24.99 $29.99 | [https://jujubit.ai/products/lumi-jujubit-collectible-art-toy-for-gifting-desk-decor-display](https://jujubit.ai/products/lumi-jujubit-collectible-art-toy-for-gifting-desk-decor-display) | 站内链接 | 可见 |
| 44 | 公共 Header / Mega Menu | Venus WAWA — JuJuBit Collectible Art Toy for Gifting, Desk Decor & Display $59.99 | [https://jujubit.ai/products/jujubit-figurine-customizable-collectible-art-toy-venus-wawa](https://jujubit.ai/products/jujubit-figurine-customizable-collectible-art-toy-venus-wawa) | 站内链接 | 可见 |
| 45 | 公共 Header / Mega Menu | Custom Classic Chibi Head Keychain \| Turn Your Character into a Cute Keepsake $45.00 | [https://jujubit.ai/products/custom-classic-chibi-keychain](https://jujubit.ai/products/custom-classic-chibi-keychain) | 站内链接 | DOM 中存在，当前未显示 |
| 46 | 公共 Header / Mega Menu | Custom Soft Chibi Head Keychain \| Carry Your Favorite Face Everywhere $45.00 | [https://jujubit.ai/products/custom-soft-chibi-head-keychain](https://jujubit.ai/products/custom-soft-chibi-head-keychain) | 站内链接 | DOM 中存在，当前未显示 |
| 47 | 公共 Header / Mega Menu | Sakura Neko \|Classic Chibi Keychain $45.00 | [https://jujubit.ai/products/sakura-neko-classic-chibi-keychain-1](https://jujubit.ai/products/sakura-neko-classic-chibi-keychain-1) | 站内链接 | DOM 中存在，当前未显示 |
| 48 | 公共 Header / Mega Menu | Custom Pet Night Light – Turn Your Photo Into Light $129.99 | [https://jujubit.ai/products/custom-pet-night-light-turn-your-photo-into-light](https://jujubit.ai/products/custom-pet-night-light-turn-your-photo-into-light) | 站内链接 | DOM 中存在，当前未显示 |
| 49 | 公共 Header / Mega Menu | Dalmatian Ambient Light｜JuJuBit FDM 3D Printed Night Light for Kids Room & Desk $89.99 | [https://jujubit.ai/products/dottyglow%E2%84%A2-dalmatian-ambient-lamp](https://jujubit.ai/products/dottyglow%E2%84%A2-dalmatian-ambient-lamp) | 站内链接 | DOM 中存在，当前未显示 |
| 50 | 公共 Header / Mega Menu | Horse Head Ambient Light｜JuJuBit FDM 3D Printed Night Light for Office & Shelf $89.99 | [https://jujubit.ai/products/horse-head-ambient-light-jujubit-fdm-3d-printed-night-light-for-office-shelf](https://jujubit.ai/products/horse-head-ambient-light-jujubit-fdm-3d-printed-night-light-for-office-shelf) | 站内链接 | DOM 中存在，当前未显示 |
| 51 | 公共 Header / Mega Menu | JuJuBit Lavender Amethyst — Serenity & Inner Peace Energy $20.99 $29.99 | [https://jujubit.ai/products/jujubit-lavender-amethyst-serenity-inner-peace-energy](https://jujubit.ai/products/jujubit-lavender-amethyst-serenity-inner-peace-energy) | 站内链接 | DOM 中存在，当前未显示 |
| 52 | 公共 Header / Mega Menu | JuJuBit Black Obsidian — Protection & Grounding Energy $20.99 $29.99 | [https://jujubit.ai/products/jujubit-black-obsidian-protection-grounding-energy-1](https://jujubit.ai/products/jujubit-black-obsidian-protection-grounding-energy-1) | 站内链接 | DOM 中存在，当前未显示 |
| 53 | 公共 Header / Mega Menu | JuJuBit White Phantom × Golden Citrine Bracelet $39.99 $54.99 | [https://jujubit.ai/products/jujubit-white-phantom-golden-citrine-new-year-wealth-momentum-energy](https://jujubit.ai/products/jujubit-white-phantom-golden-citrine-new-year-wealth-momentum-energy) | 站内链接 | DOM 中存在，当前未显示 |
| 54 | 公共 Header / Mega Menu | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Mecha-01 $29.99 | [https://jujubit.ai/products/jujubit-custom-artisan-keycap](https://jujubit.ai/products/jujubit-custom-artisan-keycap) | 站内链接 | DOM 中存在，当前未显示 |
| 55 | 公共 Header / Mega Menu | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Fossil $29.99 | [https://jujubit.ai/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards-1](https://jujubit.ai/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards-1) | 站内链接 | DOM 中存在，当前未显示 |
| 56 | 公共 Header / Mega Menu | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Corgi $29.99 / SHOP | [https://jujubit.ai/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards](https://jujubit.ai/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards) | 站内链接 | 可见 |
| 57 | 公共 Header / Mega Menu | Personalized Pet Acrylic Photo Board $19.99 | [https://jujubit.ai/products/personalized-pet-acrylic-photo-board](https://jujubit.ai/products/personalized-pet-acrylic-photo-board) | 站内链接 | DOM 中存在，当前未显示 |
| 58 | 公共 Header / Mega Menu | Personalized Friendship Acrylic Photo Board $19.99 | [https://jujubit.ai/products/personalized-friendship-acrylic-photo-board](https://jujubit.ai/products/personalized-friendship-acrylic-photo-board) | 站内链接 | DOM 中存在，当前未显示 |
| 59 | 公共 Header / Mega Menu | Personalized Portrait Acrylic Board $19.99 | [https://jujubit.ai/products/personalized-portrait-acrylic-board](https://jujubit.ai/products/personalized-portrait-acrylic-board) | 站内链接 | DOM 中存在，当前未显示 |
| 60 | 公共 Header / Mega Menu | 图片/图标链接（无可见文字） | [https://jujubit.ai/search](https://jujubit.ai/search) | 站内链接 | 可见 |
| 61 | Hero / Banner | Create your own | [https://jujubit.ai/pages/back-to-school](https://jujubit.ai/pages/back-to-school) | 站内链接 | 可见 |
| 62 | 创作模板 | Create Now | [https://jujubit.ai/products/two-person-templates-series-custom-figures-for-love-friendship-connection](https://jujubit.ai/products/two-person-templates-series-custom-figures-for-love-friendship-connection) | 站内链接 | 可见 |
| 63 | 创作模板 | Create Now / More Workflow | [https://jujubit.ai/products/custom-mini-pop-figurine-turn-your-photo-into-a-cute-3d-figure](https://jujubit.ai/products/custom-mini-pop-figurine-turn-your-photo-into-a-cute-3d-figure) | 站内链接 | 可见 |
| 64 | 创作模板 | Create Now | [https://jujubit.ai/products/custom-cinematic-figurine-cartoon-style-3d-figure](https://jujubit.ai/products/custom-cinematic-figurine-cartoon-style-3d-figure) | 站内链接 | 可见 |
| 65 | 创作模板 | Create Now | [https://jujubit.ai/products/custom-realistic-figurine-turn-your-photo-into-a-lifelike-3d-figure](https://jujubit.ai/products/custom-realistic-figurine-turn-your-photo-into-a-lifelike-3d-figure) | 站内链接 | 可见 |
| 66 | 分类入口 | SHOP | [https://jujubit.ai/collections/trpg](https://jujubit.ai/collections/trpg) | 站内链接 | 可见 |
| 67 | 分类入口 | EXPLORE | [https://jujubit.ai/collections/tripo-jujubit](https://jujubit.ai/collections/tripo-jujubit) | 站内链接 | 可见 |
| 68 | 趋势商品 | Webs Everywhere – The Spider’s Nest Encounter Set $24.99 | [https://jujubit.ai/products/webs-everywhere-the-spider-s-nest-encounter-set](https://jujubit.ai/products/webs-everywhere-the-spider-s-nest-encounter-set) | 站内链接 | 可见 |
| 69 | 趋势商品 | The Horde Approaches – The Orc War Band Encounter Set $24.99 | [https://jujubit.ai/products/the-horde-approaches-the-orc-war-band-encounter-set](https://jujubit.ai/products/the-horde-approaches-the-orc-war-band-encounter-set) | 站内链接 | 可见 |
| 70 | 趋势商品 | The Gate Has Opened – The Demon Invasion Encounter Set $24.99 | [https://jujubit.ai/products/the-gate-has-opened-the-demon-invasion-encounter-set](https://jujubit.ai/products/the-gate-has-opened-the-demon-invasion-encounter-set) | 站内链接 | 可见 |
| 71 | 趋势商品 | Descend Into the Tomb – The Undead Horde Encounter Set $24.99 | [https://jujubit.ai/products/descend-into-the-tomb-the-undead-horde-encounter-set](https://jujubit.ai/products/descend-into-the-tomb-the-undead-horde-encounter-set) | 站内链接 | 可见 |
| 72 | 趋势商品 | Build Your First Encounter \| Goblin Ambush Encounter Set $24.99 | [https://jujubit.ai/products/build-your-first-encounter-goblin-ambush-encounter-set](https://jujubit.ai/products/build-your-first-encounter-goblin-ambush-encounter-set) | 站内链接 | 可见 |
| 73 | 趋势商品 | Interrupt the Ritual – The Dark Cult Encounter Set $24.99 | [https://jujubit.ai/products/the-cultist-ritual-dark-cult-encounter-set-hand-painted-resin-miniatures-for-d-d](https://jujubit.ai/products/the-cultist-ritual-dark-cult-encounter-set-hand-painted-resin-miniatures-for-d-d) | 站内链接 | 可见 |
| 74 | 趋势商品 | Enter the Dragon’s Domain – The Dragon’s Lair Encounter Set $24.99 | [https://jujubit.ai/products/enter-the-dragon-s-domain-the-dragon-s-lair-encounter-set](https://jujubit.ai/products/enter-the-dragon-s-domain-the-dragon-s-lair-encounter-set) | 站内链接 | 可见 |
| 75 | 趋势商品 | Crystalline Eye Tyrant-Detailed Sculpt Miniature for RPG, Display & Collection $164.99 | [https://jujubit.ai/products/crystalline-eye-tyrant-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/crystalline-eye-tyrant-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 76 | 趋势商品 | One-Eyed Bonecrusher Ogre-Detailed Sculpt Miniature for RPG, Display & Collection $164.99 | [https://jujubit.ai/products/one-eyed-bonecrusher-ogre-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/one-eyed-bonecrusher-ogre-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 77 | 趋势商品 | Celestial Wyvern Sovereign-Detailed Sculpt Miniature for RPG, Display & Collection $164.99 | [https://jujubit.ai/products/celestial-wyvern-sovereign-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/celestial-wyvern-sovereign-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 78 | 趋势商品 | Shadow Knight-Detailed Sculpt Miniature for RPG, Display & Collection $24.99 | [https://jujubit.ai/products/shadow-knight-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/shadow-knight-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 79 | 趋势商品 | Demon Maid-Detailed Sculpt Miniature for RPG, Display & Collection $24.99 | [https://jujubit.ai/products/demon-maid-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/demon-maid-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 80 | 趋势商品 | Dragonborn Ronin Guardian-Detailed Sculpt Miniature for RPG, Display & Collection $24.99 | [https://jujubit.ai/products/dragonborn-ronin-guardian-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/dragonborn-ronin-guardian-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 81 | 趋势商品 | Crimson Monarch-Detailed Sculpt Miniature for RPG, Display & Collection $24.99 | [https://jujubit.ai/products/crimson-monarch-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/crimson-monarch-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 82 | 趋势商品 | Oakshield Champion-Detailed Sculpt Miniature for RPG, Display & Collection $24.99 | [https://jujubit.ai/products/oakshield-champion-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/products/oakshield-champion-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 83 | 公共 Footer | Instagram | [https://www.instagram.com/thisisjujubit_](https://www.instagram.com/thisisjujubit_) | 外部链接 | 可见 |
| 84 | 公共 Footer | YouTube | [https://www.youtube.com/@thisisjujubit](https://www.youtube.com/@thisisjujubit) | 外部链接 | 可见 |
| 85 | 公共 Footer | X | [https://x.com/thisisjujubit](https://x.com/thisisjujubit) | 外部链接 | 可见 |
| 86 | 公共 Footer | TikTok | [https://www.tiktok.com/@jujubit_official](https://www.tiktok.com/@jujubit_official) | 外部链接 | 可见 |
| 87 | 公共 Footer | Creative Rights | [https://jujubit.ai/pages/intellectual-property-ai-generated-designs](https://jujubit.ai/pages/intellectual-property-ai-generated-designs) | 站内链接 | 可见 |
| 88 | 公共 Footer | Terms of Services | [https://jujubit.ai/pages/terms-of-service](https://jujubit.ai/pages/terms-of-service) | 站内链接 | 可见 |
| 89 | 公共 Footer | Shipping Policy | [https://jujubit.ai/pages/shipping-policy](https://jujubit.ai/pages/shipping-policy) | 站内链接 | 可见 |
| 90 | 公共 Footer | Privacy Policy | [https://jujubit.ai/pages/privacy-policy](https://jujubit.ai/pages/privacy-policy) | 站内链接 | 可见 |
| 91 | 公共 Footer | Payment Method | [https://jujubit.ai/pages/payment-method](https://jujubit.ai/pages/payment-method) | 站内链接 | 可见 |
| 92 | 公共 Footer | Sizing Chart | [https://jujubit.ai/pages/sizing-chart](https://jujubit.ai/pages/sizing-chart) | 站内链接 | 可见 |
| 93 | 公共 Footer | Powered by Shopify | [https://www.shopify.com/?utm_campaign=poweredby&utm_medium=shopify&utm_source=onlinestore](https://www.shopify.com/?utm_campaign=poweredby&utm_medium=shopify&utm_source=onlinestore) | 外部链接 | 可见 |
| 94 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2F](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2F) | 站内链接 | 可见 |

## 4. 购物车

页面：<https://jujubit.ai/cart>

固定链接如下。**Checkout** 是按钮触发的动态操作入口，实际地址为运行时生成的 `/checkout` 或 `/checkouts/...`，不写入具体会话 URL，也不计入固定 href 数。

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 95 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/cart#MainContent](https://jujubit.ai/cart#MainContent) | 页面内锚点 | 可见 |
| 96 | 语言/地区/首页入口 | 语言/地区选择器的当前页地址 | [https://jujubit.ai/cart](https://jujubit.ai/cart) | 站内链接 | DOM 中存在，当前未显示 |
| 97 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart](https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart) | 站内链接 | 可见 |
| 98 | 空购物车 | Continue shopping | [https://jujubit.ai/collections/all](https://jujubit.ai/collections/all) | 站内链接 | DOM 中存在，当前未显示 |
| 99 | 商品推荐 | View all / View all130 products | [https://jujubit.ai/collections/just-restocked](https://jujubit.ai/collections/just-restocked) | 站内链接 | 可见 |
| 100 | 商品推荐 | Crimson Monarch-Detailed Sculpt Miniature for RPG, Display & Collection from $24.99 | [https://jujubit.ai/collections/just-restocked/products/crimson-monarch-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/collections/just-restocked/products/crimson-monarch-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 101 | 商品推荐 | Elven Archer-Detailed Sculpt Miniature for RPG, Display & Collection from $24.99 | [https://jujubit.ai/collections/just-restocked/products/elven-archer-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/collections/just-restocked/products/elven-archer-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 102 | 商品推荐 | Dark Lords-Detailed Sculpt Miniature for RPG, Display & Collection from $24.99 | [https://jujubit.ai/collections/just-restocked/products/dark-lords-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/collections/just-restocked/products/dark-lords-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 103 | 商品推荐 | Shadow Knight-Detailed Sculpt Miniature for RPG, Display & Collection from $24.99 | [https://jujubit.ai/collections/just-restocked/products/shadow-knight-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/collections/just-restocked/products/shadow-knight-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 104 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcart](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcart) | 站内链接 | 可见 |

## 5. 创作/生成页

请求入口：<https://jujubit.ai/products/customize-your-own>

抓取时最终地址：<https://jujubit.ai/products/customize-your-own?variant=62485711716723>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 105 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/products/customize-your-own?variant=62485711716723#MainContent](https://jujubit.ai/products/customize-your-own?variant=62485711716723#MainContent) | 页面内锚点 | 可见 |
| 106 | 商品图片 | 商品图片：15% OFF | [https://jujubit.ai/cdn/shop/files/pod_1800x1800.png?v=1770294841](https://jujubit.ai/cdn/shop/files/pod_1800x1800.png?v=1770294841) | 媒体文件 | 可见 |
| 107 | 商品图片 | 商品图片：15% OFF | [https://jujubit.ai/cdn/shop/files/pod1_1800x1800.png?v=1770294841](https://jujubit.ai/cdn/shop/files/pod1_1800x1800.png?v=1770294841) | 媒体文件 | 可见 |
| 108 | 商品图片 | 商品图片：15% OFF | [https://jujubit.ai/cdn/shop/files/pod2_1800x1800.png?v=1776771772](https://jujubit.ai/cdn/shop/files/pod2_1800x1800.png?v=1776771772) | 媒体文件 | 可见 |
| 109 | 商品图片 | 商品图片：15% OFF | [https://jujubit.ai/cdn/shop/files/pod4_1800x1800.png?v=1776771772](https://jujubit.ai/cdn/shop/files/pod4_1800x1800.png?v=1776771772) | 媒体文件 | 可见 |
| 110 | 商品图片 | 商品图片：15% OFF | [https://jujubit.ai/cdn/shop/files/20260701-155546_1800x1800.jpg?v=1782892696](https://jujubit.ai/cdn/shop/files/20260701-155546_1800x1800.jpg?v=1782892696) | 媒体文件 | 可见 |
| 111 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=generate&return_url=%2Fproducts%2Fcustomize-your-own%3Fvariant%3D62485711716723](https://jujubit.ai/pages/vip-program?entry_page=generate&return_url=%2Fproducts%2Fcustomize-your-own%3Fvariant%3D62485711716723) | 站内链接 | 可见 |
| 112 | 商品政策 | Shipping | [https://jujubit.ai/policies/shipping-policy](https://jujubit.ai/policies/shipping-policy) | 站内链接 | DOM 中存在，当前未显示 |
| 113 | 关联集合 | 图片/图标链接（无可见文字） | [https://jujubit.ai/collections/valentine-collection](https://jujubit.ai/collections/valentine-collection) | 站内链接 | 可见 |
| 114 | 关联集合 | 图片/图标链接（无可见文字） | [https://jujubit.ai/collections/wawas-world](https://jujubit.ai/collections/wawas-world) | 站内链接 | 可见 |
| 115 | 商品推荐 | Whisper Blade-Detailed Sculpt Miniature for RPG, Display & Collection from $24.99 | [https://jujubit.ai/collections/just-restocked/products/whisper-blade-detailed-sculpt-miniature-for-rpg-display-collection](https://jujubit.ai/collections/just-restocked/products/whisper-blade-detailed-sculpt-miniature-for-rpg-display-collection) | 站内链接 | 可见 |
| 116 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fproducts%2Fcustomize-your-own%3Fvariant%3D62485711716723](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fproducts%2Fcustomize-your-own%3Fvariant%3D62485711716723) | 站内链接 | 可见 |

## 6. 集合页

页面：<https://jujubit.ai/collections>

集合前缀商品地址（如 `/collections/keycaps/products/...`）是页面真实 href，虽然通常落到同一商品详情，仍按可跳转地址保留。

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 117 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/collections#MainContent](https://jujubit.ai/collections#MainContent) | 页面内锚点 | 可见 |
| 118 | 集合入口 | EXPLORE | [https://jujubit.ai/collections/encounter-packs](https://jujubit.ai/collections/encounter-packs) | 站内链接 | 可见 |
| 119 | 集合入口 | EXPLORE | [https://jujubit.ai/collections/mini-pop](https://jujubit.ai/collections/mini-pop) | 站内链接 | 可见 |
| 120 | 集合入口 | EXPLORE | [https://jujubit.ai/collections/momo-planet](https://jujubit.ai/collections/momo-planet) | 站内链接 | 可见 |
| 121 | 集合入口 | EXPLORE | [https://jujubit.ai/collections/lords-of-the-fallen-realms](https://jujubit.ai/collections/lords-of-the-fallen-realms) | 站内链接 | 可见 |
| 122 | 集合内商品 | Custom Classic Chibi Head Keychain \| Turn Your Character into a Cute Keepsake from $45.00 | [https://jujubit.ai/collections/keychain-pod/products/custom-classic-chibi-keychain](https://jujubit.ai/collections/keychain-pod/products/custom-classic-chibi-keychain) | 站内链接 | 可见 |
| 123 | 集合内商品 | Custom Soft Chibi Head Keychain \| Carry Your Favorite Face Everywhere from $45.00 | [https://jujubit.ai/collections/keychain-pod/products/custom-soft-chibi-head-keychain](https://jujubit.ai/collections/keychain-pod/products/custom-soft-chibi-head-keychain) | 站内链接 | 可见 |
| 124 | 集合内商品 | Sakura Neko \|Classic Chibi Keychain from $45.00 | [https://jujubit.ai/collections/keychain-pod/products/sakura-neko-classic-chibi-keychain-1](https://jujubit.ai/collections/keychain-pod/products/sakura-neko-classic-chibi-keychain-1) | 站内链接 | 可见 |
| 125 | 集合内商品 | Golden Curls Girl｜Classic Chibi Keychain from $45.00 | [https://jujubit.ai/collections/keychain-pod/products/classic-chibi-keychain-golden-curls-girl](https://jujubit.ai/collections/keychain-pod/products/classic-chibi-keychain-golden-curls-girl) | 站内链接 | 可见 |
| 126 | 集合内商品 | Honey Bun ｜Soft Chibi Keychain from $45.00 | [https://jujubit.ai/collections/keychain-pod/products/honey-bun-soft-chibi-keychain](https://jujubit.ai/collections/keychain-pod/products/honey-bun-soft-chibi-keychain) | 站内链接 | 可见 |
| 127 | 集合内商品 | Custom Pet Night Light – Turn Your Photo Into Light from $129.99 | [https://jujubit.ai/collections/fdm/products/custom-pet-night-light-turn-your-photo-into-light](https://jujubit.ai/collections/fdm/products/custom-pet-night-light-turn-your-photo-into-light) | 站内链接 | 可见 |
| 128 | 集合内商品 | Dalmatian Ambient Light｜JuJuBit FDM 3D Printed Night Light for Kids Room & Desk from $89.99 | [https://jujubit.ai/collections/fdm/products/dottyglow%E2%84%A2-dalmatian-ambient-lamp](https://jujubit.ai/collections/fdm/products/dottyglow%E2%84%A2-dalmatian-ambient-lamp) | 站内链接 | 可见 |
| 129 | 集合内商品 | Horse Head Ambient Light｜JuJuBit FDM 3D Printed Night Light for Office & Shelf from $89.99 | [https://jujubit.ai/collections/fdm/products/horse-head-ambient-light-jujubit-fdm-3d-printed-night-light-for-office-shelf](https://jujubit.ai/collections/fdm/products/horse-head-ambient-light-jujubit-fdm-3d-printed-night-light-for-office-shelf) | 站内链接 | 可见 |
| 130 | 集合内商品 | Sparrow Ambient Light｜JuJuBit FDM 3D Printed Night Light for Living Room & Desk from $89.99 | [https://jujubit.ai/collections/fdm/products/sparrow-ambient-light-jujubit-fdm-3d-printed-night-light-for-living-room-desk](https://jujubit.ai/collections/fdm/products/sparrow-ambient-light-jujubit-fdm-3d-printed-night-light-for-living-room-desk) | 站内链接 | 可见 |
| 131 | 集合内商品 | French Bulldog Ambient Light｜JuJuBit FDM 3D Printed Night Light for Bedside & Desk from $89.99 | [https://jujubit.ai/collections/fdm/products/mochipup%E2%84%A2-frenchie-mood-lamp](https://jujubit.ai/collections/fdm/products/mochipup%E2%84%A2-frenchie-mood-lamp) | 站内链接 | 可见 |
| 132 | 集合内商品 | JuJuBit Lavender Amethyst — Serenity & Inner Peace Energy Regular price $29.99 Sale price $20.99 | [https://jujubit.ai/collections/crystal-bracelets/products/jujubit-lavender-amethyst-serenity-inner-peace-energy](https://jujubit.ai/collections/crystal-bracelets/products/jujubit-lavender-amethyst-serenity-inner-peace-energy) | 站内链接 | 可见 |
| 133 | 集合内商品 | JuJuBit Black Obsidian — Protection & Grounding Energy Regular price $29.99 Sale price $20.99 | [https://jujubit.ai/collections/crystal-bracelets/products/jujubit-black-obsidian-protection-grounding-energy-1](https://jujubit.ai/collections/crystal-bracelets/products/jujubit-black-obsidian-protection-grounding-energy-1) | 站内链接 | 可见 |
| 134 | 集合内商品 | JuJuBit White Phantom × Golden Citrine Bracelet Regular price $54.99 Sale price $39.99 | [https://jujubit.ai/collections/crystal-bracelets/products/jujubit-white-phantom-golden-citrine-new-year-wealth-momentum-energy](https://jujubit.ai/collections/crystal-bracelets/products/jujubit-white-phantom-golden-citrine-new-year-wealth-momentum-energy) | 站内链接 | 可见 |
| 135 | 集合内商品 | JuJuBit SAGITTARIUS Zodiac Bracelet – Amethyst × White Phantom for Clear Vision & Expansive Growth Regular price $54.99 Sale price $39.99 | [https://jujubit.ai/collections/crystal-bracelets/products/jujubit-amethyst-white-phantom-sagittarius](https://jujubit.ai/collections/crystal-bracelets/products/jujubit-amethyst-white-phantom-sagittarius) | 站内链接 | 可见 |
| 136 | 集合内商品 | JuJuBit Amethyst — Clarity & Expression Energy Regular price $54.99 Sale price $39.99 | [https://jujubit.ai/collections/crystal-bracelets/products/jujubit-amethyst-gemini-clarity-expression-energy](https://jujubit.ai/collections/crystal-bracelets/products/jujubit-amethyst-gemini-clarity-expression-energy) | 站内链接 | 可见 |
| 137 | 集合内商品 | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Mecha-01 from $29.99 | [https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap](https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap) | 站内链接 | 可见 |
| 138 | 集合内商品 | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Fossil $29.99 | [https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards-1](https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards-1) | 站内链接 | 可见 |
| 139 | 集合内商品 | JuJuBit Custom Artisan Keycap for Mechanical Keyboards Corgi from $29.99 | [https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards](https://jujubit.ai/collections/keycaps/products/jujubit-custom-artisan-keycap-for-mechanical-keyboards) | 站内链接 | 可见 |
| 140 | 集合内商品 | JuJuBit Christmas Santa Artisan Keycap from $29.99 | [https://jujubit.ai/collections/keycaps/products/jujubit-christmas-classic-artisan-keycap-for-mechanical-keyboards](https://jujubit.ai/collections/keycaps/products/jujubit-christmas-classic-artisan-keycap-for-mechanical-keyboards) | 站内链接 | 可见 |
| 141 | 集合内商品 | JuJuBit Christmas Santa Artisan Keycap — Mechanical Keyboard from $29.99 | [https://jujubit.ai/collections/keycaps/products/jujubit-christmas-classic-santa-keycap](https://jujubit.ai/collections/keycaps/products/jujubit-christmas-classic-santa-keycap) | 站内链接 | 可见 |
| 142 | 集合内商品 | Personalized Pet Acrylic Photo Board $19.99 | [https://jujubit.ai/collections/photo-board/products/personalized-pet-acrylic-photo-board](https://jujubit.ai/collections/photo-board/products/personalized-pet-acrylic-photo-board) | 站内链接 | 可见 |
| 143 | 集合内商品 | Personalized Friendship Acrylic Photo Board $19.99 | [https://jujubit.ai/collections/photo-board/products/personalized-friendship-acrylic-photo-board](https://jujubit.ai/collections/photo-board/products/personalized-friendship-acrylic-photo-board) | 站内链接 | 可见 |
| 144 | 集合内商品 | Personalized Portrait Acrylic Board $19.99 | [https://jujubit.ai/collections/photo-board/products/personalized-portrait-acrylic-board](https://jujubit.ai/collections/photo-board/products/personalized-portrait-acrylic-board) | 站内链接 | 可见 |
| 145 | 集合内商品 | Personalized Couple & Anniversary Acrylic Photo Board $19.99 | [https://jujubit.ai/collections/photo-board/products/personalized-couple-anniversary-acrylic-photo-board](https://jujubit.ai/collections/photo-board/products/personalized-couple-anniversary-acrylic-photo-board) | 站内链接 | 可见 |
| 146 | 集合内商品 | Personalized Graduation Acrylic Photo Board $19.99 | [https://jujubit.ai/collections/photo-board/products/personalized-graduation-acrylic-photo-board](https://jujubit.ai/collections/photo-board/products/personalized-graduation-acrylic-photo-board) | 站内链接 | 可见 |
| 147 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcollections](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcollections) | 站内链接 | 可见 |

## 7. 模板集合页

页面：<https://jujubit.ai/collections/templates-create-your-own>

当前 DOM 发现第 2 页入口，但本次未继续抓取第 2 页内容；分页地址本身已列入。

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 148 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/collections/templates-create-your-own#MainContent](https://jujubit.ai/collections/templates-create-your-own#MainContent) | 页面内锚点 | 可见 |
| 149 | 模板商品 | JuJuBit Customized Figurine-Create Your Own from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/customize-your-own](https://jujubit.ai/collections/templates-create-your-own/products/customize-your-own) | 站内链接 | 可见 |
| 150 | 模板商品 | Custom Figurine of Yourself \| Turn Your Photo into a 3D Printed Figure from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-figurine-of-yourself](https://jujubit.ai/collections/templates-create-your-own/products/custom-figurine-of-yourself) | 站内链接 | 可见 |
| 151 | 模板商品 | Custom TRPG Miniature – Create Your Own Tabletop RPG Character Figure from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-miniature-create-your-own-tabletop-rpg-character-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-miniature-create-your-own-tabletop-rpg-character-figure) | 站内链接 | 可见 |
| 152 | 模板商品 | Custom TRPG Creature Miniature \| Create Your Own Monster, Familiar or Boss Figure from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-creature-miniature-create-your-own-monster-familiar-or-boss-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-creature-miniature-create-your-own-monster-familiar-or-boss-figure) | 站内链接 | 可见 |
| 153 | 模板商品 | Custom TRPG Character Miniature \| Create Your Own Tabletop RPG Hero from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-miniature-create-your-own-trpg-hero-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-trpg-miniature-create-your-own-trpg-hero-figure) | 站内链接 | 可见 |
| 154 | 模板商品 | Custom Pop Figurine \| Turn Your Photo into a Cute 3D Figure from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-mini-pop-figurine-turn-your-photo-into-a-cute-3d-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-mini-pop-figurine-turn-your-photo-into-a-cute-3d-figure) | 站内链接 | 可见 |
| 155 | 模板商品 | Custom Cinematic Figurine — Cartoon-Style 3D Figure from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-cinematic-figurine-cartoon-style-3d-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-cinematic-figurine-cartoon-style-3d-figure) | 站内链接 | 可见 |
| 156 | 模板商品 | Custom Realistic Figurine \| Turn Your Photo into a Lifelike 3D Figure from $69.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-realistic-figurine-turn-your-photo-into-a-lifelike-3d-figure](https://jujubit.ai/collections/templates-create-your-own/products/custom-realistic-figurine-turn-your-photo-into-a-lifelike-3d-figure) | 站内链接 | 可见 |
| 157 | 模板商品 | Pet Season Special \| Custom Realistic 3D Figurine for Your Beloved Pet from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-realistic-figurine-create-3d-figurine-for-your-beloved-pet](https://jujubit.ai/collections/templates-create-your-own/products/custom-realistic-figurine-create-3d-figurine-for-your-beloved-pet) | 站内链接 | 可见 |
| 158 | 模板商品 | Custom Couple Figurine \| Turn Your Love Story Into a 3D Collectible from $69.99 | [https://jujubit.ai/collections/templates-create-your-own/products/two-person-templates-series-custom-figures-for-love-friendship-connection](https://jujubit.ai/collections/templates-create-your-own/products/two-person-templates-series-custom-figures-for-love-friendship-connection) | 站内链接 | 可见 |
| 159 | 模板商品 | Parent & Child Custom Figurine \| Turn Family Love Into a 3D Collectible from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/parent-child-custom-figurine-turn-family-love-into-a-3d-collectible](https://jujubit.ai/collections/templates-create-your-own/products/parent-child-custom-figurine-turn-family-love-into-a-3d-collectible) | 站内链接 | 可见 |
| 160 | 模板商品 | Custom Helmet Babies \| Turn Your Image into a Cute 3D figurine from $49.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-helmet-babies-turn-your-image-into-a-cute-3d-figurine](https://jujubit.ai/collections/templates-create-your-own/products/custom-helmet-babies-turn-your-image-into-a-cute-3d-figurine) | 站内链接 | 可见 |
| 161 | 模板商品 | Custom Voxel Figurine \| Turn Yourself into a 3D Pixelated character from $49.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-voxel-figurine-turn-yourself-into-a-3d-pixelated-character](https://jujubit.ai/collections/templates-create-your-own/products/custom-voxel-figurine-turn-yourself-into-a-3d-pixelated-character) | 站内链接 | 可见 |
| 162 | 模板商品 | Custom Special Force Figurine \| Turn Yourself into a special force soldier from $69.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-special-force-figurine-turn-yourself-into-a-3d-secret-agent](https://jujubit.ai/collections/templates-create-your-own/products/custom-special-force-figurine-turn-yourself-into-a-3d-secret-agent) | 站内链接 | 可见 |
| 163 | 模板商品 | Personalized Mini Pop Couple Figure \| Custom Two-Person Collectible from $59.99 | [https://jujubit.ai/collections/templates-create-your-own/products/personalized-mini-pop-couple-figure-custom-two-person-collectible](https://jujubit.ai/collections/templates-create-your-own/products/personalized-mini-pop-couple-figure-custom-two-person-collectible) | 站内链接 | 可见 |
| 164 | 模板商品 | Custom Low-poly Figurine \| Personalized Your Geometric Statue from $29.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-low-poly-figurine-turn-yourself-into-a-3d-hogwarts-student](https://jujubit.ai/collections/templates-create-your-own/products/custom-low-poly-figurine-turn-yourself-into-a-3d-hogwarts-student) | 站内链接 | 可见 |
| 165 | 模板商品 | Custom Ghibli Figurine \| Personalized Your Personal Soft Anime Figurine from $69.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-ghibli-figurine-personalized-your](https://jujubit.ai/collections/templates-create-your-own/products/custom-ghibli-figurine-personalized-your) | 站内链接 | 可见 |
| 166 | 模板商品 | Custom Cowboy & Cowgirl Figurine \| Personalized Your Western American Stylish Avatar from $69.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-cowboy-cowgirl-figurine-personalized-your-western-american-stylish-avatar](https://jujubit.ai/collections/templates-create-your-own/products/custom-cowboy-cowgirl-figurine-personalized-your-western-american-stylish-avatar) | 站内链接 | 可见 |
| 167 | 模板商品 | Custom Dark Gothic Figurine \| Bring your zombie nightmare imaginations into reality. from $49.99 | [https://jujubit.ai/collections/templates-create-your-own/products/custom-dark-gothic-figurine-bring-the-zoombie-nightmare-into-a-real-world](https://jujubit.ai/collections/templates-create-your-own/products/custom-dark-gothic-figurine-bring-the-zoombie-nightmare-into-a-real-world) | 站内链接 | 可见 |
| 168 | 分页 | 2 / Next | [https://jujubit.ai/collections/templates-create-your-own?page=2](https://jujubit.ai/collections/templates-create-your-own?page=2) | 站内链接 | 可见 |
| 169 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcollections%2Ftemplates-create-your-own](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fcollections%2Ftemplates-create-your-own) | 站内链接 | 可见 |

## 8. 内容与帮助页

以下页面均继承首页的公共 Header/Footer，本节只列各页新增链接。

### 8.1 How It Works

页面：<https://jujubit.ai/pages/how-it-works>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 170 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/how-it-works#MainContent](https://jujubit.ai/pages/how-it-works#MainContent) | 页面内锚点 | 可见 |
| 171 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fhow-it-works](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fhow-it-works) | 站内链接 | 可见 |

### 8.2 Tracking

页面：<https://jujubit.ai/pages/tracking>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 172 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/tracking#MainContent](https://jujubit.ai/pages/tracking#MainContent) | 页面内锚点 | 可见 |
| 173 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Ftracking](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Ftracking) | 站内链接 | 可见 |

### 8.3 Contact Us

页面：<https://jujubit.ai/pages/contact>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 174 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/contact#MainContent](https://jujubit.ai/pages/contact#MainContent) | 页面内锚点 | 可见 |
| 175 | 表单验证 | Privacy Policy | [https://hcaptcha.com/privacy](https://hcaptcha.com/privacy) | 外部链接 | 可见 |
| 176 | 表单验证 | Terms of Service | [https://hcaptcha.com/terms](https://hcaptcha.com/terms) | 外部链接 | 可见 |
| 177 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fcontact](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fcontact) | 站内链接 | 可见 |

### 8.4 FAQs

页面：<https://jujubit.ai/pages/faqs>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 178 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/faqs#MainContent](https://jujubit.ai/pages/faqs#MainContent) | 页面内锚点 | 可见 |
| 179 | 联系支持 | support@jujubit.ai | [mailto:support@jujubit.ai](mailto:support@jujubit.ai) | 邮件操作 | DOM 中存在，当前未显示 |
| 180 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Ffaqs](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Ffaqs) | 站内链接 | 可见 |

### 8.5 Refund & Exchange Policy

页面：<https://jujubit.ai/pages/refund-exchange-policy>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 181 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/refund-exchange-policy#MainContent](https://jujubit.ai/pages/refund-exchange-policy#MainContent) | 页面内锚点 | 可见 |
| 182 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Frefund-exchange-policy](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Frefund-exchange-policy) | 站内链接 | 可见 |

### 8.6 About Us

页面：<https://jujubit.ai/pages/about-us>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 183 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/about-us#MainContent](https://jujubit.ai/pages/about-us#MainContent) | 页面内锚点 | 可见 |
| 184 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fabout-us](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fabout-us) | 站内链接 | 可见 |

### 8.7 Join Us

页面：<https://jujubit.ai/pages/join-us>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 185 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/join-us#MainContent](https://jujubit.ai/pages/join-us#MainContent) | 页面内锚点 | 可见 |
| 186 | 招聘申请 | APPLY IT NOW | [https://docs.google.com/forms/d/e/1FAIpQLSerlr0f__gb1nneIpYpX826rsBm1us6RzzO0oporXBq9mowZQ/viewform?usp=publish-editor](https://docs.google.com/forms/d/e/1FAIpQLSerlr0f__gb1nneIpYpX826rsBm1us6RzzO0oporXBq9mowZQ/viewform?usp=publish-editor) | 外部链接 | 可见 |
| 187 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fjoin-us](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fjoin-us) | 站内链接 | 可见 |

## 9. 搜索页

页面：<https://jujubit.ai/search>

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 188 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/search#MainContent](https://jujubit.ai/search#MainContent) | 页面内锚点 | 可见 |
| 189 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fsearch](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fsearch) | 站内链接 | 可见 |

## 10. 会员页

页面：<https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart>

`entry_page` 与 `return_url` 会随入口变化，因此文档保留抓取到的真实参数组合，但不把它们误认为不同会员页面模板。

| 序号 | 模块 | 链接文字 | 链接 | 类型 | 抓取时可见性 |
| ---: | --- | --- | --- | --- | --- |
| 190 | 无障碍入口 | Skip to content（跳到主内容） | [https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart#MainContent](https://jujubit.ai/pages/vip-program?entry_page=cart_whole&return_url=%2Fcart#MainContent) | 页面内锚点 | 可见 |
| 191 | 会员入口 | Upgrade | [https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fvip-program%3Fentry_page%3Dcart_whole%26return_url%3D%252Fcart](https://jujubit.ai/pages/vip-program?entry_page=cart_half&return_url=%2Fpages%2Fvip-program%3Fentry_page%3Dcart_whole%26return_url%3D%252Fcart) | 站内链接 | 可见 |

## 11. 动态操作入口

| 所在页面 | 操作 | 地址规则 | 说明 |
| --- | --- | --- | --- |
| 购物车 | Checkout | `/checkout` 或 `/checkouts/...` | 依购物车、地区和会话动态生成，不记录具体订单 URL。 |
| 全站 Header/Footer | 语言切换 | 当前路径 + locale 表单提交 | DOM 中选项可能共用当前页 href，真实切换由脚本/表单完成。 |
| 全站 Header/Footer | 币种/地区切换 | 当前路径 + country/currency 表单提交 | 不存在稳定的一选项一固定 href。 |
| Header | 账户 | `https://shopify.com/95408849267/account` | 已移除一次性 `buyer_flags` 参数。 |

## 12. 已知数据边界

- 首页、购物车、创作页、集合总览、模板集合第一页、7 个内容/帮助页、搜索页和一个会员入口已抓取。
- 没有递归打开所有 191 条链接；因此商品详情中的推荐链接、其他集合分页、账户登录后链接可能继续产生新目的地。
- 页面内容会随 Shopify 商品上架、推荐算法、A/B 配置和地区变化；维护时应重新抓取并按同一规则比较差异。
