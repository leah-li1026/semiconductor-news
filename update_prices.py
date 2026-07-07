#!/usr/bin/env python3
"""
半导体情报站 - 每周一自动更新价格数据
数据来源：中国闪存市场 https://www.chinaflashmarket.com/
"""

import re
import sys
import io
from datetime import datetime
from urllib.request import urlopen, Request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# 可用的价格页面URL
PRICE_URLS = {
    'consumer_ssd': 'https://www.chinaflashmarket.com/price/ssdoem',
    'lpddr': 'https://www.chinaflashmarket.com/price/lpddr',
}


def fetch_page(url):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  ⚠️ 抓取失败 {url}: {e}")
        return None


def parse_price_rows(html):
    """
    解析中国闪存市场表格行
    结构:
      <th><a>产品名</a></th>
      <td><span class="new-price [price-up|price-down]"><b>$</b>价格</span></td>
      <td><span class="[price-up|price-down]">涨跌额</span></td>  或 持平
      <td><span class="[price-up|price-down]">涨跌幅</span></td>  或 持平
    """
    prices = []

    # 匹配每个 <tr> 行
    row_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
    for row_match in row_pattern.finditer(html):
        row_html = row_match.group(1)

        # 提取产品名
        name_match = re.search(r'<th[^>]*class="title"[^>]*><a[^>]*>(.*?)</a>', row_html)
        if not name_match:
            continue
        product = name_match.group(1).strip()

        # 提取价格 - <span class="new-price..."><b>$</b>142.00</span>
        price_match = re.search(r'<span\s+class\s*=\s*"new-price[^"]*"[^>]*><b>\$</b>([\d,.]+)</span>', row_html)
        if not price_match:
            continue
        price = price_match.group(1).strip()

        # 提取涨跌幅 - 第三个 <td> 中的百分比
        td_blocks = re.findall(r'<td>(.*?)</td>', row_html, re.DOTALL)

        change_pct = '持平'
        for td in td_blocks:
            pct_match = re.search(r'([+-][\d.]+%)', td)
            if pct_match:
                change_pct = pct_match.group(1)
                break
            if '持平' in td or '平稳' in td:
                change_pct = '持平'
                break

        prices.append({
            'product': product,
            'price': price,
            'change': change_pct
        })

    return prices


def format_change(change_str):
    if not change_str or change_str in ('持平', '平稳'):
        return '<td class="price-flat">持平</td>'
    if change_str.startswith('+'):
        return f'<td class="price-up">{change_str}</td>'
    if change_str.startswith('-'):
        return f'<td class="price-down">{change_str}</td>'
    return f'<td class="price-flat">{change_str}</td>'


def update_html_table(html, card_title_keyword, new_prices, today):
    """替换指定卡片中的表格数据"""
    # 定位卡片: 找到包含关键字的 price-card
    card_pattern = re.compile(
        r'(<div class="price-card-title">[^<]*' + re.escape(card_title_keyword) + r'[^<]*</div>.*?<tbody>)(.*?)(</tbody>)',
        re.DOTALL
    )

    match = card_pattern.search(html)
    if not match:
        print(f"    ⚠️ 未找到包含「{card_title_keyword}」的卡片")
        return html

    rows = '\n'.join(
        f'                        <tr><td>{p["product"]}</td><td>${p["price"]}</td>{format_change(p["change"])}</tr>'
        for p in new_prices
    )

    html = html[:match.start()] + match.group(1) + '\n' + rows + '\n                    ' + match.group(3) + html[match.end():]

    # 更新日期
    date_pattern = re.compile(
        r'(<div class="price-card-title">[^<]*' + re.escape(card_title_keyword) + r'[^<]*</div>\s*<div class="price-card-sub">)更新日期：[\d-]+'
    )
    html = date_pattern.sub(r'\1更新日期：' + today, html)

    return html


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print("半导体情报站 - 价格数据更新")
    print(f"日期: {today}")
    print("=" * 50)

    all_prices = {}

    print("\n正在抓取价格数据...")

    # 消费级SSD
    print("  -> 消费级SSD...")
    html = fetch_page(PRICE_URLS['consumer_ssd'])
    if html:
        prices = parse_price_rows(html)
        all_prices['consumer_ssd'] = prices
        print(f"    获取 {len(prices)} 条数据")
        for p in prices:
            print(f"      {p['product']}: ${p['price']} ({p['change']})")

    # LPDDR
    print("  -> LPDDR...")
    html = fetch_page(PRICE_URLS['lpddr'])
    if html:
        prices = parse_price_rows(html)
        all_prices['lpddr'] = prices
        print(f"    获取 {len(prices)} 条数据")
        for p in prices:
            print(f"      {p['product']}: ${p['price']} ({p['change']})")

    total = sum(len(v) for v in all_prices.values())
    if total == 0:
        print("\n未抓取到任何价格数据，跳过更新")
        sys.exit(0)

    print(f"\n共获取 {total} 条价格数据")

    # 读取并更新HTML
    filepath = 'index.html'
    print(f"\n正在更新 {filepath}...")

    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # 更新消费级SSD
    if 'consumer_ssd' in all_prices and all_prices['consumer_ssd']:
        html_content = update_html_table(html_content, '消费级SSD', all_prices['consumer_ssd'], today)

    # 更新LPDDR
    if 'lpddr' in all_prices and all_prices['lpddr']:
        html_content = update_html_table(html_content, 'LPDDR5X', all_prices['lpddr'], today)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\n更新完成 ({today})")


if __name__ == '__main__':
    main()
