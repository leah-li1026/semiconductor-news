#!/usr/bin/env python3
"""
半导体情报站 - LLM智能分析生成
功能：读取价格历史数据 -> 调用LLM生成分析 -> 输出 _analysis_data.json
覆盖：今日五大要点、股票映射、产业机会、涨价预警

环境变量：
  LLM_API_KEY   - API密钥（必需）
  LLM_BASE_URL  - API端点（可选，默认 https://api.openai.com/v1）
  LLM_MODEL     - 模型名（可选，默认 gpt-4o-mini）
"""

import json
import sys
import io
import os
from datetime import datetime, timedelta
from pathlib import Path

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = Path(__file__).parent
STORAGE_FILE = SCRIPT_DIR / '_storage_history.json'
PASSIVE_FILE = SCRIPT_DIR / 'passive_history.json'
OUTPUT_FILE = SCRIPT_DIR / '_analysis_data.json'


def load_json(path):
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def compute_storage_changes(storage_data):
    """计算存储价格的周/月变化"""
    dates = sorted(storage_data.keys())
    if len(dates) < 2:
        return {}

    latest = storage_data[dates[-1]]
    prev = storage_data[dates[-2]] if len(dates) >= 2 else {}
    month_ago = storage_data[dates[-5]] if len(dates) >= 5 else storage_data[dates[0]]

    changes = {}
    for category in ['dram', 'rdimm', 'lpddr', 'enterprise_ssd', 'consumer_ssd', 'nand_wafer']:
        if category not in latest:
            continue
        changes[category] = {}
        for product, price in latest[category].items():
            prev_price = prev.get(category, {}).get(product)
            month_price = month_ago.get(category, {}).get(product)
            entry = {'price': price, 'date': dates[-1]}
            if prev_price and prev_price > 0:
                entry['week_pct'] = round((price - prev_price) / prev_price * 100, 1)
            if month_price and month_price > 0:
                entry['month_pct'] = round((price - month_price) / month_price * 100, 1)
            changes[category][product] = entry

    return {'dates': dates, 'changes': changes}


def compute_passive_changes(passive_data):
    """计算阻容感价格变化"""
    categories = passive_data.get('categories', {})
    changes = {}
    for cat_name, cat_data in categories.items():
        changes[cat_name] = {}
        for item_name, item_data in cat_data.get('items', {}).items():
            changes[cat_name][item_name] = {}
            for brand_name, brand_data in item_data.get('brands', {}).items():
                hist = brand_data.get('history', [])
                if len(hist) < 2:
                    continue
                latest = hist[-1]
                prev = hist[-2]
                month = hist[-5] if len(hist) >= 5 else hist[0]
                entry = {
                    'price': latest['price'],
                    'date': latest['date'],
                    'trend': latest.get('trend', ''),
                }
                if prev['price'] > 0:
                    entry['week_pct'] = round((latest['price'] - prev['price']) / prev['price'] * 100, 1)
                if month['price'] > 0:
                    entry['month_pct'] = round((latest['price'] - month['price']) / month['price'] * 100, 1)
                changes[cat_name][item_name][brand_name] = entry

    return changes


def build_prompt(storage_changes, passive_changes):
    """构建LLM提示词"""
    today = datetime.now().strftime('%Y-%m-%d')

    storage_lines = []
    for cat, products in storage_changes.get('changes', {}).items():
        for prod, info in products.items():
            week = info.get('week_pct', 0)
            month = info.get('month_pct', 0)
            storage_lines.append(f"  {cat}/{prod}: ${info['price']} (周{week:+.1f}%, 月{month:+.1f}%)")
    storage_text = '\n'.join(storage_lines)

    passive_lines = []
    for cat, items in passive_changes.items():
        for item, brands in items.items():
            for brand, info in brands.items():
                week = info.get('week_pct', 0)
                month = info.get('month_pct', 0)
                passive_lines.append(f"  {cat}/{item}/{brand}: ¥{info['price']} (周{week:+.1f}%, 月{month:+.1f}%)")
    passive_text = '\n'.join(passive_lines)

    prompt = f"""你是半导体行业分析师。基于以下最新价格数据，生成今日情报站的分析内容。
日期：{today}

## 存储芯片最新价格及变化
{storage_text}

## 阻容感最新价格及变化
{passive_text}

请严格按照以下JSON格式输出，不要添加任何其他文字：

{{
  "highlights": [
    {{"num": 1, "title": "简短标题（15字内）", "desc": "50-80字详细描述，包含具体数据", "tag": "暴涨|涨价|待传导|降价|企稳|紧缺|放量"}},
    ...共5条
  ],
  "stock_mapping": [
    {{
      "category": "存储芯片|服务器|AI基础设施|被动元件",
      "signal": "emoji+信号文字",
      "signal_color": "red|yellow|gray",
      "title": "产品名",
      "price_line": "价格范围+变化描述",
      "stocks": [
        {{"name": "公司名", "tag": "🟢利好描述|🟡承压描述|🔴利空描述"}},
        ...
      ],
      "note": "💡 一句话分析"
    }},
    ...共6-8条
  ],
  "opportunities": {{
    "alerts": [
      {{"name": "emoji 产品名", "tag": "tag-buy|tag-watch|tag-strong", "text": "简短描述"}},
      ...共6-8条
    ],
    "supply_advice": [
      {{"name": "产品名", "url": "数据来源URL", "tag": "tag-buy|tag-watch|tag-strong", "text": "emoji 建议"}},
      ...共6-8条
    ]
  }}
}}

分析要求：
1. highlights优先选择涨幅/跌幅最大的产品，包含具体数字
2. stock_mapping中每个产品关联2-4家上市公司
3. 涨幅>10%标🔴暴涨，5-10%标🔥涨价，<5%标➡️企稳
4. 所有数据必须来自上面提供的真实价格数据，不要编造
"""

    return prompt


