#!/usr/bin/env python3
"""
阻容感/PCB 常用物料价格追踪
数据来源：立创商城 (szlcsc.com) via Selenium
功能：抓取价格 -> 追加历史记录 -> 更新 index.html

物料清单（按市场常用度从高到低）：
- MLCC: 0402 1uF > 0201 100nF > 0603 10uF > 0805 22uF
- 电阻: 0402 10K > 0603 100R > 0805 4.7K
- 电感: 0402 1uH > 0603 4.7uH > 功率电感 10uH 3A
- PCB: FR-4 双面/四层, HDI, 高频板 (手动维护)
"""

import json
import re
import sys
import io
from datetime import datetime
from pathlib import Path

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / 'passive_history.json'
HTML_FILE = SCRIPT_DIR / 'index.html'

# ===== 追踪物料定义（按市场常用度从高到低排序）=====
TRACK_ITEMS = {
    "MLCC": {
        "label": "⚡ MLCC 贴片电容",
        "items": [
            ("0402 1uF X5R 10V", {"keyword": "0402 1uF X5R 10V", "unit": "¥/颗"}),
            ("0201 100nF X5R 16V", {"keyword": "0201 100nF X5R 16V", "unit": "¥/颗"}),
            ("0603 10uF X5R 10V", {"keyword": "0603 10uF X5R 10V", "unit": "¥/颗"}),
            ("0805 22uF X5R 6.3V", {"keyword": "0805 22uF X5R", "unit": "¥/颗"}),
        ]
    },
    "电阻": {
        "label": "🔌 贴片电阻",
        "items": [
            ("0402 10KΩ ±1%", {"keyword": "0402 10K 0402", "unit": "¥/颗"}),
            ("0603 100Ω ±1%", {"keyword": "0603 100R 0603", "unit": "¥/颗"}),
            ("0805 4.7KΩ ±1%", {"keyword": "0805 4.7K", "unit": "¥/颗"}),
        ]
    },
    "电感": {
        "label": "🧲 贴片电感",
        "items": [
            ("0402 1uH ±5%", {"keyword": "0402 1UH", "unit": "¥/颗"}),
            ("0603 4.7uH ±5%", {"keyword": "0603 4.7UH", "unit": "¥/颗"}),
            ("功率电感 10uH 3A", {"keyword": "SMD 10uH 3A", "unit": "¥/颗"}),
        ]
    },
    "PCB": {
        "label": "📋 PCB 板材/覆铜板",
        "items": [
            ("FR-4 双面板 (1.6mm)", {"keyword": None, "unit": "¥/㎡", "manual": True}),
            ("FR-4 四层板", {"keyword": None, "unit": "¥/㎡", "manual": True}),
            ("HDI板", {"keyword": None, "unit": "¥/㎡", "manual": True}),
            ("高频板 (Rogers)", {"keyword": None, "unit": "¥/㎡", "manual": True}),
        ]
    }
}


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_update": "", "categories": {}}


def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [OK] History saved")


def get_last_price(history, category, item_name):
    cat = history.get("categories", {}).get(category, {})
    item = cat.get("items", {}).get(item_name, {})
    hist = item.get("history", [])
    return hist[-1]["price"] if hist else None


def determine_trend(current, previous):
    if previous is None or previous == 0:
        return "新增"
    pct = (current - previous) / previous * 100
    if abs(pct) < 1:
        return "平稳"
    elif pct >= 5:
        return f"上涨 +{pct:.1f}%"
    elif pct >= 1:
        return f"微涨 +{pct:.1f}%"
    elif pct <= -5:
        return f"下跌 {pct:.1f}%"
    elif pct <= -1:
        return f"微跌 {pct:.1f}%"
    return "平稳"


def scrape_with_selenium(keyword):
    """用 Selenium 搜索立创商城并提取价格"""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')

    driver = webdriver.Chrome(options=options)
    try:
        # 搜索
        driver.get(f'https://so.szlcsc.com/global.html?k={keyword}')
        import time
        time.sleep(8)

        page = driver.page_source
        if '完成验证' in page or '安全验证' in page:
            print(f"    CAPTCHA detected for {keyword}")
            return None

        # 提取产品ID
        links = re.findall(r'item\.szlcsc\.com/(\d+)\.html', page)
        if not links:
            print(f"    No product found for {keyword}")
            return None

        pid = links[0]
        # 访问详情页
        driver.get(f'https://item.szlcsc.com/{pid}.html')
        time.sleep(5)

        page = driver.page_source
        prices = re.findall(r'"price"\s*:\s*"?(\d+\.?\d*)"?', page)
        stock = re.findall(r'"value"\s*:\s*(\d+)', page)

        if prices:
            price = float(prices[0])
            stock_qty = int(stock[0]) if stock else 0
            return {'price': price, 'stock': stock_qty, 'pid': pid}
        return None
    finally:
        driver.quit()


