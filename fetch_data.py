"""
估值看板数据采集脚本（GitHub Actions 调用）
数据源：
- 蛋卷基金 index_eva/dj：63 个指数 PE/PB/分位/ROE/股息率（A股+美股+港股）
- 腾讯行情：VIX 恐慌指数、两市成交额
"""
import json
import re
import sys
from datetime import datetime

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 宽基指数白名单（其余归为行业/主题）
BROAD = {
    "SH000300", "SH000905", "SH000016", "SH000852", "SH000688", "SZ399006",
    "SZ399001", "SH000001", "SZ399005", "SH000010", "SH000009", "SZ399102",
    "SH000903", "SH000922", "SH000015", "SZ399324", "SZ399550", "SH000925",
    "SP500", "NDX", "SPACEVCP", "SPCQVCP", "CSPSADRP",
    "HKHSI", "HKHSCEI", "HKHSTECH",
}
# 中概/港股相关（即使代码前缀是 CSI 也归港股）
HK_KEY = {"CSIH30533", "CSIH11136", "SPHCMSHP", "HKHSSCNE"}
# 明确属于美股的
US_KEY = {"SPACEVCP", "CSPSADRP", "SPCQVCP", "SP500", "NDX"}


def market_of(code):
    if code in HK_KEY or code.startswith("HK"):
        return "hk"
    if code in US_KEY or code.startswith(("SP", "CSP")):
        return "us"
    return "cn"


def kind_of(code):
    return "broad" if code in BROAD else "sector"


def fetch_valuations():
    r = requests.get("https://danjuanfunds.com/djapi/index_eva/dj", headers=UA, timeout=20)
    r.raise_for_status()
    items = r.json()["data"]["items"]
    out = []
    for it in items:
        if not it.get("pe") or it.get("pe_percentile", 0) <= 0:
            continue
        code = it["index_code"]
        market = "hk" if code.startswith(("HK",)) else "us" if code.startswith(("SP", "CSP", "NDX")) else "cn"
        out.append({
            "code": code,
            "name": it["name"],
            "pe": round(it["pe"], 2),
            "pePct": round(it["pe_percentile"] * 100, 1),
            "pb": round(it["pb"], 2),
            "pbPct": round(it["pb_percentile"] * 100, 1),
            "roe": round(it["roe"] * 100, 1),
            "div": round(it["yeild"] * 100, 2),
            "bond": round((it.get("bond_yeild") or 0) * 100, 2),
            "market": market_of(code),
            "kind": kind_of(code),
            "type": it["eva_type"],  # low / mid / high
        })
    return out


def fetch_vix():
    try:
        r = requests.get("https://qt.gtimg.cn/q=usVIX", headers=UA, timeout=15)
        r.encoding = "gbk"
        m = re.search(r'v_usVIX="[^"]*~([^~]+)~\.VIX~([\d.]+)', r.text)
        if m:
            return {"name": m.group(1), "value": float(m.group(2))}
    except Exception:
        pass
    return None


def fetch_turnover():
    """两市成交额（亿元）：上证指数 + 深证成指 的成交额字段"""
    total = 0
    try:
        r = requests.get("https://qt.gtimg.cn/q=sh000001,sz399001", headers=UA, timeout=15)
        r.encoding = "gbk"
        for sec in re.findall(r'v_(?:sh|sz)\d+="([^"]+)"', r.text):
            f = sec.split("~")
            if len(f) > 37:
                amt = float(f[37])  # 成交额（万元）
                total += amt
        return round(total / 10000, 0)  # 亿元
    except Exception:
        return None


def summarize(vals, label):
    """计算一个分组（市场或大类）的温度与统计"""
    if not vals:
        return None
    pcts = [v["pePct"] for v in vals]
    return {
        "label": label,
        "count": len(vals),
        "temp": round(sum(pcts) / len(pcts), 1),
        "low": sum(1 for v in vals if v["pePct"] < 30),
        "mid": sum(1 for v in vals if 30 <= v["pePct"] < 70),
        "high": sum(1 for v in vals if v["pePct"] >= 70),
    }


def main():
    vals = fetch_valuations()
    if not vals:
        print("估值数据为空，退出")
        return 1

    markets = {}
    for m in ("cn", "us", "hk"):
        s = summarize([v for v in vals if v["market"] == m], m)
        if s:
            markets[m] = s
    markets["all"] = summarize(vals, "all")

    # 股债性价比：沪深300 盈利收益率(1/PE) ÷ 10年国债收益率
    hs300 = next((v for v in vals if v["code"] == "SH000300"), None)
    erp = None
    if hs300 and hs300["pe"] > 0 and hs300["bond"] > 0:
        ep = 100.0 / hs300["pe"]
        erp = round(ep / hs300["bond"], 2)

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "markets": markets,
        "vix": fetch_vix(),
        "turnover": fetch_turnover(),
        "erp": erp,
        "hs300_ep": round(100.0 / hs300["pe"], 2) if hs300 and hs300["pe"] > 0 else None,
        "hs300_bond": hs300["bond"] if hs300 else None,
        "indices": vals,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("data.json 完成", {k: v["temp"] for k, v in markets.items()}, "指数数", len(vals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
