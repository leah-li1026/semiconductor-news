#!/usr/bin/env python3
"""
阻容感/PCB 常用物料价格追踪
数据来源：立创商城 https://www.szlcsc.com/
功能：抓取价格 → 追加历史记录 → 更新 index.html 趋势图

物料清单（常用标准件）：
- MLCC: 0201 100nF, 0402 1uF, 0603 10uF, 0805 22uF
- 电阻: 0402 10KΩ, 0603 100Ω, 0805 4.7KΩ
- 电感: 0402 1uH, 0603 4.7uH, 功率电感 10uH 3A
- PCB: FR-4 双面/四层, HDI, 高频板
"""

import json
import re
import sys
import io
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / 'passive_history.json'
HTML_FILE = SCRIPT_DIR / 'index.html'

# ===== 追踪物料定义 =====
TRACK_ITEMS = {
    "MLCC": {
        "label": "⚡ MLCC 贴片电容",
        "items": {
            "0201 100nF X5R 16V": {"search": "0201 100nF X5R 16V MLCC", "unit": "¥/颗"},
            "0402 1uF X5R 10V": {"search": "0402 1uF X5R 10V MLCC", "unit": "¥/颗"},
            "0603 10uF X5R 10V": {"search": "0603 10uF X5R 10V MLCC", "unit": "¥/颗"},
            "0805 22uF X5R 6.3V": {"search": "0805 22uF X5R 6.3V MLCC", "unit": "¥/颗"},
        }
    },
    "电阻": {
        "label": "🔌 贴片电阻",
        "items": {
            "0402 10KΩ ±1%": {"search": "0402 10K 1% 贴片电阻", "unit": "¥/颗"},
            "0603 100Ω ±1%": {"search": "0603 100R 1% 贴片电阻", "unit": "¥/颗"},
            "0805 4.7KΩ ±1%": {"search": "0805 4.7K 1% 贴片电阻", "unit": "¥/颗"},
        }
    },
    "电感": {
        "label": "🧲 贴片电感",
        "items": {
            "0402 1uH ±5%": {"search": "0402 1uH 贴片电感", "unit": "¥/颗"},
            "0603 4.7uH ±5%": {"search": "0603 4.7uH 贴片电感", "unit": "¥/颗"},
            "功率电感 10uH 3A": {"search": "功率电感 10uH 3A", "unit": "¥/颗"},
        }
    },
    "PCB": {
        "label": "📋 PCB 板材/覆铜板",
        "items": {
            "FR-4 双面板 (1.6mm)": {"search": "FR-4 双面板 1.6mm", "unit": "¥/㎡", "manual": True},
            "FR-4 四层板": {"search": "FR-4 四层板", "unit": "¥/㎡", "manual": True},
            "HDI板": {"search": "HDI板", "unit": "¥/㎡", "manual": True},
            "高频板 (Rogers)": {"search": "Rogers高频板", "unit": "¥/㎡", "manual": True},
        }
    }
}


def load_history():
    """加载历史数据"""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_update": "", "categories": {}}


