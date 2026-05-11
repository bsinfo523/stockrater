#!/usr/bin/env python3
"""
StockRater - Datenbeschaffungsskript v3
========================================
- Alle Kurse & Marktkapitalisierung in EUR umgerechnet
- Original-Währung wird im JSON mitgespeichert
- Manuelle Aktien aus docs/custom_stocks.txt
- Wechselkurse via Yahoo Finance (kostenlos)

pip install yfinance pandas requests beautifulsoup4 lxml
"""

import yfinance as yf
import pandas as pd
import json
import time
import requests
import os
from datetime import datetime, timedelta
from io import StringIO

MAX_STOCKS  = 10000
DELAY       = 0.4
OUTPUT_FILE = "docs/stocks.json"
CUSTOM_FILE = "docs/custom_stocks.txt"
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; StockRater/1.0)"}

# ─────────────────────────────────────────────
#  WECHSELKURSE → EUR
# ─────────────────────────────────────────────

FX_CACHE = {}

def get_fx_to_eur(currency):
    """Gibt den Faktor zurück, mit dem man eine Fremdwährung in EUR umrechnet."""
    if currency == "EUR":
        return 1.0
    if currency in FX_CACHE:
        return FX_CACHE[currency]
    try:
        # Yahoo Finance Ticker z.B. "USDEUR=X"
        sym = f"{currency}EUR=X"
        t   = yf.Ticker(sym)
        info = t.info
        rate = info.get("regularMarketPrice") or info.get("previousClose")
        if rate:
            FX_CACHE[currency] = round(rate, 6)
            return FX_CACHE[currency]
    except:
        pass
    # Fallback: Standardwerte (werden nur genutzt wenn API versagt)
    fallback = {
        "USD": 0.92, "GBP": 1.17, "CHF": 1.04, "JPY": 0.0062,
        "HKD": 0.118, "CAD": 0.68, "AUD": 0.60, "INR": 0.011,
        "NOK": 0.086, "SEK": 0.088, "DKK": 0.134, "CNY": 0.127,
        "SGD": 0.69, "KRW": 0.00067, "BRL": 0.17, "MXN": 0.047,
    }
    rate = fallback.get(currency, 0.92)
    FX_CACHE[currency] = rate
    return rate

def to_eur(value, currency):
    if value is None: return None
    return round(value * get_fx_to_eur(currency), 4)

def load_fx_rates():
    """Lädt alle gängigen Wechselkurse vorab."""
    currencies = ["USD","GBP","CHF","JPY","HKD","CAD","AUD","INR",
                  "NOK","SEK","DKK","CNY","SGD","KRW","BRL","MXN"]
    print("  Lade Wechselkurse...")
    for cur in currencies:
        rate = get_fx_to_eur(cur)
        print(f"    1 {cur} = {rate:.4f} EUR")
        time.sleep(0.2)

# ─────────────────────────────────────────────
#  WIKIPEDIA-HILFSFUNKTIONEN
# ─────────────────────────────────────────────

def fetch_wiki_table(url, min_rows=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        tables = pd.read_html(StringIO(r.text), flavor="lxml")
        return [t for t in tables if len(t) >= min_rows]
    except Exception as e:
        print(f"    Wiki-Fehler ({url}): {e}")
        return []

def find_col(df, candidates):
    cols_lower = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        for lower, original in cols_lower.items():
            if cand.lower() in lower:
                return original
    return None

# ─────────────────────────────────────────────
#  AKTIENLISTEN VON WIKIPEDIA
# ─────────────────────────────────────────────

def get_sp500():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 400)
    for df in tables:
        sym_col  = find_col(df, ["symbol","ticker"])
        name_col = find_col(df, ["security","company","name"])
        sec_col  = find_col(df, ["sector","gics sector"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip().replace(".","-")
            if sym in ("nan",""): continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym,
                        str(row[sec_col]).strip() if sec_col else "", "S&P 500"))
        if len(out) > 400: return out
    return []

