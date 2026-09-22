#!/usr/bin/env python3
"""
阻容感/PCB 常用物料价格追踪（按品牌）
数据来源：立创商城 (szlcsc.com) via Selenium / 手动输入
功能：按品牌抓取价格 -> 追加历史记录 -> 更新 index.html

用法：
  python update_passive.py              # 自动抓取（需 Selenium + Chrome）
  python update_passive.py --manual     # 手动输入价格（交互式）
  python update_passive.py --show       # 查看当前历史数据
"""

import json
import re
import sys
import io
import argparse
from datetime import datetime
from pathlib import Path

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import time
import random

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    HAS_SELENIUM = True
except ImportError:
    HAS_SELENIUM = False

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
]

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / 'passive_history.json'
HTML_FILE = SCRIPT_DIR / 'index.html'


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_update": "", "categories": {}}


def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("  [OK] History saved")


def scrape_lcsc(driver, keyword, max_retries=3):
    """搜索立创商城，返回价格（带重试机制）"""
    for attempt in range(max_retries):
        try:
            driver.get(f'https://so.szlcsc.com/global.html?k={keyword}')
            time.sleep(5 + random.uniform(1, 3))

            page = driver.page_source
            if '完成验证' in page or '安全验证' in page:
                print(f"      ⚠️ 验证码拦截 (尝试 {attempt+1}/{max_retries})")
                # 清除cookies重试
                driver.delete_all_cookies()
                time.sleep(3 + random.uniform(2, 5))
                continue

            links = re.findall(r'item\.szlcsc\.com/(\d+)\.html', page)
            if not links:
                return None, None, 'no_results'

            pid = links[0]
            driver.get(f'https://item.szlcsc.com/{pid}.html')
            time.sleep(3 + random.uniform(1, 2))

            page = driver.page_source
            prices = re.findall(r'"price"\s*:\s*"?(\d+\.?\d*)"?', page)
            brand = re.search(r'"brand"[^}]*"name"\s*:\s*"([^"]+)"', page)

            if prices:
                return float(prices[0]), brand.group(1) if brand else None, None
            return None, None, 'no_price'
        except Exception as e:
            print(f"      ❌ 异常 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5 + random.uniform(3, 7))
                continue
            return None, None, f'error: {e}'
    return None, None, 'CAPTCHA_max_retries'


def scrape_all(history):
    """按品牌抓取所有物料（带UA轮换和随机间隔）"""
    if not HAS_SELENIUM:
        print("  [WARN] Selenium not installed")
        return {}, 0

    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    # 降低自动化检测风险
    options.add_argument('--disable-blink-features=AutomationControlled')

    driver = webdriver.Chrome(options=options)
    # 隐藏 webdriver 特征
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
    })

    results = {}
    scraped = 0
    captcha_count = 0
    max_captcha = 5  # 连续验证码超过此数则提前终止

    try:
        for cat_name, cat_data in history.get('categories', {}).items():
            if cat_name == 'PCB':
                continue
            for item_name, item_data in cat_data.get('items', {}).items():
                for brand_name, brand_data in item_data.get('brands', {}).items():
                    kw = brand_data.get('keyword')
                    if not kw:
                        continue

                    price, real_brand, err = scrape_lcsc(driver, kw)
                    if price:
                        if item_name not in results:
                            results[item_name] = {}
                        results[item_name][brand_name] = price
                        scraped += 1
                        captcha_count = 0
                        print(f"    {item_name} [{brand_name}]: CNY{price}")
                    else:
                        print(f"    {item_name} [{brand_name}]: {err}")
                        if 'CAPTCHA' in str(err):
                            captcha_count += 1
                            if captcha_count >= max_captcha:
                                print(f"\n  ⚠️ 连续验证码拦截 {captcha_count} 次，提前终止抓取")
                                return results, scraped

                    # 请求间随机间隔
                    time.sleep(2 + random.uniform(1, 3))
    finally:
        driver.quit()

    return results, scraped


