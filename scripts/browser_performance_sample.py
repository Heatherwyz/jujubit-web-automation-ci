#!/usr/bin/env python3
"""Collect browser-navigation and Web Vitals samples for representative pages.

This is intentionally a browser observation, not a replacement for RUM or a
commercial multi-region synthetic test. It records what a fresh Chromium
context observed in the current execution environment.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
from pathlib import Path

from playwright.async_api import async_playwright


PAGES = {
    "home": "https://jujubit.ai/",
    "create": "https://jujubit.ai/products/customize-your-own",
    "collection-photo-board": "https://jujubit.ai/collections/photo-board",
}


VITALS_SCRIPT = """() => new Promise(resolve => {
  const result = {lcp_ms: null, cls: 0, long_tasks: 0, long_task_ms: 0};
  try {
    new PerformanceObserver(list => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) result.lcp_ms = last.startTime;
    }).observe({type: 'largest-contentful-paint', buffered: true});
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) result.cls += entry.value;
      }
    }).observe({type: 'layout-shift', buffered: true});
    new PerformanceObserver(list => {
      for (const entry of list.getEntries()) {
        result.long_tasks += 1;
        result.long_task_ms += entry.duration;
      }
    }).observe({type: 'longtask', buffered: true});
  } catch (_) {}
  window.__jujubitVitals = result;
  resolve();
})"""


async def sample(browser, label: str, url: str, mobile: bool) -> dict:
    context = await browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900},
        is_mobile=mobile,
        has_touch=mobile,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            if mobile else None
        ),
    )
    page = await context.new_page()
    responses = []
    failures = []
    page.on("response", lambda response: responses.append(response))
    page.on("requestfailed", lambda request: failures.append({"url": request.url, "error": request.failure or ""}))
    started = dt.datetime.now(dt.timezone.utc)
    error = ""
    try:
        await page.add_init_script(VITALS_SCRIPT)
        response = await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(15_000)
        nav = await page.evaluate("performance.getEntriesByType('navigation')[0]?.toJSON() || {}")
        vitals = await page.evaluate("window.__jujubitVitals || {}")
        resources = await page.evaluate("performance.getEntriesByType('resource').map(x => x.toJSON())")
        body = await page.evaluate("document.body?.innerText?.length || 0")
        status = response.status if response else 0
    except Exception as exc:  # retain partial request detail
        error = str(exc)
        nav, vitals, resources, body, status = {}, {}, [], 0, 0
    finally:
        await context.close()
    transfer = sum(r.get("transferSize", 0) or 0 for r in resources)
    return {
        "label": label, "url": url, "profile": "mobile" if mobile else "desktop",
        "started_at": started.isoformat(), "status": status, "error": error,
        "navigation": nav, "web_vitals": vitals, "resource_count": len(resources),
        "resource_transfer_bytes": transfer, "failed_request_count": len(failures),
        "failed_requests": failures[:30], "body_text_length": body,
        "response_status_counts": {str(code): sum(1 for r in responses if r.status == code) for code in sorted({r.status for r in responses})},
    }


async def main(output: Path) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            results = []
            for label, url in PAGES.items():
                for mobile in (True, False):
                    results.append(await sample(browser, label, url, mobile))
        finally:
            await browser.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.output))