def get_nasdaq100():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/Nasdaq-100", 90)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","security","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip().replace(".","-")
            if sym in ("nan",""): continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "NASDAQ 100"))
        if len(out) > 80: return out
    return []

def get_dax():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/DAX", 35)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol","index"])
        name_col = find_col(df, ["company","name","member"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            sym = sym.replace(".DE","").replace(".de","") + ".DE"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "DAX"))
        if len(out) >= 35: return out
    return []

def get_mdax():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/MDAX", 40)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name","member"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            sym = sym.replace(".DE","") + ".DE"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "MDAX"))
        if len(out) >= 40: return out
    return []

def get_stoxx50():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/Euro_Stoxx_50", 40)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 12: continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "EURO STOXX 50"))
        if len(out) >= 40: return out
    return []

def get_ftse100():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/FTSE_100_Index", 90)
    for df in tables:
        sym_col  = find_col(df, ["epic","ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 8: continue
            sym = sym.replace(".L","") + ".L"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "FTSE 100"))
        if len(out) >= 90: return out
    return []

def get_cac40():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/CAC_40", 35)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "CAC 40"))
        if len(out) >= 35: return out
    return []

def get_ibex35():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/IBEX_35", 30)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "IBEX 35"))
        if len(out) >= 25: return out
    return []

def get_aex():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/AEX_index", 20)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "AEX"))
        if len(out) >= 20: return out
    return []

def get_smi():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/Swiss_Market_Index", 15)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 12: continue
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "SMI"))
        if len(out) >= 15: return out
    return []

def get_nikkei225():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/Nikkei_225", 100)
    for df in tables:
        sym_col  = find_col(df, ["code","ticker","symbol"])
        name_col = find_col(df, ["company","name","english"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if not sym.isdigit(): continue
            out.append((sym + ".T", str(row[name_col]).strip() if name_col else sym, "", "Nikkei"))
        if len(out) >= 100: return out
    return []

def get_asx200():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/S%26P/ASX_200", 100)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol","code"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 8: continue
            sym = sym.replace(".AX","") + ".AX"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "ASX"))
        if len(out) >= 100: return out
    return []

def get_tsx60():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/S%26P/TSX_60", 50)
    for df in tables:
        sym_col  = find_col(df, ["ticker","symbol"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 10: continue
            sym = sym.replace(".TO","") + ".TO"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "TSX"))
        if len(out) >= 50: return out
    return []

def get_nifty50():
    tables = fetch_wiki_table("https://en.wikipedia.org/wiki/NIFTY_50", 40)
    for df in tables:
        sym_col  = find_col(df, ["symbol","ticker","nse"])
        name_col = find_col(df, ["company","name"])
        if not sym_col: continue
        out = []
        for _, row in df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in ("nan","") or len(sym) > 20: continue
            sym = sym.replace(".NS","") + ".NS"
            out.append((sym, str(row[name_col]).strip() if name_col else sym, "", "NIFTY"))
        if len(out) >= 40: return out
    return []

def get_hang_seng():
    return [
        ("0700.HK","Tencent Holdings","","HSI"),
        ("9988.HK","Alibaba Group","","HSI"),
        ("0005.HK","HSBC Holdings","","HSI"),
        ("1299.HK","AIA Group","","HSI"),
        ("0941.HK","China Mobile","","HSI"),
        ("3690.HK","Meituan","","HSI"),
        ("0388.HK","HK Exchanges","","HSI"),
        ("2318.HK","Ping An Insurance","","HSI"),
        ("1810.HK","Xiaomi","","HSI"),
        ("9999.HK","NetEase","","HSI"),
        ("0883.HK","CNOOC","","HSI"),
        ("0011.HK","Hang Seng Bank","","HSI"),
        ("6098.HK","Country Garden Services","","HSI"),
    ]

