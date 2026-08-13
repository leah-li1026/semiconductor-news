#!/usr/bin/env python3
"""
半导体情报站 - 每周自动更新价格数据
数据来源：中国闪存市场 https://www.chinaflashmarket.com/

覆盖品类：DRAM现货、DDR5服务器RDIMM、企业级SSD、消费级SSD、LPDDR5X、NAND Wafer
更新内容：价格表格、更新日期
"""

import re
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import requests
    from bs4 import BeautifulSoup
    USE_REQUESTS = True
except ImportError:
    from urllib.request import urlopen, Request
    USE_REQUESTS = False

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def fetch_page(url):
    """抓取网页内容"""
    try:
        if USE_REQUESTS:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.encoding = 'utf-8'
            return resp.text
        else:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=20) as resp:
                return resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  ⚠️ 抓取失败 {url}: {e}")
        return None


def parse_all_prices(html):
    """
    解析中国闪存市场首页所有价格表格
    返回 {产品名: {price, change, change_pct}} 字典
    """
    soup = BeautifulSoup(html, 'html.parser')
    prices = {}

    for table in soup.find_all('table', class_='price-table'):
        for row in table.find_all('tr'):
            th = row.find('th', class_='title')
            if not th:
                continue

            # 产品名
            name = th.get_text(strip=True)

            # 价格
            price_span = row.find('span', class_=re.compile(r'new-price'))
            if price_span:
                price = price_span.get_text(strip=True).replace('$', '').strip()
            else:
                tds = row.find_all('td')
                if not tds:
                    continue
                price = tds[0].get_text(strip=True).replace('$', '').replace(',', '').strip()

            # 涨跌
            change = '持平'
            change_pct = '0.00%'
            tds = row.find_all('td')
            for td in tds:
                text = td.get_text(strip=True)
                pct_match = re.search(r'([+-][\d.]+%)', text)
                if pct_match:
                    change_pct = pct_match.group(1)
                    change = change_pct
                    break
                if '涨' in text and '跌' not in text:
                    change = text
                elif '跌' in text:
                    change = text
                elif '持平' in text or '平稳' in text:
                    change = '持平'

            prices[name] = {
                'price': price,
                'change': change,
                'change_pct': change_pct,
            }

    return prices


def make_change_cell(change_str):
    """生成涨跌HTML单元格"""
    if not change_str or change_str in ('持平', '平稳', '0.00%', '0%'):
        return '<td class="price-flat">持平</td>'
    if change_str.startswith('+') or '涨' in change_str:
        return f'<td class="price-up">{change_str}</td>'
    if change_str.startswith('-') or '跌' in change_str:
        return f'<td class="price-down">{change_str}</td>'
    return f'<td class="price-flat">{change_str}</td>'


def format_price(val_str):
    """格式化价格显示"""
    try:
        val = float(val_str.replace(',', ''))
        if val >= 1000:
            return f'${val:,.0f}'
        elif val >= 1:
            return f'${val:.2f}'
        else:
            return f'${val}'
    except ValueError:
        return f'${val_str}'


