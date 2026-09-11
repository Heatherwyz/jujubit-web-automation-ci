#!/usr/bin/env python3
"""Render the dated local comprehensive performance report from test artifacts."""

from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/performance/2026-08-19/JuJuBit-综合性能测试报告-2026-08-19.md"
BASE = ROOT / "artifacts/performance/2026-08-19"


def ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f} ms"


def main() -> None:
    lighthouse = []
    for path in sorted((BASE / "lighthouse").glob("*.json")):
        data = json.loads(path.read_text())
        audits = data["audits"]
        stem = path.stem
        name = (
            "首页" if stem == "jujubit.ai-mobile"
            else "Create 商品页" if "products-customize-your-own" in stem
            else "Photo Board 集合页" if "collections-photo-board" in stem
            else stem
        )
        lighthouse.append({
            "name": name,
            "score": round(data["categories"]["performance"]["score"] * 100),
            "fcp": audits["first-contentful-paint"]["numericValue"],
            "lcp": audits["largest-contentful-paint"]["numericValue"],
            "tbt": audits["total-blocking-time"]["numericValue"],
            "cls": audits["cumulative-layout-shift"]["numericValue"],
            "si": audits["speed-index"]["numericValue"],
            "tti": audits["interactive"]["numericValue"],
            "requests": len(audits["network-requests"]["details"]["items"]),
        })

    browser = json.loads((BASE / "browser/browser-performance-sample.json").read_text())["results"]
    probe = json.loads((BASE / "site-html-probe.json").read_text())
    good = [item for item in probe["results"] if item["ok"] and item["ttfb_ms"] is not None]
    ttfb = sorted(item["ttfb_ms"] for item in good)
    p95 = ttfb[round((len(ttfb) - 1) * .95)]
    slow = sorted(good, key=lambda item: item["ttfb_ms"], reverse=True)[:8]
    browser_rows = []
    for item in browser:
        nav = item["navigation"]
        browser_rows.append(
            f"| {item['label']} | {item['profile']} | {item['status']} | {ms(nav.get('responseStart'))} | {ms(nav.get('domContentLoadedEventEnd'))} | {ms(nav.get('loadEventEnd'))} | {item['resource_count']} | {item['resource_transfer_bytes']/1024:.1f} KiB | {item['failed_request_count']} |"
        )
    lh_rows = []
    for item in lighthouse:
        lh_rows.append(
            f"| {item['name']} | {item['score']} | {ms(item['fcp'])} | {ms(item['lcp'])} | {ms(item['tbt'])} | {item['cls']:.3f} | {ms(item['si'])} | {ms(item['tti'])} | {item['requests']} |"
        )
    slow_rows = [f"| `{x['url']}` | {x['status']} | {ms(x['ttfb_ms'])} | {x['method']} |" for x in slow]
    content = f"""# JuJuBit 综合性能测试报告 - 2026-08-19

> 本地生成时间：{dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}。报告只使用本次实际生成的本地测试产物；没有账号或当前网络不可达的第三方工具不以“已执行”表述。

## 1. 执行范围与结论

本轮按《JuJuBit-美国用户性能测试工具清单》尝试了所有列出的工具类别。已实际完成的本地可运行测试包括：

1. 全链路 `curl` 链接采样（190 个唯一链接，含站内、站外和资产）。
2. 站内 HTML 低频可达性/TTFB 巡检（归一化后 115 个页面）。
3. Lighthouse 移动端实验室审计（首页、Create 商品页、Photo Board 集合页）。
4. Playwright/Chromium 真浏览器导航采样（同 3 类页面的桌面和移动视口）。

核心判断：**站内页面的首字节轻度偏慢，浏览器渲染性能问题更突出。** Lighthouse 的三类代表页 LCP 均超过 2.5s 目标，Create 页同时出现显著 CLS（0.667）与 TBT（715.5ms）；这应优先进入前端/主题与第三方脚本排查。页面级 HEAD/Range 巡检 115/115 可达，说明本轮未发现站内 HTML 链接失效，但不能替代完整页面下载和渲染性能。

## 2. 测试条件与边界

| 项目 | 本轮配置 |
|---|---|
| 采样时间 | 2026-08-19（Asia/Shanghai） |
| 本地浏览器 | Chromium（Playwright） |
| Lighthouse | v12.8.2，移动端，模拟节流，单次实验室审计 |
| 浏览器采样 | 新建无登录上下文；移动 390×844、桌面 1440×900；DOM Content Loaded 后再等待 15s |
| HTML 巡检 | HEAD，失败时 Range `0-0`；并发 2、间隔 1.5s、超时 30s |
| 链接采样 | curl，190 URL，并发 8、单 URL 超时 20s、跟随重定向 |

这些数据来自当前执行环境，**不是美国节点**、不是 RUM、也不是容量/压测结果。Lighthouse/Playwright 的页面资源量与真实用户会受 CDN 节点、缓存、Cookie 弹窗、AB 实验和第三方服务影响。

## 3. Lighthouse 移动端实验室结果

| 页面 | Performance | FCP | LCP | TBT | CLS | Speed Index | TTI | 请求数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(lh_rows)}

判读：LCP 目标为 ≤2.5s、CLS ≤0.1。首页 LCP 14.3s；Create 页分数最低（15），CLS 为 0.667；Photo Board 集合页 LCP 22.0s。三页均需优化，Create 页应先处理布局稳定性和主线程阻塞，集合页应优先定位 LCP 资源与关键请求链。

原始 Lighthouse JSON 位于 `artifacts/performance/2026-08-19/lighthouse/`，可导入 Lighthouse Viewer 继续查看瀑布、诊断项和截图。

## 4. Chromium 真浏览器导航观察

| 页面 | 视口 | 文档状态 | responseStart | DOMContentLoaded | loadEventEnd | 资源数 | 传输量 | 失败请求 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(browser_rows)}

所有代表页主文档均为 HTTP 200，且未记录导航级异常。失败子请求数量较多（15–33），它可能包括第三方请求、取消请求、跨域策略或资源延迟；详单保存在 `browser/browser-performance-sample.json`，不能仅凭计数判定业务故障。浏览器采样中的 LCP/CLS PerformanceObserver 值未稳定采集，因此以 Lighthouse 的 LCP/CLS 为本报告的实验室核心指标。

## 5. 站内 HTML 可达性与 TTFB 巡检

| 指标 | 结果 |
|---|---:|
| 归一化 HTML 页面 | {len(probe['results'])} |
| 成功 | {len(good)} |
| 失败/非 2xx-3xx | {len(probe['results']) - len(good)} |
| TTFB 平均值 | {statistics.mean(ttfb):.1f}ms |
| TTFB P50 | {statistics.median(ttfb):.1f}ms |
| TTFB P95 | {p95:.1f}ms |

最慢 TTFB 页面：

| URL | 状态 | TTFB | 方法 |
|---|---:|---:|---|
{chr(10).join(slow_rows)}

本项只读取响应头或首字节，不能说明页面图片、脚本和响应体下载完成速度；它与第 3、4 节的页面加载结果应结合解读。

## 6. 全链接 curl 采样回顾

已生成的链接报告覆盖 Markdown 清单提取的 190 个唯一 URL：HTTP 可完成 182、2xx/3xx 166、异常或超时 24；有效响应 TTFB P50/P95 为 2478.0/5947.3ms，总耗时 P50/P95 为 8199.8/20004.3ms。重点异常包含首页/Create/若干商品页响应体传输在 20s 内未完成，以及 YouTube、Instagram、Google Forms、X 等外部目的地不可达或超时。

详见 `artifacts/performance/jujubit-link-performance-2026-08-19.md` 与对应 JSON。清单声明 191 条固定目的地，但 Markdown 去重后实际为 190 URL，建议后续复核清单中的重复/遗漏记录。

## 7. 工具覆盖状态

| 工具/数据源 | 状态 | 本轮处理与原因 |
|---|---|---|
| Lighthouse / Lighthouse CI | 已执行 Lighthouse | 本地 CLI 已完成 3 页移动端实验室审计；未配置 CI 工作流门禁。 |
| Playwright / 浏览器开发者工具能力 | 已执行 | 完成 3 页 × 桌面/移动的真实 Chromium 导航和资源观察。 |
| curl | 已执行 | 完成全链接链路计时。 |
| WebPageTest | 未执行 | 需要指定美国节点的公开/账号服务；当前未配置可调用 API 或交互授权。 |
| GTmetrix | 未执行 | 需要网页交互/账号或 API key，当前未提供。 |
| PageSpeed Insights / CrUX | 已尝试，未取得结果 | Google PSI API 与 pagespeed.web.dev 在当前网络出口连接超时；且未提供 CrUX API key/美国维度可用性。 |
| SpeedVitals | 未执行 | 美国多地点能力与批量次数依账号套餐，未提供账号/API。 |
| Pingdom | 未执行 | 未提供可用的节点/API 访问方式。 |
| DebugBear / SpeedCurve | 未执行 | 属于持续合成监控/RUM，需项目账号、站点接入与告警配置。 |
| Shopify Web Performance | 未执行 | 需 Shopify Admin 权限与后台数据。 |
| Shopify Theme Inspector | 未执行 | 需交互式 Chrome 扩展与主题性能剖析会话；当前未配置。 |

## 8. 优先级建议

1. **P0：Create 商品页**：先审查首屏容器高度/异步组件，修复 CLS；在 Lighthouse JSON 中定位长任务和阻塞 JS，延迟非必要应用脚本。
2. **P0：Photo Board 集合页与首页 LCP**：确定 LCP 元素，压缩并使用合适尺寸的首屏图片；避免将 LCP 图像懒加载；预加载关键图片/字体。
3. **P1：资源与第三方治理**：以 Chromium 失败请求与 Lighthouse 瀑布为线索，分离营销、评论、聊天、追踪、3D/定制器的加载时机；设置资源大小、请求数和 TBT 预算。
4. **P1：美国区域复测**：提供 WebPageTest/SpeedVitals/GTmetrix 的账号或 API 后，按美国西/中/东、移动/桌面、冷/热缓存各跑至少 5 次，输出中位数和 P75。
5. **P2：真实用户基线**：接入 Shopify Web Performance 或 `web-vitals` RUM，按 `country=US`、设备、页面类型输出 LCP/INP/CLS P75/P90；这才可作为美国用户体验结论。

## 9. 本地交付物

- 综合报告：`artifacts/performance/2026-08-19/JuJuBit-综合性能测试报告-2026-08-19.md`
- Lighthouse 原始报告：`artifacts/performance/2026-08-19/lighthouse/*.json`
- 浏览器采样：`artifacts/performance/2026-08-19/browser/browser-performance-sample.json`
- 站内 HTML 巡检：`artifacts/performance/2026-08-19/site-html-probe.md`、`site-html-probe.json`
- 全链接采样：`artifacts/performance/jujubit-link-performance-2026-08-19.md`、`jujubit-link-performance-2026-08-19.json`
"""
    OUT.write_text(content, encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