def get_custom_stocks():
    """Liest manuelle Aktien aus docs/custom_stocks.txt"""
    if not os.path.exists(CUSTOM_FILE):
        # Erstelle Beispieldatei
        os.makedirs(os.path.dirname(CUSTOM_FILE), exist_ok=True)
        with open(CUSTOM_FILE, "w") as f:
            f.write("# Manuelle Aktien – ein Symbol pro Zeile\n")
            f.write("# Format: SYMBOL oder SYMBOL;Name;Sektor;Börse\n")
            f.write("# Beispiele:\n")
            f.write("# AAPL\n")
            f.write("# SAP.DE;SAP SE;Technology;DAX\n")
        return []
    out = []
    with open(CUSTOM_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            parts = [p.strip() for p in line.split(";")]
            sym  = parts[0].upper()
            name = parts[1] if len(parts) > 1 else sym
            sec  = parts[2] if len(parts) > 2 else ""
            exch = parts[3] if len(parts) > 3 else "Manuell"
            out.append((sym, name, sec, exch))
    return out

# ─────────────────────────────────────────────
#  BEWERTUNGSFUNKTIONEN
# ─────────────────────────────────────────────

def is_tech(s):      return s and "tech" in s.lower()
def is_financial(s): return s and any(k in s.lower() for k in ["bank","financial","insurance","real estate","reit"])

def score_roe(roe, s):
    if roe is None: return 0
    p = roe * 100
    return 1 if p > 15 else -1 if p < 10 else 0

def score_eq(eq, s):
    if eq is None: return 0
    thr = (45,30) if is_tech(s) else (10,5) if is_financial(s) else (25,15)
    return 1 if eq > thr[0] else -1 if eq < thr[1] else 0

def score_ebit(m, s):
    if m is None or is_financial(s): return 0
    p = m * 100
    return 1 if p > 12 else -1 if p < 6 else 0

def score_pe(pe, s):
    if pe is None or pe < 0: return -1
    thr = (22,33) if is_tech(s) else (12,16)
    return 1 if pe < thr[0] else -1 if pe > thr[1] else 0

def score_growth(g):
    if g is None: return 0
    p = g * 100
    return 1 if p > 5 else -1 if p < -5 else 0

def score_pbv(pbv, s):
    if pbv is None or is_tech(s): return 0
    return 1 if pbv < 1.5 else -1 if pbv > 2.5 else 0

def price_change_pct(ticker_obj, months):
    try:
        end   = datetime.now()
        start = end - timedelta(days=months * 31)
        hist  = ticker_obj.history(start=start, end=end)
        if len(hist) < 5: return None
        return ((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100
    except: return None

INDEX_CACHE = {}
INDEX_MAP   = {
    "S&P 500":"^GSPC","NASDAQ 100":"^NDX","DAX":"^GDAXI","MDAX":"^MDAXI",
    "EURO STOXX 50":"^STOXX50E","FTSE 100":"^FTSE","CAC 40":"^FCHI",
    "IBEX 35":"^IBEX","AEX":"^AEX","SMI":"^SSMI","Nikkei":"^N225",
    "ASX":"^AXJO","TSX":"^GSPTSE","NIFTY":"^NSEI","HSI":"^HSI",
}

def idx_change(exchange, months):
    key = f"{exchange}_{months}"
    if key not in INDEX_CACHE:
        sym = INDEX_MAP.get(exchange,"^GSPC")
        try:    INDEX_CACHE[key] = price_change_pct(yf.Ticker(sym), months)
        except: INDEX_CACHE[key] = None
    return INDEX_CACHE[key]

# ─────────────────────────────────────────────
#  EINZELNE AKTIE VERARBEITEN
# ─────────────────────────────────────────────

def process(symbol, name, sector, exchange):
    try:
        t    = yf.Ticker(symbol)
        info = t.info
        if not info: return None

        price_orig = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price_orig: return None

        currency = info.get("currency", "USD")
        fx       = get_fx_to_eur(currency)

        # EUR-Werte
        price_eur  = round(price_orig * fx, 4)
        high52_orig = info.get("fiftyTwoWeekHigh")
        high52_eur  = round(high52_orig * fx, 4) if high52_orig else None
        mktcap_orig = info.get("marketCap")
        mktcap_eur  = round(mktcap_orig * fx, 0) if mktcap_orig else None

        sector_a = info.get("sector", sector) or sector
        name_a   = info.get("shortName") or info.get("longName") or name

        # Kennzahlen
        roe      = info.get("returnOnEquity")
        t_eq     = info.get("totalStockholderEquity") or info.get("bookValue", 0)
        t_assets = info.get("totalAssets")
        eq_ratio = round((t_eq / t_assets) * 100, 2) if t_eq and t_assets and t_assets > 0 else None
        ebit_m   = info.get("ebitdaMargins")
        pe       = info.get("trailingPE") or info.get("forwardPE")
        pe_fwd   = info.get("forwardPE")
        pbv      = info.get("priceToBook")
        growth   = info.get("earningsGrowth") or info.get("revenueGrowth")

        # Kursveränderung vs. Index
        c6   = price_change_pct(t, 6)
        c12  = price_change_pct(t, 12)
        i6   = idx_change(exchange, 6)
        i12  = idx_change(exchange, 12)
        d6   = (c6  - i6 ) if c6  is not None and i6  is not None else None
        d12  = (c12 - i12) if c12 is not None and i12 is not None else None

        s_roe  = score_roe(roe, sector_a)
        s_eq   = score_eq(eq_ratio, sector_a)
        s_ebit = score_ebit(ebit_m, sector_a)
        s_pe   = score_pe(pe, sector_a)
        s_pe5  = score_pe(pe_fwd, sector_a)
        s_6m   = (1 if d6  >  5 else -1 if d6  < -5 else 0) if d6  is not None else 0
        s_12m  = (1 if d12 >  5 else -1 if d12 < -5 else 0) if d12 is not None else 0
        s_mom  = 1 if s_6m==1 and s_12m<=0 else -1 if s_6m==-1 and s_12m>=0 else 0
        s_grow = score_growth(growth)
        s_rev  = score_growth(growth)
        s_pbv  = score_pbv(pbv, sector_a)
        total  = s_roe+s_eq+s_ebit+s_pe+s_pe5+s_6m+s_12m+s_mom+s_grow+s_rev+s_pbv

        large = (mktcap_eur or 0) >= 10_000_000_000
        rec   = "buy" if total >= (4 if large else 6) else "sell" if total < 0 else "watch"

        rv = lambda v, d=2: round(v, d) if v is not None else None
        ab = round(((high52_orig - price_orig) / high52_orig) * 100, 2) if high52_orig and price_orig else None

        return {
            "symbol":       symbol,
            "name":         name_a,
            "sector":       sector_a,
            "exchange":     exchange,
            # Originalwerte (für Detailansicht)
            "currency":     currency,
            "priceOrig":    rv(price_orig),
            "high52wOrig":  rv(high52_orig),
            "marketCapOrig": mktcap_orig,
            # EUR-Werte (für Anzeige & Sortierung)
            "price":        price_eur,
            "high52w":      high52_eur,
            "marketCap":    mktcap_eur,
            "fxRate":       fx,
            # Bewertung
            "abstand":      ab,
            "rating":       total,
            "recommendation": rec,
            "details": {
                "eigenkapitalrentabilitaet": {"score": s_roe,  "value": rv(roe*100) if roe else None,       "unit": "%"},
                "eigenkapitalquote":         {"score": s_eq,   "value": eq_ratio,                           "unit": "%"},
                "ebitMarge":                 {"score": s_ebit, "value": rv(ebit_m*100) if ebit_m else None, "unit": "%"},
                "kgvAktuell":                {"score": s_pe,   "value": rv(pe),                             "unit": ""},
                "kgv5Jahre":                 {"score": s_pe5,  "value": rv(pe_fwd),                         "unit": ""},
                "kursVs6M":                  {"score": s_6m,   "value": rv(d6),                             "unit": "%"},
                "kursVs12M":                 {"score": s_12m,  "value": rv(d12),                            "unit": "%"},
                "momentum":                  {"score": s_mom,  "value": None,                               "unit": ""},
                "gewinnwachstum":            {"score": s_grow, "value": rv(growth*100) if growth else None, "unit": "%"},
                "gewinnrevision":            {"score": s_rev,  "value": rv(growth*100) if growth else None, "unit": "%"},
                "quartalszahlen":            {"score": 0,      "value": None,                               "unit": "%"},
                "kbv":                       {"score": s_pbv,  "value": rv(pbv),                            "unit": ""},
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
    print("  StockRater v3 – Datenbeschaffung")
    print("=" * 60)

    # Wechselkurse vorab laden
    print("\n[0/3] Wechselkurse laden...")
    load_fx_rates()

    # Aktienlisten
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
        ("Manuell",       get_custom_stocks),
    ]

    all_stocks, seen = [], set()
    for label, fn in sources:
        try:
            rows  = fn()
            added = 0
            for row in rows:
                sym = row[0]
                if sym not in seen:
                    seen.add(sym)
                    all_stocks.append(row)
                    added += 1
            print(f"  {'✓' if added>0 else '✗'} {label}: {added} Aktien")
        except Exception as e:
            print(f"  ✗ {label}: {e}")

    print(f"\n  Gesamt: {len(all_stocks)} eindeutige Symbole")
    if not all_stocks:
        print("FEHLER: Keine Symbole. Abbruch.")
        return
    if len(all_stocks) > MAX_STOCKS:
        all_stocks = all_stocks[:MAX_STOCKS]

    # Finanzdaten
    print(f"\n[2/3] Finanzdaten abrufen ({len(all_stocks)} Aktien)...")
    results, errors = [], 0
    for i, (symbol, name, sector, exchange) in enumerate(all_stocks):
        print(f"  [{i+1}/{len(all_stocks)}] {symbol:<15} {name[:32]:<32}", end=" ")
        data = process(symbol, name, sector, exchange)
        if data:
            results.append(data)
            icon = {"buy":"✓","watch":"~","sell":"✗"}.get(data["recommendation"],"?")
            print(f"→ {data['rating']:+3d} {icon}  {data['price']:.2f} EUR")
        else:
            errors += 1
            print("→ –")
        time.sleep(DELAY)

    results.sort(key=lambda x: x["rating"], reverse=True)

    # Speichern – bestehende Kursdaten für Merklisten-Verlauf erhalten
    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Alte Verlaufsdaten übernehmen falls vorhanden
    old_history = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
            for s in old_data.get("stocks", []):
                if "priceHistory" in s:
                    old_history[s["symbol"]] = s["priceHistory"]
        except: pass

    today = datetime.now().strftime("%Y-%m-%d")
    for s in results:
        hist = old_history.get(s["symbol"], [])
        # Heutigen Kurs anfügen (nur einmal pro Tag)
        if not hist or hist[-1]["date"] != today:
            hist.append({"date": today, "price": s["price"], "currency": "EUR"})
        s["priceHistory"] = hist

    output = {
        "metadata": {
            "count":     len(results),
            "updatedAt": datetime.now().isoformat(),
            "errors":    errors,
            "version":   "3.0",
            "currency":  "EUR"
        },
        "stocks": results
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    buy   = sum(1 for r in results if r["recommendation"]=="buy")
    watch = sum(1 for r in results if r["recommendation"]=="watch")
    sell  = sum(1 for r in results if r["recommendation"]=="sell")
    print(f"\n  ✓ {len(results)} Aktien gespeichert  ({errors} Fehler)")
    print(f"  Kauf: {buy}  |  Beobachten: {watch}  |  Verkauf: {sell}")
    print(f"\n✅ Fertig!")
    print("=" * 60)

if __name__ == "__main__":
    main()