def manual_input(history):
    """交互式手动输入价格"""
    today = datetime.now().strftime('%Y-%m-%d')
    results = {}

    print(f"\n{'='*60}")
    print(f"  手动输入阻容感价格  日期: {today}")
    print(f"{'='*60}")
    print("  提示: 直接回车跳过，输入 'q' 结束\n")

    for cat_name, cat_data in history.get('categories', {}).items():
        label = cat_data.get('label', cat_name)
        print(f"\n━━━ {label} ━━━")

        for item_name, item_data in cat_data.get('items', {}).items():
            brands = item_data.get('brands', {})
            unit = item_data.get('unit', '')

            # 显示上次价格
            last_prices = []
            for brand_name, brand_data in brands.items():
                hist = brand_data.get('history', [])
                if hist:
                    last_prices.append(f"{brand_name}: ¥{hist[-1]['price']}")
            hint = f"  (上次: {', '.join(last_prices)})" if last_prices else ""

            print(f"\n  📦 {item_name} [{unit}]{hint}")

            for brand_name, brand_data in brands.items():
                hist = brand_data.get('history', [])
                last = hist[-1]['price'] if hist else None
                default_hint = f" (上次: ¥{last})" if last is not None else ""

                val = input(f"    {brand_name}{default_hint}: ").strip()
                if val.lower() == 'q':
                    print("\n  结束输入。")
                    return results, today
                if val == '':
                    continue
                try:
                    price = float(val)
                    if item_name not in results:
                        results[item_name] = {}
                    results[item_name][brand_name] = price
                    print(f"      ✓ ¥{price}")
                except ValueError:
                    print(f"      ✗ 无效输入，跳过")

    return results, today


def append_to_history(history, results, today):
    """将新价格追加到历史，仅在抓取覆盖率足够时更新 last_update"""
    updated_brands = 0
    total_brands = 0

    for cat_name, cat_data in history.get('categories', {}).items():
        if cat_name == 'PCB':
            continue
        for item_name, item_data in cat_data.get('items', {}).items():
            for brand_name, brand_data in item_data.get('brands', {}).items():
                total_brands += 1
                if item_name in results and brand_name in results[item_name]:
                    new_price = results[item_name][brand_name]
                    hist = brand_data.get('history', [])

                    # 计算趋势
                    if hist:
                        prev = hist[-1]['price']
                        pct = (new_price - prev) / prev * 100 if prev else 0
                        if abs(pct) < 1:
                            trend = '平稳'
                        elif pct >= 5:
                            trend = f'上涨 +{pct:.1f}%'
                        elif pct >= 1:
                            trend = f'微涨 +{pct:.1f}%'
                        elif pct <= -5:
                            trend = f'下跌 {pct:.1f}%'
                        else:
                            trend = f'微跌 {pct:.1f}%'
                    else:
                        trend = '新增'

                    if hist and hist[-1]['date'] == today:
                        hist[-1]['price'] = new_price
                        hist[-1]['trend'] = trend
                    else:
                        hist.append({'date': today, 'price': new_price, 'trend': trend})
                    brand_data['history'] = hist
                    updated_brands += 1

    # 仅在抓取覆盖率 >= 50% 时更新 last_update，避免部分抓取导致数据不一致
    coverage = updated_brands / total_brands * 100 if total_brands > 0 else 0
    if coverage >= 50:
        history['last_update'] = today
        print(f"  ✅ last_update 已更新 ({updated_brands}/{total_brands} = {coverage:.0f}% 覆盖)")
    else:
        print(f"  ⚠️ 抓取不完整 ({updated_brands}/{total_brands} = {coverage:.0f}%)，保留原 last_update: {history.get('last_update')}")

    return history


def show_history(history):
    """显示当前历史数据摘要"""
    print(f"\n{'='*60}")
    print(f"  阻容感价格历史数据  最后更新: {history.get('last_update', '无')}")
    print(f"{'='*60}")

    for cat_name, cat_data in history.get('categories', {}).items():
        label = cat_data.get('label', cat_name)
        print(f"\n{label}")
        print(f"{'─'*50}")

        for item_name, item_data in cat_data.get('items', {}).items():
            brands = item_data.get('brands', {})
            unit = item_data.get('unit', '')
            print(f"\n  {item_name} [{unit}]")

            for brand_name, brand_data in brands.items():
                hist = brand_data.get('history', [])
                if not hist:
                    print(f"    {brand_name}: 暂无数据")
                    continue

                latest = hist[-1]
                n = len(hist)
                if n >= 2:
                    prev = hist[-2]['price']
                    pct = (latest['price'] - prev) / prev * 100 if prev else 0
                    arrow = '↑' if pct > 0 else ('↓' if pct < 0 else '→')
                    print(f"    {brand_name}: ¥{latest['price']} {arrow}{abs(pct):.1f}% ({n}条记录, {hist[0]['date']}~{latest['date']})")
                else:
                    print(f"    {brand_name}: ¥{latest['price']} ({n}条记录)")

    print()


