#!/usr/bin/env python3
"""
StockRater - Datenbeschaffungsskript
=====================================
Holt Aktienlisten von Wikipedia (robust, spaltenunabhängig)
und Finanzdaten von Yahoo Finance (kostenlos, kein API-Key).

Voraussetzungen:
    pip install yfinance pandas requests beautifulsoup4 lxml

Ausführung:
    python scripts/fetch_stocks.py
"""

import yfinance as yf
import pandas as pd
import json
import time
import requests
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from io import StringIO

# ─────────────────────────────────────────────
#  KONFIGURATION
# ─────────────────────────────────────────────
MAX_STOCKS          = 10000
DELAY               = 0.4   # Sekunden zwischen Yahoo-Anfragen
OUTPUT_FILE         = "docs/stocks.json"
HEADERS             = {"User-Agent": "Mozilla/5.0 (compatible; StockRater/1.0)"}
FX_CACHE = {}

# ─────────────────────────────────────────────
#  HILFSFUNKTION: Wikipedia-Tabelle robust lesen
# ─────────────────────────────────────────────

def fetch_wiki_table(url, min_rows=10):
    """
    Lädt alle Tabellen einer Wikipedia-Seite via BeautifulSoup.
    Gibt Liste von DataFrames zurück, gefiltert auf min_rows Zeilen.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        tables = pd.read_html(StringIO(r.text), flavor="lxml")
        return [t for t in tables if len(t) >= min_rows]
    except Exception as e:
        print(f"    Wiki-Fehler ({url}): {e}")
        return []

def find_col(df, candidates):
    """Findet die erste Spalte deren Name einen der Kandidaten enthält (case-insensitive)."""
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        for lower, original in cols_lower.items():
            if cand.lower() in lower:
                return original
    return None

def extract_tickers(df, sym_hints, name_hints, suffix="", exchange=""):
    """
    Extrahiert (symbol, name, sector, exchange) aus einem DataFrame.
    sym_hints / name_hints: Liste möglicher Spaltennamen-Fragmente.
    """
    sym_col  = find_col(df, sym_hints)
    name_col = find_col(df, name_hints)
    if not sym_col:
        return []
    results = []
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip().replace(".", "-") if "." not in suffix else str(row[sym_col]).strip()
        if sym in ("nan", "", "-", "N/A"):
            continue
        sym = sym + suffix if suffix and not sym.endswith(suffix) else sym
        name = str(row[name_col]).strip() if name_col else sym
        results.append((sym, name, "", exchange))
    return results

# ─────────────────────────────────────────────
#  AKTIENLISTEN
# ─────────────────────────────────────────────

def get_sp500():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    tables = fetch_wiki_table(url, min_rows=400)
    for df in tables:
        sym_col  = find_col(df, ["symbol", "ticker"])
        name_col = find_col(df, ["security", "company", "name"])
        sec_col  = find_col(df, ["sector", "gics sector"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip().replace(".", "-")
            if sym in ("nan", ""):
                continue
            name = str(row[name_col]).strip() if name_col else sym
            sec  = str(row[sec_col]).strip()  if sec_col  else ""
            results.append((sym, name, sec, "S&P 500"))
        if len(results) > 400:
            return results
    return []

def get_nasdaq100():
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    tables = fetch_wiki_table(url, min_rows=90)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "security", "name"])
        if not sym_col:
            continue
        results = extract_tickers(df, ["ticker","symbol"], ["company","security","name"], exchange="NASDAQ 100")
        if len(results) > 80:
            return results
    return []

def get_dax():
    url = "https://en.wikipedia.org/wiki/DAX"
    tables = fetch_wiki_table(url, min_rows=35)
    for df in tables:
        sym_col = find_col(df, ["ticker", "symbol", "index"])
        if not sym_col:
            continue
        name_col = find_col(df, ["company", "name", "member"])
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            # Entferne .DE falls schon vorhanden, füge es dann sauber an
            sym = sym.replace(".DE", "").replace(".de", "") + ".DE"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "DAX"))
        if len(results) >= 35:
            return results
    return []

def get_mdax():
    url = "https://en.wikipedia.org/wiki/MDAX"
    tables = fetch_wiki_table(url, min_rows=40)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name", "member"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            sym = sym.replace(".DE","") + ".DE"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "MDAX"))
        if len(results) >= 40:
            return results
    return []

def get_stoxx50():
    url = "https://en.wikipedia.org/wiki/Euro_Stoxx_50"
    tables = fetch_wiki_table(url, min_rows=40)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = extract_tickers(df, ["ticker","symbol"], ["company","name"], exchange="EURO STOXX 50")
        if len(results) >= 40:
            return results
    return []

def get_ftse100():
    url = "https://en.wikipedia.org/wiki/FTSE_100_Index"
    tables = fetch_wiki_table(url, min_rows=90)
    for df in tables:
        sym_col  = find_col(df, ["epic", "ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 8:
                continue
            sym = sym.replace(".L","") + ".L"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "FTSE 100"))
        if len(results) >= 90:
            return results
    return []

def get_cac40():
    url = "https://en.wikipedia.org/wiki/CAC_40"
    tables = fetch_wiki_table(url, min_rows=35)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "CAC 40"))
        if len(results) >= 35:
            return results
    return []

def get_ibex35():
    url = "https://en.wikipedia.org/wiki/IBEX_35"
    tables = fetch_wiki_table(url, min_rows=30)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "IBEX 35"))
        if len(results) >= 25:
            return results
    return []

def get_aex():
    url = "https://en.wikipedia.org/wiki/AEX_index"
    tables = fetch_wiki_table(url, min_rows=20)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "AEX"))
        if len(results) >= 20:
            return results
    return []

def get_smi():
    url = "https://en.wikipedia.org/wiki/Swiss_Market_Index"
    tables = fetch_wiki_table(url, min_rows=15)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 12:
                continue
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "SMI"))
        if len(results) >= 15:
            return results
    return []

def get_nikkei225():
    url = "https://en.wikipedia.org/wiki/Nikkei_225"
    tables = fetch_wiki_table(url, min_rows=100)
    for df in tables:
        # Nikkei hat oft Zahlen-Codes
        sym_col  = find_col(df, ["code", "ticker", "symbol"])
        name_col = find_col(df, ["company", "name", "english"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or not sym.isdigit():
                continue
            sym = sym + ".T"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "Nikkei"))
        if len(results) >= 100:
            return results
    return []

def get_asx200():
    url = "https://en.wikipedia.org/wiki/S%26P/ASX_200"
    tables = fetch_wiki_table(url, min_rows=100)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol", "code"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 8:
                continue
            sym = sym.replace(".AX","") + ".AX"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "ASX"))
        if len(results) >= 100:
            return results
    return []

def get_tsx60():
    url = "https://en.wikipedia.org/wiki/S%26P/TSX_60"
    tables = fetch_wiki_table(url, min_rows=50)
    for df in tables:
        sym_col  = find_col(df, ["ticker", "symbol"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 10:
                continue
            sym = sym.replace(".TO","") + ".TO"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "TSX"))
        if len(results) >= 50:
            return results
    return []

def get_nifty50():
    url = "https://en.wikipedia.org/wiki/NIFTY_50"
    tables = fetch_wiki_table(url, min_rows=40)
    for df in tables:
        sym_col  = find_col(df, ["symbol", "ticker", "nse"])
        name_col = find_col(df, ["company", "name"])
        if not sym_col:
            continue
        results = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan", "") or len(sym) > 20:
                continue
            sym = sym.replace(".NS","") + ".NS"
            name = str(row[name_col]).strip() if name_col else sym
            results.append((sym, name, "", "NIFTY"))
        if len(results) >= 40:
            return results
    return []

def get_hang_seng():
    """Hang Seng – feste Liste da Wikipedia-Tabelle unzuverlässig"""
    return [
        ("0700.HK", "Tencent Holdings",    "", "HSI"),
        ("9988.HK", "Alibaba Group",        "", "HSI"),
        ("0005.HK", "HSBC Holdings",        "", "HSI"),
        ("1299.HK", "AIA Group",            "", "HSI"),
        ("0941.HK", "China Mobile",         "", "HSI"),
        ("3690.HK", "Meituan",              "", "HSI"),
        ("0388.HK", "HK Exchanges",         "", "HSI"),
        ("2318.HK", "Ping An Insurance",    "", "HSI"),
        ("1810.HK", "Xiaomi",               "", "HSI"),
        ("9999.HK", "NetEase",              "", "HSI"),
        ("0883.HK", "CNOOC",                "", "HSI"),
        ("2382.HK", "Sunny Optical",        "", "HSI"),
        ("0011.HK", "Hang Seng Bank",       "", "HSI"),
        ("1177.HK", "Sino Biopharmaceutical","", "HSI"),
        ("6098.HK", "Country Garden Services","","HSI"),
    ]

# ─────────────────────────────────────────────
#  BEWERTUNGSFUNKTIONEN
# ─────────────────────────────────────────────

def is_tech(sector):
    return sector and "tech" in sector.lower()

def is_financial(sector):
    return sector and any(k in sector.lower() for k in ["bank","financial","insurance","real estate","reit"])

def score_roe(roe, sector):
    if roe is None: return 0
    p = roe * 100
    return 1 if p > 15 else (-1 if p < 10 else 0)

def score_equity_ratio(eq, sector):
    if eq is None: return 0
    thr = (45, 30) if is_tech(sector) else (10, 5) if is_financial(sector) else (25, 15)
    return 1 if eq > thr[0] else (-1 if eq < thr[1] else 0)

def score_ebit(margin, sector):
    if margin is None or is_financial(sector): return 0
    p = margin * 100
    return 1 if p > 12 else (-1 if p < 6 else 0)

def score_pe(pe, sector):
    if pe is None or pe < 0: return -1
    thr = (22, 33) if is_tech(sector) else (12, 16)
    return 1 if pe < thr[0] else (-1 if pe > thr[1] else 0)

def score_growth(g):
    if g is None: return 0
    p = g * 100
    return 1 if p > 5 else (-1 if p < -5 else 0)

def score_pbv(pbv, sector):
    if pbv is None or is_tech(sector): return 0
    return 1 if pbv < 1.5 else (-1 if pbv > 2.5 else 0)

def price_change(ticker_obj, months):
    try:
        end   = datetime.now()
        start = end - timedelta(days=months * 31)
        hist  = ticker_obj.history(start=start, end=end)
        if len(hist) < 5: return None
        return ((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100
    except:
        return None

INDEX_CACHE = {}
INDEX_MAP   = {
    "S&P 500": "^GSPC", "NASDAQ 100": "^NDX", "DAX": "^GDAXI",
    "MDAX": "^MDAXI", "EURO STOXX 50": "^STOXX50E", "FTSE 100": "^FTSE",
    "CAC 40": "^FCHI", "IBEX 35": "^IBEX", "AEX": "^AEX", "SMI": "^SSMI",
    "Nikkei": "^N225", "ASX": "^AXJO", "TSX": "^GSPTSE",
    "NIFTY": "^NSEI", "HSI": "^HSI",
}

def idx_change(exchange, months):
    key = f"{exchange}_{months}"
    if key not in INDEX_CACHE:
        sym = INDEX_MAP.get(exchange, "^GSPC")
        try:
            INDEX_CACHE[key] = price_change(yf.Ticker(sym), months)
        except:
            INDEX_CACHE[key] = None
    return INDEX_CACHE[key]

def abstand(price, high52):
    if not price or not high52 or high52 == 0: return None
    return round(((high52 - price) / high52) * 100, 2)

# ─────────────────────────────────────────────
#  EINZELNE AKTIE VERARBEITEN
# ─────────────────────────────────────────────

def process(symbol, name, sector, exchange):
    try:
        t    = yf.Ticker(symbol)
        info = t.info
        if not info:
            return None

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None

        sector_a  = info.get("sector", sector) or sector
        name_a    = info.get("shortName") or info.get("longName") or name
        currency  = info.get("currency", "USD")
        mktcap    = info.get("marketCap")
        high52    = info.get("fiftyTwoWeekHigh")

        # Finanzkennzahlen
        roe       = info.get("returnOnEquity")
        t_equity  = info.get("totalStockholderEquity") or info.get("bookValue", 0)
        t_assets  = info.get("totalAssets")
        eq_ratio  = round((t_equity / t_assets) * 100, 2) if t_equity and t_assets and t_assets > 0 else None
        ebit_m    = info.get("ebitdaMargins")
        pe        = info.get("trailingPE") or info.get("forwardPE")
        pe_fwd    = info.get("forwardPE")
        pbv       = info.get("priceToBook")
        growth    = info.get("earningsGrowth") or info.get("revenueGrowth")

        # Kursentwicklung vs. Index
        c6  = price_change(t, 6)
        c12 = price_change(t, 12)
        i6  = idx_change(exchange, 6)
        i12 = idx_change(exchange, 12)

        diff6  = (c6  - i6 ) if c6  is not None and i6  is not None else None
        diff12 = (c12 - i12) if c12 is not None and i12 is not None else None

        s_roe  = score_roe(roe, sector_a)
        s_eq   = score_equity_ratio(eq_ratio, sector_a)
        s_ebit = score_ebit(ebit_m, sector_a)
        s_pe   = score_pe(pe, sector_a)
        s_pe5  = score_pe(pe_fwd, sector_a)
        s_6m   = (1 if diff6  >  5 else -1 if diff6  < -5 else 0) if diff6  is not None else 0
        s_12m  = (1 if diff12 >  5 else -1 if diff12 < -5 else 0) if diff12 is not None else 0
        s_mom  = (1 if s_6m == 1 and s_12m <= 0 else -1 if s_6m == -1 and s_12m >= 0 else 0)
        s_grow = score_growth(growth)
        s_rev  = score_growth(growth)   # Näherung
        s_qtr  = 0
        s_pbv  = score_pbv(pbv, sector_a)

        total = s_roe + s_eq + s_ebit + s_pe + s_pe5 + s_6m + s_12m + s_mom + s_grow + s_rev + s_qtr + s_pbv

        large = (mktcap or 0) >= 10_000_000_000
        rec   = "buy" if total >= (4 if large else 6) else "sell" if total < 0 else "watch"

        def rv(v, d=2): return round(v, d) if v is not None else None

        return {
            "symbol":     symbol,
            "name":       name_a,
            "sector":     sector_a,
            "exchange":   exchange,
            "currency":   currency,
            "price":      rv(price),
            "marketCap":  mktcap,
            "high52w":    rv(high52),
            "abstand":    abstand(price, high52),
            "rating":     total,
            "recommendation": rec,
            "details": {
                "eigenkapitalrentabilitaet": {"score": s_roe,  "value": rv(roe*100)  if roe  else None, "unit": "%"},
                "eigenkapitalquote":         {"score": s_eq,   "value": eq_ratio,                        "unit": "%"},
                "ebitMarge":                 {"score": s_ebit, "value": rv(ebit_m*100) if ebit_m else None, "unit": "%"},
                "kgvAktuell":                {"score": s_pe,   "value": rv(pe),                           "unit": ""},
                "kgv5Jahre":                 {"score": s_pe5,  "value": rv(pe_fwd),                       "unit": ""},
                "kursVs6M":                  {"score": s_6m,   "value": rv(diff6),                        "unit": "%"},
                "kursVs12M":                 {"score": s_12m,  "value": rv(diff12),                       "unit": "%"},
                "momentum":                  {"score": s_mom,  "value": None,                             "unit": ""},
                "gewinnwachstum":            {"score": s_grow, "value": rv(growth*100) if growth else None, "unit": "%"},
                "gewinnrevision":            {"score": s_rev,  "value": rv(growth*100) if growth else None, "unit": "%"},
                "quartalszahlen":            {"score": 0,      "value": None,                             "unit": "%"},
                "kbv":                       {"score": s_pbv,  "value": rv(pbv),                          "unit": ""},
            },
            "updatedAt": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"FEHLER {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  StockRater – Datenbeschaffung")
    print("=" * 60)

    print("\n[1/3] Aktienlisten von Wikipedia laden...")
    sources = [
        ("S&P 500",       get_sp500),
        ("NASDAQ 100",    get_nasdaq100),
        ("DAX",           get_dax),
        ("MDAX",          get_mdax),
        ("EURO STOXX 50", get_stoxx50),
        ("FTSE 100",      get_ftse100),
        ("CAC 40",        get_cac40),
        ("IBEX 35",       get_ibex35),
        ("AEX",           get_aex),
        ("SMI",           get_smi),
        ("Nikkei 225",    get_nikkei225),
        ("ASX 200",       get_asx200),
        ("TSX 60",        get_tsx60),
        ("NIFTY 50",      get_nifty50),
        ("Hang Seng",     get_hang_seng),
    ]

    all_stocks, seen = [], set()
    for label, fn in sources:
        try:
            rows = fn()
            added = 0
            for row in rows:
                sym = row[0]
                if sym not in seen:
                    seen.add(sym)
                    all_stocks.append(row)
                    added += 1
            status = "✓" if added > 0 else "✗"
            print(f"  {status} {label}: {added} Aktien")
        except Exception as e:
            print(f"  ✗ {label}: {e}")

    total_list = len(all_stocks)
    print(f"\n  Gesamt: {total_list} eindeutige Symbole")

    if total_list == 0:
        print("FEHLER: Keine Symbole geladen. Abbruch.")
        return

    if total_list > MAX_STOCKS:
        all_stocks = all_stocks[:MAX_STOCKS]

    # ── Finanzdaten von Yahoo Finance ──
    print(f"\n[2/3] Finanzdaten abrufen ({len(all_stocks)} Aktien)...")
    print("  (Kann 20–90 Minuten dauern je nach Anzahl)\n")

    results, errors = [], 0
    for i, (symbol, name, sector, exchange) in enumerate(all_stocks):
        print(f"  [{i+1}/{len(all_stocks)}] {symbol:<15} {name[:35]:<35}", end=" ")
        data = process(symbol, name, sector, exchange)
        if data:
            results.append(data)
            icon = {"buy": "✓", "watch": "~", "sell": "✗"}.get(data["recommendation"], "?")
            print(f"→ {data['rating']:+3d} {icon}")
        else:
            errors += 1
            print("→ –")
        time.sleep(DELAY)

    results.sort(key=lambda x: x["rating"], reverse=True)

    # ── Speichern ──
    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    output = {
        "metadata": {
            "count":     len(results),
            "updatedAt": datetime.now().isoformat(),
            "errors":    errors,
            "version":   "2.0"
        },
        "stocks": results
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    buy   = sum(1 for r in results if r["recommendation"] == "buy")
    watch = sum(1 for r in results if r["recommendation"] == "watch")
    sell  = sum(1 for r in results if r["recommendation"] == "sell")

    print(f"\n  ✓ {len(results)} Aktien gespeichert  ({errors} Fehler)")
    print(f"  Kauf: {buy}  |  Beobachten: {watch}  |  Verkauf: {sell}")
    print(f"\n✅ Fertig!")
    print("=" * 60)

if __name__ == "__main__":
    main()


def fx_rate(currency):
    if not currency or currency == "EUR":
        return 1
    if currency in FX_CACHE:
        return FX_CACHE[currency]
    try:
        data = requests.get(f"https://open.er-api.com/v6/latest/{currency}", timeout=20).json()
        rate = data["rates"]["EUR"]
    except Exception:
        rate = 1
    FX_CACHE[currency] = rate
    return rate
