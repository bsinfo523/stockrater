#!/usr/bin/env python3
"""
StockRater - Datenbeschaffungsskript v5
========================================
Fixes:
- DAX: robusteres Parsing, erkennt Ticker-Spalte zuverlässig
- GBp: Britische Pence werden korrekt als GBP/100 behandelt
- Symbole mit Punkt im Namen (BT.A.L, BIP.UN.TO): suffix-Logik repariert
- parse_index: verhindert dass Zahlen/Kurse als Ticker landen
- Allgemein: strengere Symbol-Validierung

pip install yfinance pandas requests beautifulsoup4 lxml
"""

import yfinance as yf
import pandas as pd
import json, time, requests, os, re
from datetime import datetime, timedelta
from io import StringIO

MAX_STOCKS  = 10000
DELAY       = 0.4
OUTPUT_FILE = "docs/stocks.json"
CUSTOM_FILE = "docs/custom_stocks.txt"
HEADERS     = {"User-Agent": "Mozilla/5.0 (compatible; StockRater/1.0)"}

FX_RATES = {}  # 1 EUR = X Fremdwährung

# ─────────────────────────────────────────────
#  SYMBOL-VALIDIERUNG
# ─────────────────────────────────────────────

# Gültige Ticker: nur Buchstaben, Ziffern, Punkte, Bindestriche
# KEINE Minuszeichen am Anfang, keine Kommas, keine Leerzeichen
SYM_RE = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{0,14}$')

def is_valid_symbol(s):
    """Prüft ob ein String ein plausibler Ticker ist."""
    if not s or s in ("nan", "N/A", "-", ""):
        return False
    # Muss mit Buchstabe oder Ziffer beginnen
    if not SYM_RE.match(s):
        return False
    # Keine reinen Zahlen mit Komma (Kurswerte wie "1,234.56")
    if re.match(r'^[\d,.\-]+$', s):
        return False
    # Muss mindestens einen Buchstaben enthalten
    if not any(c.isalpha() for c in s):
        return False
    return True

def clean_suffix(s, suffix):
    """
    Fügt Suffix korrekt an – berücksichtigt Symbole mit Punkt im Namen.
    Beispiel: 'BT.A' + '.L' → 'BT.A.L'  (nicht 'BT.A.L.L')
              'BP'   + '.L' → 'BP.L'
    """
    if not suffix:
        return s
    if s.endswith(suffix):
        return s
    # Entferne nur das Suffix am Ende, nicht mitten im Symbol
    base = s[:-len(suffix)] if s.endswith(suffix) else s
    return base + suffix

# ─────────────────────────────────────────────
#  WECHSELKURSE
# ─────────────────────────────────────────────