def update_card_table(html, card_keyword, new_data, today):
    """
    更新指定卡片中的表格数据
    card_keyword: 卡片标题中的关键字
    new_data: [(产品名, 价格, 涨跌), ...] 列表
    """
    # 定位卡片
    card_pattern = re.compile(
        r'(<div class="price-card-title">[^<]*' + re.escape(card_keyword) + r'[^<]*</div>.*?<tbody>)(.*?)(</tbody>)',
        re.DOTALL
    )

    match = card_pattern.search(html)
    if not match:
        print(f"    ⚠️ 未找到「{card_keyword}」卡片")
        return html

    rows = '\n'.join(
        f'                        <tr><td>{name}</td><td>{format_price(price)}</td>{make_change_cell(change)}</tr>'
        for name, price, change in new_data
    )

    html = html[:match.start()] + match.group(1) + '\n' + rows + '\n                    ' + match.group(3) + html[match.end():]

    # 更新日期
    date_pattern = re.compile(
        r'(<div class="price-card-title">[^<]*' + re.escape(card_keyword) + r'[^<]*</div>\s*<div class="price-card-sub">)更新日期：[\d-]+'
    )
    html = date_pattern.sub(r'\1更新日期：' + today, html)

    print(f"    ✅ {card_keyword}: {len(new_data)} 条数据已更新")
    return html


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 50)
    print("🔬 半导体情报站 - 价格数据自动更新")
    print(f"📅 日期: {today}")
    print("=" * 50)

    # 1. 抓取数据
    print("\n📡 正在抓取中国闪存市场数据...")
    html = fetch_page('https://www.chinaflashmarket.com/')
    if not html:
        print("❌ 抓取失败，退出")
        sys.exit(1)

    prices = parse_all_prices(html)
    print(f"  ✅ 解析到 {len(prices)} 条价格数据")

    if not prices:
        print("❌ 无数据，退出")
        sys.exit(1)

    # 打印抓取到的数据
    print("\n📊 抓取到的价格数据:")
    for name, info in prices.items():
        print(f"  {name}: ${info['price']} ({info['change']})")

    # 2. 读取HTML
    filepath = 'index.html'
    print(f"\n📝 正在更新 {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # 3. 更新各品类价格表

    # DRAM 现货价
    dram_items = []
    for name in ['DDR4 16Gb 3200', 'DDR4 8Gb 3200', 'DDR5 24Gb Major', 'DDR5 16Gb Major', 'DDR5 16Gb eTT']:
        if name in prices:
            p = prices[name]
            dram_items.append((name, p['price'], p['change']))
    if dram_items:
        html_content = update_card_table(html_content, 'DRAM 现货价格', dram_items, today)

    # DDR5 服务器合约价
    rdimm_items = []
    for name in ['DDR5 RDIMM 32GB', 'DDR5 RDIMM 64GB', 'DDR5 RDIMM 96GB']:
        if name in prices:
            p = prices[name]
            rdimm_items.append((name, p['price'], p['change']))
    if rdimm_items:
        html_content = update_card_table(html_content, 'DDR5 服务器合约价', rdimm_items, today)

    # 企业级SSD (行业市场，HTML中用短名称)
    essd_map = {
        'PCIe 3.0 256GB': 'SSD(PCIe 3.0) 256GB',
        'PCIe 3.0 512GB': 'SSD(PCIe 3.0) 512GB',
        'PCIe 3.0 1TB': 'SSD(PCIe 3.0) 1TB',
        'PCIe 4.0 512GB': 'SSD(PCIe 4.0) 512GB',
        'PCIe 4.0 1TB': 'SSD(PCIe 4.0) 1TB',
        'PCIe 4.0 2TB': 'SSD(PCIe 4.0) 2TB',
    }
    essd_items = []
    for html_name, cfm_name in essd_map.items():
        if cfm_name in prices:
            p = prices[cfm_name]
            essd_items.append((html_name, p['price'], p['change']))
    if essd_items:
        html_content = update_card_table(html_content, '企业级SSD价格', essd_items, today)

    # 消费级SSD
    cssd_items = []
    for name in ['SSD(PCIe 3.0) 256GB', 'SSD(PCIe 3.0) 512GB', 'SSD(PCIe 3.0) 1TB',
                 'SSD(PCIe 4.0) 512GB', 'SSD(PCIe 4.0) 1TB', 'SSD(PCIe 4.0) 2TB']:
        if name in prices:
            p = prices[name]
            cssd_items.append((name, p['price'], p['change']))
    if cssd_items:
        html_content = update_card_table(html_content, '消费级SSD价格', cssd_items, today)

    # LPDDR5X
    lpddr_items = []
    for name in ['LPDDR5X 128Gb', 'LPDDR5X 96Gb', 'LPDDR5X 64Gb']:
        if name in prices:
            p = prices[name]
            lpddr_items.append((name, p['price'], p['change']))
    if lpddr_items:
        html_content = update_card_table(html_content, 'LPDDR5X 移动端价格', lpddr_items, today)

    # NAND Wafer
    nand_items = []
    for name in ['1Tb QLC', '1Tb TLC', '512Gb TLC', '256Gb TLC']:
        if name in prices:
            p = prices[name]
            nand_items.append((name, p['price'], p['change']))
    if nand_items:
        html_content = update_card_table(html_content, 'NAND Flash Wafer 价格', nand_items, today)

    # 4. 保存
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)

    total = len(dram_items) + len(rdimm_items) + len(essd_items) + len(cssd_items) + len(lpddr_items) + len(nand_items)
    print(f"\n🎉 更新完成！共更新 {total} 条价格数据 ({today})")


if __name__ == '__main__':
    main()