def save_history(data):
    """保存历史数据"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 历史数据已保存到 {HISTORY_FILE}")


def search_lcsc(keyword):
    """
    从立创商城搜索物料价格
    返回 (price, trend) 或 None
    """
    if not HAS_REQUESTS:
        print(f"    ⚠️ requests 未安装，跳过在线抓取")
        return None

    try:
        url = f"https://so.szlcsc.com/global.html?k={keyword}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'utf-8'

        # 尝试从搜索结果页提取价格
        # 立创商城搜索结果通常在 JavaScript 变量或特定 class 中
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 方法1：查找价格元素
        price_el = soup.find('span', class_=re.compile(r'price', re.I))
        if price_el:
            price_text = price_el.get_text(strip=True)
            price_match = re.search(r'[\d.]+', price_text.replace(',', ''))
            if price_match:
                return (float(price_match.group()), "待确认")

        # 方法2：查找商品列表中的价格
        product_list = soup.find_all('div', class_=re.compile(r'product|item|list', re.I))
        for item in product_list[:3]:
            price_el = item.find('span', class_=re.compile(r'price', re.I))
            if price_el:
                price_text = price_el.get_text(strip=True)
                price_match = re.search(r'[\d.]+', price_text.replace(',', ''))
                if price_match:
                    return (float(price_match.group()), "待确认")

        # 方法3：正则匹配页面中的价格
        prices = re.findall(r'¥\s*([\d.]+)', resp.text)
        if prices:
            return (float(prices[0]), "待确认")

        print(f"    ⚠️ 未能解析到价格: {keyword}")
        return None

    except Exception as e:
        print(f"    ⚠️ 抓取失败 {keyword}: {e}")
        return None


def get_last_price(history, category, item_name):
    """获取某物料的上一次价格"""
    cat = history.get("categories", {}).get(category, {})
    item = cat.get("items", {}).get(item_name, {})
    hist = item.get("history", [])
    if hist:
        return hist[-1].get("price")
    return None


def determine_trend(current, previous):
    """根据价格变化判断趋势"""
    if previous is None or previous == 0:
        return "新增"
    change_pct = (current - previous) / previous * 100
    if abs(change_pct) < 1:
        return "平稳"
    elif change_pct >= 5:
        return f"上涨 +{change_pct:.1f}%"
    elif change_pct >= 1:
        return f"微涨 +{change_pct:.1f}%"
    elif change_pct <= -5:
        return f"下跌 {change_pct:.1f}%"
    elif change_pct <= -1:
        return f"微跌 {change_pct:.1f}%"
    return "平稳"


def scrape_prices(history):
    """抓取所有物料价格"""
    today = datetime.now().strftime('%Y-%m-%d')
    results = {}
    scraped_count = 0

    for cat_name, cat_info in TRACK_ITEMS.items():
        results[cat_name] = {"label": cat_info["label"], "items": {}}
        print(f"\n📡 [{cat_name}]")

        for item_name, item_info in cat_info["items"].items():
            # PCB 等手动维护的品类，保留上次价格
            if item_info.get("manual"):
                last = get_last_price(history, cat_name, item_name)
                if last is not None:
                    results[cat_name]["items"][item_name] = {
                        "price": last,
                        "trend": "平稳",
                        "unit": item_info["unit"],
                        "source": "manual"
                    }
                    print(f"  {item_name}: ¥{last} (手动维护，保留上次)")
                continue

            # 在线抓取
            result = search_lcsc(item_info["search"])
            if result:
                price, _ = result
                prev_price = get_last_price(history, cat_name, item_name)
                trend = determine_trend(price, prev_price)
                results[cat_name]["items"][item_name] = {
                    "price": price,
                    "trend": trend,
                    "unit": item_info["unit"],
                    "source": "lcsc"
                }
                scraped_count += 1
                print(f"  {item_name}: ¥{price} ({trend})")
            else:
                # 抓取失败，保留上次数据
                last = get_last_price(history, cat_name, item_name)
                if last is not None:
                    results[cat_name]["items"][item_name] = {
                        "price": last,
                        "trend": "数据待更新",
                        "unit": item_info["unit"],
                        "source": "fallback"
                    }
                    print(f"  {item_name}: ¥{last} (保留上次)")
                else:
                    print(f"  {item_name}: ❌ 无历史数据")

    return results, scraped_count


def append_to_history(history, results, today):
    """将本周数据追加到历史记录"""
    for cat_name, cat_data in results.items():
        if cat_name not in history["categories"]:
            history["categories"][cat_name] = {"label": cat_data["label"], "items": {}}

        for item_name, item_data in cat_data["items"].items():
            if item_name not in history["categories"][cat_name]["items"]:
                history["categories"][cat_name]["items"][item_name] = {
                    "unit": item_data["unit"],
                    "history": []
                }

            hist_list = history["categories"][cat_name]["items"][item_name]["history"]

            # 检查本周是否已有数据（避免重复）
            if hist_list and hist_list[-1]["date"] == today:
                # 更新本周数据
                hist_list[-1]["price"] = item_data["price"]
                hist_list[-1]["trend"] = item_data["trend"]
            else:
                # 追加新一周数据
                hist_list.append({
                    "date": today,
                    "price": item_data["price"],
                    "trend": item_data["trend"]
                })

    history["last_update"] = today
    return history


def update_html_tables(results, today):
    """更新 index.html 中的阻容感价格表格"""
    if not HTML_FILE.exists():
        print("  ⚠️ index.html 不存在")
        return

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    for cat_name, cat_data in results.items():
        label = cat_data["label"]
        items = cat_data["items"]
        if not items:
            continue

        # 构建新表格行
        rows = []
        for item_name, item_data in items.items():
            price_val = item_data["price"]
            unit = item_data["unit"]
            trend = item_data["trend"]

            # 格式化价格
            if price_val >= 100:
                price_str = f"¥{price_val:,.0f}/{unit.split('/')[-1]}" if '/' in unit else f"¥{price_val:,.0f}"
            elif price_val >= 1:
                price_str = f"¥{price_val:.2f}/{unit.split('/')[-1]}" if '/' in unit else f"¥{price_val:.2f}"
            else:
                price_str = f"¥{price_val}/{unit.split('/')[-1]}" if '/' in unit else f"¥{price_val}"

            # 趋势样式
            if '涨' in trend or '紧' in trend:
                td_class = 'price-up'
            elif '跌' in trend:
                td_class = 'price-down'
            else:
                td_class = 'price-flat'

            # 表头判断（PCB 用"类型"，其他用"型号规格"）
            first_col = "类型" if cat_name == "PCB" else "型号规格"
            rows.append(f'<tr><td>{item_name}</td><td>{price_str}</td><td class="{td_class}">{trend}</td></tr>')

        rows_html = '\n                        '.join(rows)

        # 用正则替换该品类的表格内容
        # 匹配模式：<div class="price-card-title">{label}</div>...<tbody>...</tbody>
        escaped_label = re.escape(label)
        pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>.*?<tbody>)(.*?)(</tbody>)',
            re.DOTALL
        )
        match = pattern.search(html)
        if match:
            html = html[:match.start(2)] + '\n                        ' + rows_html + '\n                    ' + html[match.end(2):]
            print(f"  ✅ {cat_name} 表格已更新")

        # 更新日期
        date_pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>\s*<div class="price-card-sub"[^>]*>)更新日期：[\d-]+'
        )
        html = date_pattern.sub(r'\1更新日期：' + today, html)

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✅ index.html 已更新")


def update_html_charts(history):
    """更新 index.html 中阻容感趋势图的 Chart.js 数据"""
    if not HTML_FILE.exists():
        return

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    # 为每个品类生成图表数据
    chart_configs = []
    for cat_name in ["MLCC", "电阻", "电感"]:
        cat_data = history.get("categories", {}).get(cat_name, {})
        items = cat_data.get("items", {})
        if not items:
            continue

        # 收集所有日期
        all_dates = set()
        for item_data in items.values():
            for h in item_data.get("history", []):
                all_dates.add(h["date"])
        dates_sorted = sorted(all_dates)
        labels = [d[5:] for d in dates_sorted]  # MM-DD 格式

        datasets = []
        colors = ['#3b82f6', '#8b5cf6', '#f472b6', '#fb923c', '#4ade80']
        for i, (item_name, item_data) in enumerate(items.items()):
            price_map = {h["date"]: h["price"] for h in item_data.get("history", [])}
            data_points = [price_map.get(d, None) for d in dates_sorted]
            color = colors[i % len(colors)]
            short_name = item_name.split(' ')[0] if ' ' in item_name else item_name[:8]
            datasets.append({
                "label": short_name,
                "data": data_points,
                "borderColor": color,
                "backgroundColor": color + '1a',
                "fill": True,
                "tension": 0.4,
                "pointRadius": 3
            })

        chart_configs.append({
            "cat": cat_name,
            "labels": labels,
            "datasets": datasets
        })

    # 注入图表初始化代码（在 initCharts 函数末尾追加）
    # 先检查是否已有阻容感图表代码
    if 'passiveChart_MLCC' in html:
        # 已有图表，需要更新数据
        # 删除旧的阻容感图表代码块
        html = re.sub(
            r'// ===== 阻容感趋势图 =====.*?// ===== /阻容感趋势图 =====',
            '', html, flags=re.DOTALL
        )

    chart_js_code = """
    // ===== 阻容感趋势图 =====