def setup_fx():
    global FX_RATES

    # Versuch 1: frankfurter.app (EZB)
    try:
        r = requests.get("https://api.frankfurter.app/latest?from=EUR",
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        FX_RATES = data.get("rates", {})
        FX_RATES["EUR"] = 1.0
        # GBp (Pence) = GBP / 100
        if "GBP" in FX_RATES:
            FX_RATES["GBp"] = FX_RATES["GBP"] * 100
            FX_RATES["GBX"] = FX_RATES["GBP"] * 100
        print(f"  ✓ frankfurter.app: {len(FX_RATES)} Kurse (Stand {data.get('date','?')})")
        for cur in ["USD","GBP","GBp","CHF","JPY","HKD","AUD","CAD","INR"]:
            if cur in FX_RATES:
                eur = round(1.0/FX_RATES[cur], 4)
                print(f"    1 {cur} = {eur:.4f} EUR")
        return
    except Exception as e:
        print(f"  ✗ frankfurter.app: {e}")

    # Versuch 2: Hardcode
    print("  ⚠ Nutze Hardcode-Werte")
    FX_RATES = {
        "EUR":1.0,"USD":1.1761,"GBP":0.8641,"CHF":0.9156,
        "JPY":184.37,"HKD":9.2067,"CAD":1.6063,"AUD":1.6259,
        "INR":111.13,"NOK":11.54,"SEK":10.93,"DKK":7.463,
        "CNY":8.134,"SGD":1.512,"KRW":1567.3,"BRL":6.32,"MXN":21.45,
    }
    FX_RATES["GBp"] = FX_RATES["GBP"] * 100
    FX_RATES["GBX"] = FX_RATES["GBP"] * 100

def to_eur(value, currency):
    """Rechnet Betrag in Fremdwährung korrekt in EUR um."""
    if value is None or currency is None: return None
    if currency == "EUR": return round(float(value), 4)
    # GBp/GBX = britische Pence = GBP/100
    rate = FX_RATES.get(currency) or FX_RATES.get(currency.upper())
    if not rate or rate <= 0:
        print(f"    ⚠ Unbekannte Währung: {currency} – übersprungen")
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
        print(f"    Wiki-Fehler ({url.split('/')[-1]}): {e}")
        return []

def find_col(df, hints):
    """Findet Spalte anhand von Schlüsselwörtern (case-insensitive)."""
    low = {str(c).lower(): c for c in df.columns}
    for h in hints:
        for k, v in low.items():
            if h.lower() in k: return v
    return None

def find_ticker_col(df):
    """
    Findet die Ticker-Spalte zuverlässig.
    Prüft zusätzlich ob die Spalte wirklich Ticker enthält (nicht Kurswerte).
    """
    candidates = ["ticker","symbol","code","epic","isin"]
    for hint in candidates:
        c = find_col(df, [hint])
        if c is None: continue
        # Stichprobe: mindestens 50% der Werte müssen gültige Ticker sein
        sample = df[c].dropna().head(20).astype(str)
        valid = sum(1 for s in sample if is_valid_symbol(s.strip()))
        if valid >= len(sample) * 0.5:
            return c
    return None

def parse_generic(url, min_rows, sym_hints, name_hints, suffix, exchange, min_out,
                  extra_filter=None):
    """
    Generischer Index-Parser mit robuster Symbol-Validierung.
    extra_filter: optionale Funktion die (symbol_str) → bool
    """
    for df in fetch_wiki(url, min_rows):
        # Ticker-Spalte robust suchen
        sc = None
        for hint in sym_hints:
            c = find_col(df, [hint])
            if c is None: continue
            sample = df[c].dropna().head(20).astype(str)
            valid = sum(1 for s in sample if is_valid_symbol(s.strip()))
            if valid >= len(sample) * 0.4:
                sc = c; break

        nc = find_col(df, name_hints)
        if sc is None: continue

        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if not is_valid_symbol(s): continue
            if extra_filter and not extra_filter(s): continue
            # Suffix korrekt anhängen
            s_final = clean_suffix(s, suffix)
            if not is_valid_symbol(s_final): continue
            n = str(row[nc]).strip() if nc else s_final
            if n in ("nan",""): n = s_final
            out.append((s_final, n, "", exchange))

        if len(out) >= min_out:
            return out
    return []

# ─────────────────────────────────────────────
#  AKTIENLISTEN
# ─────────────────────────────────────────────

def get_sp500():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", 400):
        sc = find_col(df,["symbol","ticker"])
        nc = find_col(df,["security","company","name"])
        xc = find_col(df,["sector","gics"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            # S&P 500 nutzt . statt - (BF.B → BF-B)
            s = s.replace(".","-")
            if not is_valid_symbol(s): continue
            n = str(row[nc]).strip() if nc else s
            x = str(row[xc]).strip() if xc else ""
            out.append((s, n, x, "S&P 500"))
        if len(out) > 400: return out
    return []

def get_nasdaq100():
    return parse_generic(
        "https://en.wikipedia.org/wiki/Nasdaq-100", 90,
        ["ticker","symbol"], ["company","security","name"],
        "", "NASDAQ 100", 80
    )

def get_dax():
    """
    DAX-Seite hat mehrere Tabellen. Die Ticker-Tabelle hat eine Spalte
    mit echten Kürzeln wie 'ADS', 'ALV', nicht Kurswerte.
    """
    for df in fetch_wiki("https://en.wikipedia.org/wiki/DAX", 35):
        sc = find_ticker_col(df)
        nc = find_col(df, ["company","name","member","unternehmen"])
        if sc is None: continue

        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if not is_valid_symbol(s): continue
            # Deutsche Ticker: max 4-5 Buchstaben, nur Buchstaben/Ziffern
            if len(s) > 8: continue
            # .DE anhängen wenn nicht vorhanden
            if not s.endswith(".DE"):
                s = s + ".DE"
            n = str(row[nc]).strip() if nc else s
            if n in ("nan",""): n = s
            out.append((s, n, "", "DAX"))

        if len(out) >= 35: return out
    return []

def get_mdax():
    return parse_generic(
        "https://en.wikipedia.org/wiki/MDAX", 40,
        ["ticker","symbol"], ["company","name","member"],
        ".DE", "MDAX", 40,
        extra_filter=lambda s: len(s.replace(".DE","")) <= 8
    )

def get_stoxx50():
    return parse_generic(
        "https://en.wikipedia.org/wiki/Euro_Stoxx_50", 40,
        ["ticker","symbol"], ["company","name"],
        "", "EURO STOXX 50", 40
    )

def get_ftse100():
    """
    FTSE: Symbole enden auf .L, können aber Punkte enthalten (BT.A.L).
    Daher darf der Punkt im Symbol nicht entfernt werden.
    """
    for df in fetch_wiki("https://en.wikipedia.org/wiki/FTSE_100_Index", 90):
        sc = find_col(df,["epic","ticker","symbol"])
        nc = find_col(df,["company","name"])
        if not sc: continue
        # Stichprobe prüfen
        sample = df[sc].dropna().head(10).astype(str)
        valid = sum(1 for s in sample if re.match(r'^[A-Z]{1,5}$', s.strip()))
        if valid < 5: continue  # Falsche Tabelle

        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if not re.match(r'^[A-Z0-9]{1,5}(\.[A-Z])?$', s): continue
            s_final = s + ".L"
            n = str(row[nc]).strip() if nc else s_final
            if n in ("nan",""): n = s_final
            out.append((s_final, n, "", "FTSE 100"))

        if len(out) >= 90: return out
    return []

def get_cac40():
    return parse_generic(
        "https://en.wikipedia.org/wiki/CAC_40", 35,
        ["ticker","symbol"], ["company","name"],
        "", "CAC 40", 35
    )

def get_ibex35():
    return parse_generic(
        "https://en.wikipedia.org/wiki/IBEX_35", 30,
        ["ticker","symbol"], ["company","name"],
        "", "IBEX 35", 25
    )

def get_aex():
    return parse_generic(
        "https://en.wikipedia.org/wiki/AEX_index", 20,
        ["ticker","symbol"], ["company","name"],
        "", "AEX", 20
    )

def get_smi():
    return parse_generic(
        "https://en.wikipedia.org/wiki/Swiss_Market_Index", 15,
        ["ticker","symbol"], ["company","name"],
        "", "SMI", 15
    )

def get_nikkei225():
    for df in fetch_wiki("https://en.wikipedia.org/wiki/Nikkei_225", 100):
        sc = find_col(df,["code","ticker","symbol"])
        nc = find_col(df,["company","name","english"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            # Nikkei-Codes sind 4-stellige Zahlen
            if not re.match(r'^\d{4}$', s): continue
            n = str(row[nc]).strip() if nc else s
            out.append((s+".T", n, "", "Nikkei"))
        if len(out) >= 100: return out
    return []

def get_asx200():
    """
    ASX: Ticker sind 2-3 Buchstaben, manchmal mit Ziffern.
    Keine Punkt-Symbole bei ASX.
    """
    return parse_generic(
        "https://en.wikipedia.org/wiki/S%26P/ASX_200", 100,
        ["ticker","symbol","code"], ["company","name"],
        ".AX", "ASX", 100,
        extra_filter=lambda s: re.match(r'^[A-Z0-9]{1,6}$', s.replace(".AX",""))
    )

def get_tsx60():
    """
    TSX: Manche Symbole haben Klassen-Suffix (RCI.B, CTC.A).
    Diese sollen als RCI-B.TO bzw. CTC-A.TO behandelt werden.
    """
    for df in fetch_wiki("https://en.wikipedia.org/wiki/S%26P/TSX_60", 50):
        sc = find_col(df,["ticker","symbol"])
        nc = find_col(df,["company","name"])
        if not sc: continue
        out = []
        for _, row in df.iterrows():
            s = str(row[sc]).strip()
            if not re.match(r'^[A-Z]{1,6}(\.[A-Z])?$', s): continue
            # Punkte in Symbol bleiben: RCI.B → RCI.B.TO (Yahoo-Format)
            s_final = s + ".TO"
            n = str(row[nc]).strip() if nc else s_final
            if n in ("nan",""): n = s_final
            out.append((s_final, n, "", "TSX"))
        if len(out) >= 50: return out
    return []

def get_nifty50():
    return parse_generic(
        "https://en.wikipedia.org/wiki/NIFTY_50", 40,
        ["symbol","ticker","nse"], ["company","name"],
        ".NS", "NIFTY", 40,
        extra_filter=lambda s: re.match(r'^[A-Z&]{1,20}$', s.replace(".NS","").replace("-",""))
    )

def get_hang_seng():
    # Feste Liste – Wikipedia-Tabelle unzuverlässig für HK-Nummern
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
        ("0175.HK","Geely Automobile","","HSI"),
        ("2020.HK","ANTA Sports","","HSI"),
        ("6862.HK","Haidilao","","HSI"),
        ("9618.HK","JD.com","","HSI"),
    ]

def get_custom():
    """
    Liest manuelle Aktien aus custom_stocks.txt.
    Kommentierte Zeilen (# ...) werden übersprungen.
    Gibt Liste von (symbol, name, sector, exchange) zurück.
    """
    if not os.path.exists(CUSTOM_FILE):
        os.makedirs(os.path.dirname(CUSTOM_FILE), exist_ok=True)
        with open(CUSTOM_FILE,"w",encoding="utf-8") as f:
            f.write(
                "# Manuelle Aktien – ein Symbol pro Zeile\n"
                "# Format: SYMBOL  oder  SYMBOL;Name;Sektor;Boerse\n"
                "# Bereits in einem Index vorhandene Aktien werden automatisch\n"
                "# am Ende des Runs auskommentiert um Duplikate zu vermeiden.\n"
                "#\n"
                "# Beispiele:\n"
                "# NEL.OL;Nel ASA;Energy;Oslo\n"
                "# NOVO-B.CO;Novo Nordisk;Healthcare;OMXC\n"
            )
        return []
    out = []
    with open(CUSTOM_FILE,"r",encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            p = [x.strip() for x in line.split(";")]
            sym = p[0].upper()
            if not sym: continue
            out.append((sym,
                        p[1] if len(p)>1 else sym,
                        p[2] if len(p)>2 else "",
                        p[3] if len(p)>3 else "Manuell"))
    return out


def update_custom_file(already_in_index: set):
    """
    Kommentiert Einträge in custom_stocks.txt aus, die bereits
    über Wikipedia-Indizes geladen werden – verhindert Duplikate.
    Zeigt im Log welche Symbole bereits abgedeckt sind.
    """
    if not os.path.exists(CUSTOM_FILE):
        return
    with open(CUSTOM_FILE,"r",encoding="utf-8") as f:
        lines = f.readlines()

    changed = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Leere Zeilen und Kommentare unverändert
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        sym = stripped.split(";")[0].strip().upper()
        if sym in already_in_index:
            # Auskommentieren mit Hinweis
            new_lines.append(f"# [auto-kommentiert: bereits in Index] {stripped}\n")
            print(f"  → {sym} bereits über Index abgedeckt – in custom_stocks.txt auskommentiert")
            changed = True
        else:
            new_lines.append(line)

    if changed:
        with open(CUSTOM_FILE,"w",encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"  custom_stocks.txt aktualisiert")

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
    "EURO STOXX 50":"^STOXX50E","FTSE 100":"^FTSE","CAC 40":"^FCHI",
    "IBEX 35":"^IBEX","AEX":"^AEX","SMI":"^SSMI","Nikkei":"^N225",
    "ASX":"^AXJO","TSX":"^GSPTSE","NIFTY":"^NSEI","HSI":"^HSI","Manuell":"^GSPC",
}

def idx_chg(exchange, months):
    k = f"{exchange}_{months}"
    if k not in IDX_CACHE:
        try: IDX_CACHE[k] = pchg(yf.Ticker(IDX_MAP.get(exchange,"^GSPC")), months)
        except: IDX_CACHE[k] = None
    return IDX_CACHE[k]

# ─────────────────────────────────────────────
#  EINZELNE AKTIE VERARBEITEN
# ─────────────────────────────────────────────

def process(symbol, name, sector, exchange):
    try:
        t = yf.Ticker(symbol)
        info = t.info
        if not info: return None

        price_orig = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price_orig: return None

        currency = info.get("currency","USD")

        # GBp/GBX korrekt behandeln (Pence → Pfund → EUR)
        price_eur   = to_eur(price_orig, currency)
        h52_orig    = info.get("fiftyTwoWeekHigh")
        h52_eur     = to_eur(h52_orig, currency)
        mcap_orig   = info.get("marketCap")
        mcap_eur    = to_eur(mcap_orig, currency)

        if price_eur is None: return None

        sec  = info.get("sector", sector) or sector
        name_a = info.get("shortName") or info.get("longName") or name

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
        r_pe=sc_pe(pe,sec); r_pe5=sc_pe(pefwd,sec)
        r_6m  = (1 if d6 >5 else -1 if d6 <-5 else 0) if d6  is not None else 0
        r_12m = (1 if d12>5 else -1 if d12<-5 else 0) if d12 is not None else 0
        r_mom = 1 if r_6m==1 and r_12m<=0 else -1 if r_6m==-1 and r_12m>=0 else 0
        r_gr=sc_gr(growth); r_rev=sc_gr(growth); r_pbv=sc_pbv(pbv,sec)
        total = r_roe+r_eq+r_eb+r_pe+r_pe5+r_6m+r_12m+r_mom+r_gr+r_rev+r_pbv

        large = (mcap_eur or 0) >= 10_000_000_000
        rec   = "buy" if total>=(4 if large else 6) else "sell" if total<0 else "watch"
        rv    = lambda v,d=2: (round(float(v),d) if not math.isnan(float(v)) and not math.isinf(float(v)) else None) if v is not None else None
        ab    = round(((h52_orig-price_orig)/h52_orig)*100,2) if h52_orig and price_orig and h52_orig>0 else None

        # ── ANALYSTEN-DATEN ──────────────────────────────────
        # Yahoo Finance: targetMeanPrice, targetMedianPrice,
        #                targetHighPrice, targetLowPrice,
        #                numberOfAnalystOpinions, recommendationKey
        analyst = None
        try:
            n_analysts  = info.get("numberOfAnalystOpinions")
            tgt_mean    = info.get("targetMeanPrice")
            tgt_median  = info.get("targetMedianPrice")
            tgt_high    = info.get("targetHighPrice")
            tgt_low     = info.get("targetLowPrice")
            rec_key     = info.get("recommendationKey","")  # "buy","hold","sell" etc.

            # Alle Kursziele in EUR umrechnen
            tgt_mean_eur   = to_eur(tgt_mean,   currency) if tgt_mean   else None
            tgt_median_eur = to_eur(tgt_median,  currency) if tgt_median else None
            tgt_high_eur   = to_eur(tgt_high,    currency) if tgt_high   else None
            tgt_low_eur    = to_eur(tgt_low,     currency) if tgt_low    else None

            # Upside = (Kursziel / Kurs - 1) * 100
            upside_mean = None
            if tgt_mean_eur and price_eur and price_eur > 0:
                upside_mean = round((tgt_mean_eur / price_eur - 1) * 100, 1)

            # Analysten-Konsens-Empfehlung normalisieren
            consensus_map = {
                "strongbuy":"Starker Kauf","buy":"Kauf","hold":"Halten",
                "sell":"Verkauf","strongsell":"Starker Verkauf",
                "underperform":"Unterperform","outperform":"Outperform",
                "overweight":"Übergewichten","underweight":"Untergewichten",
                "neutral":"Neutral","market perform":"Marktperform",
            }
            consensus_de = consensus_map.get((rec_key or "").lower(), rec_key or "k.A.")

            if n_analysts and tgt_mean_eur:
                analyst = {
                    "anzahl":        int(n_analysts),
                    "kursziel":      rv(tgt_mean_eur),    # gemischtes Kursziel (Mittelwert) in EUR
                    "kurszielOrig":  rv(tgt_mean),        # in Originalwährung
                    "median":        rv(tgt_median_eur),
                    "medianOrig":    rv(tgt_median),
                    "hoch":          rv(tgt_high_eur),
                    "hochOrig":      rv(tgt_high),
                    "tief":          rv(tgt_low_eur),
                    "tiefOrig":      rv(tgt_low),
                    "upside":        upside_mean,         # % Potenzial vom aktuellen Kurs
                    "konsens":       consensus_de,
                    "konsensKey":    rec_key or "",
                }
        except Exception as ae:
            pass  # Analysten-Daten optional – kein Abbruch

        # ── DIVIDENDENRENDITE ────────────────────────────────
        # Yahoo liefert dividendYield als Dezimalzahl (0.035 = 3.5%)
        # ── DIVIDENDENRENDITE: selbst berechnen aus lastDividendValue ──
        # Zuverlässiger als dividendYield, das Yahoo inkonsistent liefert
        # ── DIVIDENDENRENDITE ─────────────────────────────────────────────────
        # Methode 1: dividendYield aus info (Dezimal, z.B. 0.035 = 3.5%)
        # Methode 2: Historische Dividenden letzter 12 Monate ÷ Kurs
        # Regel: Methode 1 wird NUR übernommen wenn Methode 2 den Wert bestätigt.
        #        Toleranz: ±30% Abweichung zwischen beiden Methoden.
        #        Ist nur Methode 2 verfügbar, wird deren Wert direkt genutzt.
        div_yield_pct = None
        try:
            # Methode 1
            m1 = None
            dy = info.get("dividendYield")
            if dy is not None:
                dy_f = float(dy)
                if not math.isnan(dy_f) and not math.isinf(dy_f) and 0 < dy_f < 0.15:
                    m1 = round(dy_f * 100, 2)

            # Methode 2: Historische Dividenden der letzten 12 Monate
            m2 = None
            try:
                divs = t.dividends
                if divs is not None and len(divs) > 0:
                    cutoff = datetime.now() - timedelta(days=365)
                    try:
                        recent = divs[divs.index >= cutoff.strftime('%Y-%m-%d')]
                    except Exception:
                        recent = divs.iloc[-4:] if len(divs) >= 4 else divs
                    if len(recent) > 0 and price_orig and float(price_orig) > 0:
                        annual_sum = float(recent.sum())
                        raw = (annual_sum / float(price_orig)) * 100
                        if 0.01 < raw < 15:
                            m2 = round(raw, 2)
            except Exception:
                pass

            # Abgleich: beide Methoden müssen innerhalb ±30% übereinstimmen
            if m1 is not None and m2 is not None:
                abw = abs(m1 - m2) / max(m1, m2)   # relative Abweichung
                if abw <= 0.30:
                    div_yield_pct = round((m1 + m2) / 2, 2)  # Mittelwert
                else:
                    # Zu große Abweichung → Methode 2 bevorzugen (echte Zahlungen)
                    div_yield_pct = m2
            elif m2 is not None:
                div_yield_pct = m2   # nur Methode 2 verfügbar
            elif m1 is not None:
                div_yield_pct = None # nur Methode 1 ohne Bestätigung → verwerfen
        except Exception:
            div_yield_pct = None

        return {
            "symbol":symbol, "name":name_a, "sector":sec, "exchange":exchange,
            "currency":currency,
            "priceOrig":rv(price_orig), "high52wOrig":rv(h52_orig),
            "marketCapOrig":mcap_orig,
            "price":rv(price_eur), "high52w":rv(h52_eur), "marketCap":rv(mcap_eur,0),
            "fxRate":FX_RATES.get(currency,1.0),
            "abstand":ab, "rating":total, "recommendation":rec,
            "dividendYield":div_yield_pct,
            "details":{
                "eigenkapitalrentabilitaet":{"score":r_roe,"value":rv(roe*100) if roe else None,"unit":"%"},
                "eigenkapitalquote":        {"score":r_eq, "value":eqr,"unit":"%"},
                "ebitMarge":                {"score":r_eb, "value":rv(ebit*100) if ebit else None,"unit":"%"},
                "kgvAktuell":               {"score":r_pe, "value":rv(pe),"unit":""},
                "kgv5Jahre":                {"score":r_pe5,"value":rv(pefwd),"unit":""},
                "kursVs6M":                 {"score":r_6m, "value":rv(d6),"unit":"%"},
                "kursVs12M":                {"score":r_12m,"value":rv(d12),"unit":"%"},
                "momentum":                 {"score":r_mom,"value":None,"unit":""},
                "gewinnwachstum":           {"score":r_gr, "value":rv(growth*100) if growth else None,"unit":"%"},
                "gewinnrevision":           {"score":r_rev,"value":rv(growth*100) if growth else None,"unit":"%"},
                "quartalszahlen":           {"score":0,    "value":None,"unit":"%"},
                "kbv":                      {"score":r_pbv,"value":rv(pbv),"unit":""},
            },
            "analyst":analyst,
            "updatedAt":datetime.now().isoformat()
        }
    except Exception as e:
        print(f"  FEHLER {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────

import math

class SafeEncoder(json.JSONEncoder):
    """Konvertiert NaN und Infinity zu null – beides ist kein gültiges JSON."""
    def iterencode(self, o, _one_shot=False):
        return super().iterencode(self._clean(o), _one_shot)
    def _clean(self, obj):
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        if isinstance(obj, dict):
            return {k: self._clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self._clean(v) for v in obj]
        return obj


def main():
    print("="*60)
    print("  StockRater v5 – Datenbeschaffung")
    print("="*60)

    print("\n[0/3] Wechselkurse laden...")
    setup_fx()

    print("\n[1/3] Aktienlisten laden...")
    sources = [
        ("S&P 500",get_sp500), ("NASDAQ 100",get_nasdaq100),
        ("DAX",get_dax), ("MDAX",get_mdax),
        ("EURO STOXX 50",get_stoxx50), ("FTSE 100",get_ftse100),
        ("CAC 40",get_cac40), ("IBEX 35",get_ibex35),
        ("AEX",get_aex), ("SMI",get_smi),
        ("Nikkei 225",get_nikkei225), ("ASX 200",get_asx200),
        ("TSX 60",get_tsx60), ("NIFTY 50",get_nifty50),
        ("Hang Seng",get_hang_seng), ("Manuell",get_custom),
    ]

    all_stocks, seen = [], set()
    for label, fn in sources:
        try:
            rows=fn(); added=0
            for row in rows:
                if row[0] not in seen:
                    seen.add(row[0]); all_stocks.append(row); added+=1
            print(f"  {'✓' if added>0 else '✗'} {label}: {added}")
        except Exception as e:
            print(f"  ✗ {label}: {e}")

    print(f"\n  Gesamt: {len(all_stocks)} Symbole")
    if not all_stocks:
        print("FEHLER: Keine Symbole."); return

    # custom_stocks.txt bereinigen: Aktien die bereits über Wikipedia-Indizes
    # abgerufen werden auskommentieren, damit keine Duplikate entstehen.
    # "Manuell"-Einträge werden nie auskommentiert (kommen nur von get_custom).
    index_symbols = {sym for sym,_,_,exch in all_stocks if exch != "Manuell"}
    print(f"\n  Prüfe custom_stocks.txt auf Duplikate ({len(index_symbols)} Index-Symbole)...")
    update_custom_file(index_symbols)

    if len(all_stocks) > MAX_STOCKS:
        all_stocks = all_stocks[:MAX_STOCKS]



    # Alte stocks.json laden – für Fallback bei Fehlern und Verlaufsdaten
    old_stocks_by_sym = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE,"r",encoding="utf-8") as f:
                old_json = json.load(f)
            for s in old_json.get("stocks",[]):
                old_stocks_by_sym[s["symbol"]] = s
            print(f"  Alte stocks.json: {len(old_stocks_by_sym)} Einträge geladen")
        except Exception as e:
            print(f"  ⚠ Alte stocks.json: {e}")

    print(f"\n[2/3] Finanzdaten abrufen ({len(all_stocks)} Aktien)...")
    results, errors = [], 0
    for i,(symbol,name,sector,exchange) in enumerate(all_stocks):
        print(f"  [{i+1}/{len(all_stocks)}] {symbol:<15} {name[:28]:<28}", end=" ")
        data = process(symbol,name,sector,exchange)
        if data:
            # _custom Flag setzen damit Backup-Logik greift
            if exchange == "Manuell":
                data["_custom"] = True
            results.append(data)
            icon={"buy":"✓","watch":"~","sell":"✗"}.get(data["recommendation"],"?")
            cur = data["currency"]
            fx_note = f"({cur}÷{data['fxRate']:.4f})" if cur not in ("EUR","") else "(EUR)"
            print(f"→ {data['rating']:+3d} {icon}  {data['price']:.2f}€ {fx_note}")
        else:
            errors+=1; print("→ –")
            # Bei Fehler: alten custom-Datensatz als Fallback merken
            if exchange == "Manuell" and symbol in old_stocks_by_sym:
                fallback = old_stocks_by_sym[symbol]
                results.append(fallback)
                print(f"    ↩ Fallback: alter Datensatz vom {fallback.get('updatedAt','?')[:10]} übernommen")
        time.sleep(DELAY)

    results.sort(key=lambda x:x["rating"],reverse=True)

    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)


    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Verlaufsdaten auf neue Ergebnisse übertragen
    today = datetime.now().strftime("%Y-%m-%d")
    new_symbols = set()
    for s in results:
        new_symbols.add(s["symbol"])
        old = old_stocks_by_sym.get(s["symbol"],{})
        hist = old.get("priceHistory",[])
        if not hist or hist[-1]["date"] != today:
            hist.append({"date":today,"price":s["price"],"currency":"EUR"})
        s["priceHistory"] = hist

    # Custom-Aktien die dieses Mal fehlgeschlagen sind BEHALTEN
    # (z.B. Yahoo Finance hatte einen Timeout) – mit alten Daten
    custom_syms = {row[0] for row in get_custom()}
    kept_old = []
    for sym, old_s in old_stocks_by_sym.items():
        if sym not in new_symbols and old_s.get("_custom"):
            # Alte custom-Aktie die dieses Mal nicht geladen wurde
            kept_old.append(old_s)
            print(f"  ⚠ {sym}: Fehler beim Abruf – behalte alten Datensatz vom {old_s.get('updatedAt','?')[:10]}")

    if kept_old:
        results.extend(kept_old)
        results.sort(key=lambda x:x["rating"],reverse=True)
        print(f"  {len(kept_old)} alte custom-Aktie(n) aus Backup übernommen")

    output={
        "metadata":{
            "count":len(results),"updatedAt":datetime.now().isoformat(),
            "errors":errors,"version":"5.1","currency":"EUR",
            "fxSource":"frankfurter.app (EZB)",
            "fxRates":{k:f"1 EUR = {v} {k}" for k,v in sorted(FX_RATES.items()) if k!="EUR"}
        },
        "stocks":results
    }
    with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
        # allow_nan=False wirft Fehler bei NaN/Inf statt sie reinzuschreiben.
        # Wir nutzen einen Custom-Encoder der NaN→null konvertiert.
        json.dump(output, f, ensure_ascii=False, indent=2, cls=SafeEncoder)

    buy=sum(1 for r in results if r["recommendation"]=="buy")
    watch=sum(1 for r in results if r["recommendation"]=="watch")
    sell=sum(1 for r in results if r["recommendation"]=="sell")
    print(f"\n  ✓ {len(results)} Aktien gespeichert  ({errors} Fehler)")
    print(f"  Kauf:{buy}  Beobachten:{watch}  Verkauf:{sell}")
    usd = round(1/FX_RATES.get("USD",1.176),4)
    gbp = round(1/FX_RATES.get("GBP",0.864),4)
    gbp_p = round(1/FX_RATES.get("GBp",86.4),6)
    print(f"  FX: 1 USD={usd}€  1 GBP={gbp}€  1 GBp={gbp_p}€")
    print(f"\n✅ Fertig!")
    print("="*60)

if __name__=="__main__":
    main()