def scrape_prices(history):
    """抓取所有物料价格"""
    today = datetime.now().strftime('%Y-%m-%d')
    results = {}
    scraped = 0

    if not HAS_SELENIUM:
        print("  [WARN] Selenium not installed, using fallback prices")
        # Fallback: 保留上次价格
        for cat_name, cat_info in TRACK_ITEMS.items():
            results[cat_name] = {"label": cat_info["label"], "items": {}}
            for item_name, item_info in cat_info["items"]:
                last = get_last_price(history, cat_name, item_name)
                if last is not None:
                    results[cat_name]["items"][item_name] = {
                        "price": last, "trend": "平稳", "unit": item_info["unit"], "source": "fallback"
                    }
        return results, 0

    print(f"\n  Scraping from LCSC via Selenium...")

    for cat_name, cat_info in TRACK_ITEMS.items():
        results[cat_name] = {"label": cat_info["label"], "items": {}}
        print(f"\n  [{cat_name}]")

        for item_name, item_info in cat_info["items"]:
            if item_info.get("manual"):
                last = get_last_price(history, cat_name, item_name)
                if last is not None:
                    results[cat_name]["items"][item_name] = {
                        "price": last, "trend": "平稳", "unit": item_info["unit"], "source": "manual"
                    }
                    print(f"    {item_name}: CNY{last} (manual)")
                continue

            data = scrape_with_selenium(item_info["keyword"])
            if data:
                prev = get_last_price(history, cat_name, item_name)
                trend = determine_trend(data["price"], prev)
                results[cat_name]["items"][item_name] = {
                    "price": data["price"], "trend": trend, "unit": item_info["unit"], "source": "lcsc"
                }
                scraped += 1
                print(f"    {item_name}: CNY{data['price']} ({trend}) stock={data['stock']:,}")
            else:
                last = get_last_price(history, cat_name, item_name)
                if last is not None:
                    results[cat_name]["items"][item_name] = {
                        "price": last, "trend": "数据待更新", "unit": item_info["unit"], "source": "fallback"
                    }
                    print(f"    {item_name}: CNY{last} (fallback)")

    return results, scraped


def append_to_history(history, results, today):
    for cat_name, cat_data in results.items():
        if cat_name not in history["categories"]:
            history["categories"][cat_name] = {"label": cat_data["label"], "items": {}}

        for item_name, item_data in cat_data["items"].items():
            if item_name not in history["categories"][cat_name]["items"]:
                history["categories"][cat_name]["items"][item_name] = {
                    "unit": item_data["unit"], "history": []
                }

            hist = history["categories"][cat_name]["items"][item_name]["history"]
            if hist and hist[-1]["date"] == today:
                hist[-1]["price"] = item_data["price"]
                hist[-1]["trend"] = item_data["trend"]
            else:
                hist.append({"date": today, "price": item_data["price"], "trend": item_data["trend"]})

    history["last_update"] = today
    return history


def update_html_tables(results, today):
    if not HTML_FILE.exists():
        return

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    for cat_name, cat_data in results.items():
        label = cat_data["label"]
        items = cat_data["items"]
        if not items:
            continue

        rows = []
        for item_name, item_data in items.items():
            price_val = item_data["price"]
            unit = item_data["unit"]
            trend = item_data["trend"]

            suffix = unit.split('/')[-1] if '/' in unit else ''
            if price_val >= 100:
                price_str = f"CNY{price_val:,.0f}/{suffix}" if suffix else f"CNY{price_val:,.0f}"
            elif price_val >= 1:
                price_str = f"CNY{price_val:.2f}/{suffix}" if suffix else f"CNY{price_val:.2f}"
            else:
                price_str = f"CNY{price_val}/{suffix}" if suffix else f"CNY{price_val}"

            if '涨' in trend or '紧' in trend:
                td_class = 'price-up'
            elif '跌' in trend:
                td_class = 'price-down'
            else:
                td_class = 'price-flat'

            rows.append(f'<tr><td>{item_name}</td><td>{price_str}</td><td class="{td_class}">{trend}</td></tr>')

        rows_html = '\n                        '.join(rows)
        escaped_label = re.escape(label)
        pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>.*?<tbody>)(.*?)(</tbody>)',
            re.DOTALL
        )
        match = pattern.search(html)
        if match:
            html = html[:match.start(2)] + '\n                        ' + rows_html + '\n                    ' + html[match.end(2):]

        date_pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>\s*<div class="price-card-sub"[^>]*>)更新日期：[\d-]+'
        )
        html = date_pattern.sub(r'\1更新日期：' + today, html)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  [OK] index.html updated")


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 50)
    print("阻容感/PCB Price Tracker")
    print(f"Date: {today}")
    print("=" * 50)

    history = load_history()
    print(f"Last update: {history.get('last_update', 'none')}")

    results, scraped = scrape_prices(history)

    history = append_to_history(history, results, today)
    save_history(history)
    update_html_tables(results, today)

    total = sum(len(cat["items"]) for cat in results.values())
    print(f"\nDone! {total} items, {scraped} scraped from LCSC")


if __name__ == '__main__':
    main()
