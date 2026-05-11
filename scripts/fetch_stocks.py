#!/usr/bin/env python3
"""
StockRater - Datenbeschaffungsskript v4
========================================
Wechselkurse via frankfurter.app (EZB-Tageskurse, kostenlos, kein API-Key).
Formel: 1 EUR = FX_RATES[currency] Einheiten Fremdwährung
        Fremdwährungsbetrag / FX_RATES[currency] = EUR-Betrag

pip install yfinance pandas requests beautifulsoup4 lxml
"""

import yfinance as yf
import pandas as pd
import json, time, requests, os
from datetime import datetime, timedelta
from io import StringIO

MAX_STOCKS  = 10000
DELAY       = 0.4
OUTPUT_FILE = "docs/stocks.json"
CUSTOM_FILE = "docs/custom_stocks.txt"
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; StockRater/1.0)"}

# FX_RATES["USD"] = 1.12 → 1 EUR = 1.12 USD → 1 USD = 1/1.12 EUR
FX_RATES = {}

# ─────────────────────────────────────────────
#  WECHSELKURSE
# ─────────────────────────────────────────────

def setup_fx():
    """Lädt Wechselkurse: frankfurter.app → yfinance → Hardcode"""
    global FX_RATES

    # Versuch 1: frankfurter.app (EZB-Tageskurse)
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        FX_RATES = data.get("rates", {})
        FX_RATES["EUR"] = 1.0
        print(f"  ✓ frankfurter.app: {len(FX_RATES)} Kurse (Stand {data.get('date','?')})")
        _print_fx_sample()
        return
    except Exception as e:
        print(f"  ✗ frankfurter.app: {e}")

    # Versuch 2: yfinance FX-Ticker
    print("  → Fallback: yfinance FX-Ticker")
    FX_RATES = {"EUR": 1.0}
    for cur in ["USD","GBP","CHF","JPY","HKD","CAD","AUD","INR",
                "NOK","SEK","DKK","CNY","SGD","KRW","BRL","MXN"]:
        try:
            # EURCUR=X → 1 EUR = X Fremdwährung
            t = yf.Ticker(f"EUR{cur}=X")
            info = t.info
            rate = info.get("regularMarketPrice") or info.get("previousClose")
            if rate and rate > 0:
                FX_RATES[cur] = round(float(rate), 6)
                print(f"    1 EUR = {rate:.4f} {cur}")
            time.sleep(0.2)
        except Exception as e2:
            print(f"    ✗ {cur}: {e2}")

    if len(FX_RATES) > 5:
        print(f"  ✓ yfinance: {len(FX_RATES)} Kurse")
        return

    # Versuch 3: Hardcode-Notfallwerte
    print("  ⚠ Hardcode-Fallback (nur Näherung!)")
    FX_RATES = {
        "EUR":1.0, "USD":1.123, "GBP":0.861, "CHF":0.931,
        "JPY":163.45, "HKD":8.741, "CAD":1.562, "AUD":1.723,
        "INR":95.82, "NOK":11.54, "SEK":10.93, "DKK":7.463,
        "CNY":8.134, "SGD":1.512, "KRW":1567.3, "BRL":6.32,
        "MXN":21.45, "TWD":36.8, "ZAR":21.2, "TRY":38.5,
    }

def _print_fx_sample():
    for cur in ["USD","GBP","CHF","JPY","HKD","AUD","CAD","INR"]:
        if cur in FX_RATES:
            eur = round(1.0 / FX_RATES[cur], 4)
            print(f"    1 {cur} = {eur:.4f} EUR  (1 EUR = {FX_RATES[cur]} {cur})")

def to_eur(value, currency):
    """Rechnet Fremdwährungsbetrag in EUR um."""
    if value is None or currency is None: return None
    if currency == "EUR": return round(float(value), 4)
    rate = FX_RATES.get(currency)
    if not rate or rate <= 0:
        print(f"    ⚠ Unbekannte Währung: {currency}")
        return None
    return round(float(value) / rate, 4)

# ─────────────────────────────────────────────
#  WIKIPEDIA PARSING
# ─────────────────────────────────────────────

def fetch_wiki(url, min_rows=10):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return [t for t in pd.read_html(StringIO(r.text), flavor="lxml") if len(t) >= min_rows]
    except Exception as e:
        print(f"    Wiki-Fehler: {e}")
        return []