def update_html(history, data_date):
    """更新 index.html 中的阻容感表格
    data_date: 实际数据日期（只在有新数据时才更新HTML中的日期）
    """
    if not HTML_FILE.exists():
        return

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    for cat_name, cat_data in history.get('categories', {}).items():
        label = cat_data['label']
        items = cat_data.get('items', {})
        if not items:
            continue

        rows = []
        for item_name, item_data in items.items():
            brands = item_data.get('brands', {})
            unit = item_data.get('unit', '')

            # 取第一个有数据的品牌价格
            display_brand = None
            display_price = None
            display_trend = None
            for brand_name, brand_data in brands.items():
                hist = brand_data.get('history', [])
                if hist:
                    latest = hist[-1]
                    if display_price is None:
                        display_brand = brand_name
                        display_price = latest['price']
                        display_trend = latest.get('trend', '平稳')

            if display_price is None:
                continue

            suffix = unit.split('/')[-1] if '/' in unit else ''
            if display_price >= 100:
                price_str = f"CNY{display_price:,.0f}"
            elif display_price >= 1:
                price_str = f"CNY{display_price:.2f}"
            else:
                price_str = f"CNY{display_price}"

            if suffix:
                price_str += f"/{suffix}"

            # 趋势样式
            if display_trend and ('涨' in display_trend or '紧' in display_trend):
                td_class = 'price-up'
            elif display_trend and '跌' in display_trend:
                td_class = 'price-down'
            else:
                td_class = 'price-flat'

            # 品牌信息
            brand_names = [b for b in brands.keys() if brands[b].get('history')]
            brand_str = ' / '.join(brand_names) if brand_names else ''

            rows.append(
                f'<tr><td>{item_name}</td>'
                f'<td><span style="color:#94a3b8;font-size:10px">{brand_str}</span><br>{price_str}</td>'
                f'<td class="{td_class}">{display_trend or "—"}</td></tr>'
            )

        if not rows:
            continue

        rows_html = '\n                        '.join(rows)
        escaped_label = re.escape(label)
        pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>.*?<tbody>)(.*?)(</tbody>)',
            re.DOTALL
        )
        match = pattern.search(html)
        if match:
            html = html[:match.start(2)] + '\n                        ' + rows_html + '\n                    ' + html[match.end(2):]

        # 仅在有实际数据日期时更新HTML日期（避免无数据时虚假更新日期）
        if data_date:
            date_pattern = re.compile(
                r'(<div class="price-card-title">' + escaped_label + r'</div>\s*<div class="price-card-sub"[^>]*>)更新日期：[\d-]+'
            )
            html = date_pattern.sub(r'\1更新日期：' + data_date, html)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print("  [OK] index.html updated")


def main():
    parser = argparse.ArgumentParser(description='阻容感价格追踪工具')
    parser.add_argument('--manual', action='store_true', help='手动输入价格（交互式）')
    parser.add_argument('--show', action='store_true', help='查看当前历史数据')
    args = parser.parse_args()

    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 50)
    print("Passive Components Price Tracker (by brand)")
    print(f"Date: {today}")
    print("=" * 50)

    history = load_history()
    print(f"Last update: {history.get('last_update', 'none')}")

    if args.show:
        show_history(history)
        return

    if args.manual:
        results, today = manual_input(history)
        if not results:
            print("\n  没有输入任何价格，退出。")
            return
    else:
        if not HAS_SELENIUM:
            print("\n  [ERROR] Selenium 未安装，无法自动抓取。")
            print("  请使用 --manual 模式手动输入，或安装: pip install selenium")
            return
        print("\nScraping from LCSC...")
        results, scraped = scrape_all(history)
        print(f"\nScraped: {scraped} brand-item pairs")

    history = append_to_history(history, results, today)
    save_history(history)

    # 只在有实际新数据（coverage >= 50%）时才更新HTML日期
    data_date = history.get('last_update', '')
    if data_date == today:
        update_html(history, today)
        print(f"\n✅ 更新完成！日期: {today}")
    else:
        # 抓取不完整，保留原日期，只刷新表格数据（不改日期）
        update_html(history, None)
        print(f"\n⚠️ 抓取不完整，HTML日期未更新，保留: {data_date}")


if __name__ == '__main__':
    main()