"""
    for cfg in chart_configs:
        canvas_id = f"passiveChart_{cfg['cat']}"
        chart_js_code += f"""
    (function() {{
        var canvas = document.getElementById('{canvas_id}');
        if (!canvas) return;
        new Chart(canvas, {{
            type: 'line',
            data: {{
                labels: {json.dumps(cfg['labels'], ensure_ascii=False)},
                datasets: {json.dumps(cfg['datasets'], ensure_ascii=False)}
            }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                plugins: {{ legend: {{ position: 'top', labels: {{ boxWidth: 10, padding: 8, font: {{ size: 10 }} }} }} }},
                scales: {{
                    y: {{ grid: {{ color: 'rgba(255,255,255,0.03)' }} }},
                    x: {{ grid: {{ display: false }} }}
                }}
            }}
        }});
    }})();
"""

    chart_js_code += "    // ===== /阻容感趋势图 =====\n"

    # 在 initCharts 函数末尾（} 之前）插入
    # 找到 LPDDR5X 图表代码块的结束位置
    insert_marker = '// ===== News ====='
    if insert_marker in html:
        html = html.replace(insert_marker, chart_js_code + '\n' + insert_marker)
        print("  ✅ 阻容感趋势图代码已注入")

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def inject_chart_canvases(html):
    """为每个阻容感卡片注入 canvas 元素"""
    canvas_html_template = """
                <div class="chart-container"><canvas id="passiveChart_{cat}"></canvas></div>"""

    for cat_name in ["MLCC", "电阻", "电感"]:
        canvas_id = f"passiveChart_{cat_name}"
        if canvas_id in html:
            continue  # 已存在

        # 在该品类卡片的 manual-notice 之前插入 canvas
        label = TRACK_ITEMS[cat_name]["label"]
        escaped_label = re.escape(label)
        pattern = re.compile(
            r'(<div class="manual-notice">[^<]*📝 数据来源：)',
        )
        # 找到该品类卡片区域
        card_pattern = re.compile(
            r'(<div class="price-card-title">' + escaped_label + r'</div>.*?</table>\s*)(<div class="manual-notice">)',
            re.DOTALL
        )
        match = card_pattern.search(html)
        if match:
            canvas_html = canvas_html_template.format(cat=cat_name)
            html = html[:match.start(2)] + canvas_html + '\n                ' + match.group(2) + html[match.end(2):]
            print(f"  ✅ {cat_name} canvas 已注入")

    return html


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 50)
    print("🔧 阻容感/PCB 价格追踪更新")
    print(f"📅 日期: {today}")
    print("=" * 50)

    # 1. 加载历史
    history = load_history()
    print(f"📂 历史记录: {history.get('last_update', '无')}")

    # 2. 抓取价格
    print("\n📡 开始抓取价格数据...")
    results, scraped_count = scrape_prices(history)
    print(f"\n📊 抓取完成: {scraped_count} 条在线数据")

    # 3. 追加到历史
    history = append_to_history(history, results, today)
    save_history(history)

    # 4. 更新 HTML 表格
    print("\n📝 更新 index.html...")
    update_html_tables(results, today)

    # 5. 注入 canvas 并更新图表
    if HTML_FILE.exists():
        with open(HTML_FILE, 'r', encoding='utf-8') as f:
            html = f.read()
        html = inject_chart_canvases(html)
        with open(HTML_FILE, 'w', encoding='utf-8') as f:
            f.write(html)
    update_html_charts(history)

    # 6. 统计
    total_items = sum(len(cat["items"]) for cat in results.values())
    print(f"\n🎉 完成！共 {total_items} 个物料，{scraped_count} 条在线数据")
    print(f"📁 历史文件: {HISTORY_FILE}")
    print(f"📁 网页文件: {HTML_FILE}")


if __name__ == '__main__':
    main()