def col(df, hints):
    low = {str(c).lower(): c for c in df.columns}
    for h in hints:
        for k, v in low.items():
            if h.lower() in k: return v
    return None

def parse_index(url, min_rows, sym_hints, name_hints, suffix, exchange, min_out):
    for df in fetch_wiki(url, min_rows):
        sc = col(df, sym_hints); nc = col(df, name_hints)
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if s in ("nan","") or len(s) > 12: continue
            if suffix and not s.endswith(suffix):
                s = s.replace(suffix,"") + suffix
            n = str(row[nc]).strip() if nc else s
            out.append((s, n, "", exchange))
        if len(out) >= min_out: return out
    return []

# Index-spezifische Funktionen
def get_sp500():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 400):
        sc = col(df,["symbol","ticker"]); nc = col(df,["security","company","name"]); xc = col(df,["sector","gics"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip().replace(".","-")
            if s in ("nan",""): continue
            out.append((s, str(row[nc]).strip() if nc else s, str(row[xc]).strip() if xc else "", "S&P 500"))
        if len(out) > 400: return out
    return []

def get_nasdaq100():
    return parse_index("https://en.wikipedia.org/wiki/Nasdaq-100", 90, ["ticker","symbol"], ["company","security","name"], "", "NASDAQ 100", 80)

def get_dax():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/DAX", 35):
        sc = col(df,["ticker","symbol","index"]); nc = col(df,["company","name","member"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if s in ("nan","") or len(s) > 10: continue
            s = s.replace(".DE","") + ".DE"
            out.append((s, str(row[nc]).strip() if nc else s, "", "DAX"))
        if len(out) >= 35: return out
    return []

def get_mdax():
    return parse_index("https://en.wikipedia.org/wiki/MDAX", 40, ["ticker","symbol"], ["company","name","member"], ".DE", "MDAX", 40)

def get_stoxx50():
    return parse_index("https://en.wikipedia.org/wiki/Euro_Stoxx_50", 40, ["ticker","symbol"], ["company","name"], "", "EURO STOXX 50", 40)

def get_ftse100():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/FTSE_100_Index", 90):
        sc = col(df,["epic","ticker","symbol"]); nc = col(df,["company","name"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if s in ("nan","") or len(s) > 8: continue
            s = s.replace(".L","") + ".L"
            out.append((s, str(row[nc]).strip() if nc else s, "", "FTSE 100"))
        if len(out) >= 90: return out
    return []

def get_cac40():    return parse_index("https://en.wikipedia.org/wiki/CAC_40",          35, ["ticker","symbol"], ["company","name"], "", "CAC 40",       35)
def get_ibex35():   return parse_index("https://en.wikipedia.org/wiki/IBEX_35",         30, ["ticker","symbol"], ["company","name"], "", "IBEX 35",      25)
def get_aex():      return parse_index("https://en.wikipedia.org/wiki/AEX_index",       20, ["ticker","symbol"], ["company","name"], "", "AEX",          20)
def get_smi():      return parse_index("https://en.wikipedia.org/wiki/Swiss_Market_Index", 15, ["ticker","symbol"], ["company","name"], "", "SMI",        15)
def get_asx200():   return parse_index("https://en.wikipedia.org/wiki/S%26P/ASX_200",  100, ["ticker","symbol","code"], ["company","name"], ".AX", "ASX", 100)
def get_tsx60():    return parse_index("https://en.wikipedia.org/wiki/S%26P/TSX_60",    50, ["ticker","symbol"], ["company","name"], ".TO", "TSX",        50)
def get_nifty50():  return parse_index("https://en.wikipedia.org/wiki/NIFTY_50",        40, ["symbol","ticker","nse"], ["company","name"], ".NS", "NIFTY", 40)

def get_nikkei225():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/Nikkei_225", 100):
        sc = col(df,["code","ticker","symbol"]); nc = col(df,["company","name","english"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if not s.isdigit(): continue
            out.append((s+".T", str(row[nc]).strip() if nc else s, "", "Nikkei"))
        if len(out) >= 100: return out
    return []

def get_hang_seng():
    return [
        ("0700.HK","Tencent Holdings","","HSI"), ("9988.HK","Alibaba Group","","HSI"),
        ("0005.HK","HSBC Holdings","","HSI"),    ("1299.HK","AIA Group","","HSI"),
        ("0941.HK","China Mobile","","HSI"),     ("3690.HK","Meituan","","HSI"),
        ("0388.HK","HK Exchanges","","HSI"),     ("2318.HK","Ping An Insurance","","HSI"),
        ("1810.HK","Xiaomi","","HSI"),           ("9999.HK","NetEase","","HSI"),
        ("0883.HK","CNOOC","","HSI"),            ("0011.HK","Hang Seng Bank","","HSI"),
    ]

def get_custom():
    if not os.path.exists(CUSTOM_FILE):
        os.makedirs(os.path.dirname(CUSTOM_FILE), exist_ok=True)
        with open(CUSTOM_FILE,"w") as f:
            f.write("# Manuelle Aktien\n# Format: SYMBOL oder SYMBOL;Name;Sektor;Börse\n")
        return []
    out = []
    with open(CUSTOM_FILE,"r",encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            p = [x.strip() for x in line.split(";")]
            out.append((p[0].upper(), p[1] if len(p)>1 else p[0],
                        p[2] if len(p)>2 else "", p[3] if len(p)>3 else "Manuell"))
    return out

# ─────────────────────────────────────────────
#  BEWERTUNG
# ─────────────────────────────────────────────

def is_tech(s): return bool(s and "tech" in s.lower())
def is_fin(s):  return bool(s and any(k in s.lower() for k in ["bank","financial","insurance","real estate","reit"]))

def sc_roe(v,s):
    if v is None: return 0
    p=v*100; return 1 if p>15 else -1 if p<10 else 0
def sc_eq(v,s):
    if v is None: return 0
    t=(45,30) if is_tech(s) else (10,5) if is_fin(s) else (25,15)
    return 1 if v>t[0] else -1 if v<t[1] else 0
def sc_ebit(v,s):
    if v is None or is_fin(s): return 0
    p=v*100; return 1 if p>12 else -1 if p<6 else 0
def sc_pe(v,s):
    if v is None or v<0: return -1
    t=(22,33) if is_tech(s) else (12,16)
    return 1 if v<t[0] else -1 if v>t[1] else 0
def sc_gr(v):
    if v is None: return 0
    p=v*100; return 1 if p>5 else -1 if p<-5 else 0
def sc_pbv(v,s):
    if v is None or is_tech(s): return 0
    return 1 if v<1.5 else -1 if v>2.5 else 0

def pchg(tk, months):
    try:
        h = tk.history(start=datetime.now()-timedelta(days=months*31), end=datetime.now())
        if len(h)<5: return None
        return ((h["Close"].iloc[-1]-h["Close"].iloc[0])/h["Close"].iloc[0])*100
    except: return None

IDX_CACHE = {}
IDX_MAP = {
    "S&P 500":"^GSPC","NASDAQ 100":"^NDX","DAX":"^GDAXI","MDAX":"^MDAXI",
    "EURO STOXX 50":"^STOXX50E","FTSE 100":"^FTSE","CAC 40":"^FCHI","IBEX 35":"^IBEX",
    "AEX":"^AEX","SMI":"^SSMI","Nikkei":"^N225","ASX":"^AXJO","TSX":"^GSPTSE",
    "NIFTY":"^NSEI","HSI":"^HSI",
}
def idx_chg(exch, months):
    k = f"{exch}_{months}"
    if k not in IDX_CACHE:
        try: IDX_CACHE[k] = pchg(yf.Ticker(IDX_MAP.get(exch,"^GSPC")), months)
        except: IDX_CACHE[k] = None
    return IDX_CACHE[k]

# ─────────────────────────────────────────────
#  EINZELNE AKTIE
# ─────────────────────────────────────────────

def process(symbol, name, sector, exchange):
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info: return None

        price_orig = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price_orig: return None

        currency = info.get("currency","USD")

        # ── KORREKTE EUR-UMRECHNUNG ──
        # FX_RATES[currency] = Anzahl Fremdwährungseinheiten pro 1 EUR
        # Beispiel: FX_RATES["USD"] = 1.12 → 1 USD = 1/1.12 = 0.8929 EUR
        price_eur   = to_eur(price_orig, currency)
        h52_orig    = info.get("fiftyTwoWeekHigh")
        h52_eur     = to_eur(h52_orig, currency)
        mcap_orig   = info.get("marketCap")
        mcap_eur    = to_eur(mcap_orig, currency)
        if price_eur is None: return None

        sec  = info.get("sector", sector) or sector
        name = info.get("shortName") or info.get("longName") or name

        roe    = info.get("returnOnEquity")
        teq    = info.get("totalStockholderEquity") or info.get("bookValue",0)
        tass   = info.get("totalAssets")
        eqr    = round((teq/tass)*100,2) if teq and tass and tass>0 else None
        ebit   = info.get("ebitdaMargins")
        pe     = info.get("trailingPE") or info.get("forwardPE")
        pefwd  = info.get("forwardPE")
        pbv    = info.get("priceToBook")
        growth = info.get("earningsGrowth") or info.get("revenueGrowth")

        c6=pchg(t,6); c12=pchg(t,12)
        i6=idx_chg(exchange,6); i12=idx_chg(exchange,12)
        d6  = (c6 -i6 ) if c6  is not None and i6  is not None else None
        d12 = (c12-i12) if c12 is not None and i12 is not None else None

        r_roe=sc_roe(roe,sec); r_eq=sc_eq(eqr,sec); r_eb=sc_ebit(ebit,sec)
        r_pe=sc_pe(pe,sec);    r_pe5=sc_pe(pefwd,sec)
        r_6m  = (1 if d6 >5 else -1 if d6 <-5 else 0) if d6  is not None else 0
        r_12m = (1 if d12>5 else -1 if d12<-5 else 0) if d12 is not None else 0
        r_mom = 1 if r_6m==1 and r_12m<=0 else -1 if r_6m==-1 and r_12m>=0 else 0
        r_gr=sc_gr(growth); r_rev=sc_gr(growth); r_pbv=sc_pbv(pbv,sec)
        total = r_roe+r_eq+r_eb+r_pe+r_pe5+r_6m+r_12m+r_mom+r_gr+r_rev+r_pbv

        large = (mcap_eur or 0) >= 10_000_000_000
        rec   = "buy" if total>=(4 if large else 6) else "sell" if total<0 else "watch"
        rv    = lambda v,d=2: round(float(v),d) if v is not None else None
        ab    = round(((h52_orig-price_orig)/h52_orig)*100,2) if h52_orig and price_orig and h52_orig>0 else None

        return {
            "symbol":symbol, "name":name, "sector":sec, "exchange":exchange,
            "currency":currency, "priceOrig":rv(price_orig), "high52wOrig":rv(h52_orig),
            "marketCapOrig":mcap_orig,
            "price":rv(price_eur), "high52w":rv(h52_eur), "marketCap":rv(mcap_eur,0),
            "fxRate":FX_RATES.get(currency,1.0),
            "abstand":ab, "rating":total, "recommendation":rec,
            "details":{
                "eigenkapitalrentabilitaet":{"score":r_roe,  "value":rv(roe*100)    if roe    else None,"unit":"%"},
                "eigenkapitalquote":        {"score":r_eq,   "value":eqr,                               "unit":"%"},
                "ebitMarge":                {"score":r_eb,   "value":rv(ebit*100)   if ebit   else None,"unit":"%"},
                "kgvAktuell":               {"score":r_pe,   "value":rv(pe),                            "unit":""},
                "kgv5Jahre":                {"score":r_pe5,  "value":rv(pefwd),                         "unit":""},
                "kursVs6M":                 {"score":r_6m,   "value":rv(d6),                            "unit":"%"},
                "kursVs12M":                {"score":r_12m,  "value":rv(d12),                           "unit":"%"},
                "momentum":                 {"score":r_mom,  "value":None,                              "unit":""},
                "gewinnwachstum":           {"score":r_gr,   "value":rv(growth*100) if growth else None,"unit":"%"},
                "gewinnrevision":           {"score":r_rev,  "value":rv(growth*100) if growth else None,"unit":"%"},
                "quartalszahlen":           {"score":0,      "value":None,                              "unit":"%"},
                "kbv":                      {"score":r_pbv,  "value":rv(pbv),                           "unit":""},
            },
            "updatedAt":datetime.now().isoformat()
        }
    except Exception as e:
        print(f"  FEHLER {symbol}: {e}"); return None

# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────

def main():
    print("="*60)
    print("  StockRater v4 – Datenbeschaffung")
    print("="*60)

    print("\n[0/3] Wechselkurse laden...")
    setup_fx()
    if not FX_RATES:
        print("FEHLER: Keine Wechselkurse. Abbruch."); return

    print("\n[1/3] Aktienlisten laden...")
    sources = [
        ("S&P 500",get_sp500), ("NASDAQ 100",get_nasdaq100), ("DAX",get_dax),
        ("MDAX",get_mdax), ("EURO STOXX 50",get_stoxx50), ("FTSE 100",get_ftse100),
        ("CAC 40",get_cac40), ("IBEX 35",get_ibex35), ("AEX",get_aex), ("SMI",get_smi),
        ("Nikkei 225",get_nikkei225), ("ASX 200",get_asx200), ("TSX 60",get_tsx60),
        ("NIFTY 50",get_nifty50), ("Hang Seng",get_hang_seng), ("Manuell",get_custom),
    ]
    all_stocks, seen = [], set()
    for label, fn in sources:
        try:
            rows=fn(); added=0
            for row in rows:
                if row[0] not in seen:
                    seen.add(row[0]); all_stocks.append(row); added+=1
            print(f"  {'✓' if added>0 else '✗'} {label}: {added}")
        except Exception as e: print(f"  ✗ {label}: {e}")

    print(f"\n  Gesamt: {len(all_stocks)} Symbole")
    if not all_stocks: print("FEHLER: Keine Symbole."); return
    if len(all_stocks)>MAX_STOCKS: all_stocks=all_stocks[:MAX_STOCKS]

    print(f"\n[2/3] Finanzdaten abrufen ({len(all_stocks)} Aktien)...")
    results, errors = [], 0
    for i,(symbol,name,sector,exchange) in enumerate(all_stocks):
        print(f"  [{i+1}/{len(all_stocks)}] {symbol:<14} {name[:28]:<28}", end=" ")
        data=process(symbol,name,sector,exchange)
        if data:
            results.append(data)
            icon={"buy":"✓","watch":"~","sell":"✗"}.get(data["recommendation"],"?")
            fx_note=f"({data['currency']}÷{data['fxRate']})" if data["currency"]!="EUR" else ""
            print(f"→ {data['rating']:+3d} {icon}  {data['price']:.2f}€ {fx_note}")
        else:
            errors+=1; print("→ –")
        time.sleep(DELAY)

    results.sort(key=lambda x:x["rating"],reverse=True)

    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    old_history={}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE,"r",encoding="utf-8") as f:
                for s in json.load(f).get("stocks",[]):
                    if "priceHistory" in s: old_history[s["symbol"]]=s["priceHistory"]
        except: pass

    today=datetime.now().strftime("%Y-%m-%d")
    for s in results:
        hist=old_history.get(s["symbol"],[])
        if not hist or hist[-1]["date"]!=today:
            hist.append({"date":today,"price":s["price"],"currency":"EUR"})
        s["priceHistory"]=hist

    output={
        "metadata":{
            "count":len(results),"updatedAt":datetime.now().isoformat(),
            "errors":errors,"version":"4.0","currency":"EUR",
            "fxSource":"frankfurter.app (EZB)",
            "fxRates":{k:f"1 EUR = {v} {k}" for k,v in FX_RATES.items() if k!="EUR"}
        },
        "stocks":results
    }
    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        json.dump(output,f,ensure_ascii=False,indent=2)

    buy=sum(1 for r in results if r["recommendation"]=="buy")
    watch=sum(1 for r in results if r["recommendation"]=="watch")
    sell=sum(1 for r in results if r["recommendation"]=="sell")
    print(f"\n  ✓ {len(results)} gespeichert  ({errors} Fehler)")
    print(f"  Kauf:{buy}  Beobachten:{watch}  Verkauf:{sell}")
    usd_rate = round(1/FX_RATES.get("USD",1.12),4)
    print(f"  FX-Beispiel: 1 USD = {usd_rate} EUR")
    print(f"\n✅ Fertig!")
    print("="*60)

if __name__=="__main__":
    main()