def call_llm(prompt):
    """调用LLM API"""
    api_key = os.environ.get('LLM_API_KEY', '')
    base_url = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
    model = os.environ.get('LLM_MODEL', 'gpt-4o-mini')

    if not api_key:
        print("  ⚠️ LLM_API_KEY 未设置，跳过LLM分析")
        return None

    try:
        import requests
    except ImportError:
        print("  ⚠️ requests 未安装")
        return None

    url = f"{base_url}/chat/completions"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是半导体行业分析师，擅长基于价格数据生成简洁的情报分析。只输出JSON，不要其他文字。'},
            {'role': 'user', 'content': prompt}
        ],
        'temperature': 0.3,
        'max_tokens': 3000,
    }

    try:
        print(f"  📡 调用LLM API ({model})...")
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        if '```json' in content:
            content = content.split('```json')[1].split('```')[0]
        elif '```' in content:
            content = content.split('```')[1].split('```')[0]
        return json.loads(content.strip())
    except Exception as e:
        print(f"  ❌ LLM调用失败: {e}")
        return None


def generate_template_fallback(storage_changes, passive_changes):
    """无LLM时的模板回退"""
    today = datetime.now().strftime('%Y-%m-%d')
    highlights = []
    num = 1

    all_changes = []
    for cat, products in storage_changes.get('changes', {}).items():
        for prod, info in products.items():
            week_pct = info.get('week_pct', 0)
            month_pct = info.get('month_pct', 0)
            all_changes.append((cat, prod, info['price'], week_pct, month_pct))

    all_changes.sort(key=lambda x: abs(x[4]), reverse=True)

    for cat, prod, price, week_pct, month_pct in all_changes[:3]:
        if abs(month_pct) >= 10:
            tag = '暴涨' if month_pct > 0 else '降价'
        elif abs(month_pct) >= 5:
            tag = '涨价' if month_pct > 0 else '降价'
        else:
            tag = '企稳'

        pct_str = f"+{month_pct:.1f}%" if month_pct > 0 else f"{month_pct:.1f}%"
        highlights.append({
            'num': num,
            'title': f'{prod} 月涨{pct_str}' if month_pct > 0 else f'{prod} 月跌{pct_str}',
            'desc': f'{prod}最新报价${price}，月度变化{pct_str}。',
            'tag': tag,
        })
        num += 1

    for cat, items in passive_changes.items():
        if num > 5:
            break
        for item, brands in items.items():
            if num > 5:
                break
            for brand, info in brands.items():
                if num > 5:
                    break
                month_pct = info.get('month_pct', 0)
                if abs(month_pct) >= 5:
                    pct_str = f"+{month_pct:.1f}%" if month_pct > 0 else f"{month_pct:.1f}%"
                    highlights.append({
                        'num': num,
                        'title': f'{item} {brand} {pct_str}',
                        'desc': f'{cat}{item}({brand})最新¥{info["price"]}，月度变化{pct_str}。',
                        'tag': '涨价' if month_pct > 0 else '降价',
                    })
                    num += 1

    while len(highlights) < 5:
        highlights.append({
            'num': len(highlights) + 1,
            'title': '市场整体趋稳',
            'desc': '本周半导体主要品类价格波动收窄，市场进入消化期。',
            'tag': '企稳',
        })

    return {
        'date': today,
        'generated_by': 'template',
        'highlights': highlights[:5],
        'stock_mapping': [],
        'opportunities': {'alerts': [], 'supply_advice': []},
    }


def main():
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 50)
    print("🧠 半导体情报站 - LLM智能分析")
    print(f"📅 日期: {today}")
    print("=" * 50)

    print("\n📊 加载价格数据...")
    storage = load_json(STORAGE_FILE)
    passive = load_json(PASSIVE_FILE)

    storage_changes = compute_storage_changes(storage)
    passive_changes = compute_passive_changes(passive)
    print(f"  存储: {sum(len(v) for v in storage_changes.get('changes', {}).values())} 条产品")
    print(f"  阻容感: {sum(sum(len(b) for b in v.values()) for v in passive_changes.values())} 条品牌数据")

    prompt = build_prompt(storage_changes, passive_changes)
    result = call_llm(prompt)

    if result is None:
        print("\n⚠️ 使用模板回退生成分析...")
        result = generate_template_fallback(storage_changes, passive_changes)

    result['date'] = today
    result['generated_by'] = result.get('generated_by', 'llm')

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 分析数据已保存: {OUTPUT_FILE}")

    highlights = result.get('highlights', [])
    if highlights:
        print(f"\n⭐ 今日五大要点:")
        for h in highlights:
            print(f"  {h.get('num', '?')}. [{h.get('tag', '')}] {h.get('title', '')}")

    print(f"\n🎉 分析完成！")


if __name__ == '__main__':
    main()
