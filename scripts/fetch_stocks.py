#!/usr/bin/env python3
"""
StockRater - Datenbeschaffungsskript
====================================
Dieses Skript lädt Finanzdaten für die größten Aktiengesellschaften
weltweit und berechnet das TransparentShare-Rating (12 Kennzahlen).

Voraussetzungen:
    pip install yfinance pandas requests beautifulsoup4

Ausführung:
    python fetch_stocks.py

Ergebnis:
    stocks.json  → In den GitHub Pages Ordner kopieren
"""

import yfinance as yf
import pandas as pd
import json
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import math

# ─────────────────────────────────────────────
#  KONFIGURATION
# ─────────────────────────────────────────────
MAX_STOCKS = 10000          # Maximale Anzahl Aktien
DELAY_BETWEEN_REQUESTS = 0.5  # Sekunden zwischen API-Anfragen
OUTPUT_FILE = "docs/stocks.json"

# ─────────────────────────────────────────────
#  AKTIENLISTEN ZUSAMMENSTELLEN
# ─────────────────────────────────────────────

def get_sp500_tickers():
    """S&P 500 von Wikipedia"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url)
        df = tables[0]
        tickers = df['Symbol'].tolist()
        names = df['Security'].tolist()
        sectors = df['GICS Sector'].tolist()
        return [(t.replace('.', '-'), n, s, 'S&P 500') for t, n, s in zip(tickers, names, sectors)]
    except Exception as e:
        print(f"Fehler S&P 500: {e}")
        return []

def get_dax_tickers():
    """DAX 40 von Wikipedia"""
    url = "https://en.wikipedia.org/wiki/DAX"
    try:
        tables = pd.read_html(url)
        # Tabelle mit Ticker-Symbolen finden
        for table in tables:
            if 'Ticker symbol' in table.columns or 'Symbol' in table.columns:
                col = 'Ticker symbol' if 'Ticker symbol' in table.columns else 'Symbol'
                name_col = 'Company' if 'Company' in table.columns else table.columns[0]
                tickers = table[col].tolist()
                names = table[name_col].tolist()
                # Yahoo Finance braucht .DE Suffix für deutsche Aktien
                return [(str(t).strip() + '.DE', str(n), 'Various', 'DAX')
                        for t, n in zip(tickers, names) if str(t) != 'nan']
    except Exception as e:
        print(f"Fehler DAX: {e}")
    return []

def get_stoxx50_tickers():
    """EURO STOXX 50"""
    url = "https://en.wikipedia.org/wiki/Euro_Stoxx_50"
    try:
        tables = pd.read_html(url)
        for table in tables:
            cols = [c.lower() for c in table.columns]
            if any('ticker' in c or 'symbol' in c for c in cols):
                sym_col = next(c for c in table.columns if 'ticker' in c.lower() or 'symbol' in c.lower())
                name_col = table.columns[0]
                return [(str(t).strip(), str(n), 'Various', 'EURO STOXX 50')
                        for t, n in zip(table[sym_col], table[name_col]) if str(t) != 'nan']
    except Exception as e:
        print(f"Fehler STOXX 50: {e}")
    return []

def get_nasdaq100_tickers():
    """NASDAQ 100"""
    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    try:
        tables = pd.read_html(url)
        for table in tables:
            if 'Ticker' in table.columns or 'Symbol' in table.columns:
                col = 'Ticker' if 'Ticker' in table.columns else 'Symbol'
                name_col = 'Company' if 'Company' in table.columns else table.columns[0]
                return [(str(t).strip(), str(n), 'Technology', 'NASDAQ 100')
                        for t, n in zip(table[col], table[name_col]) if str(t) != 'nan']
    except Exception as e:
        print(f"Fehler NASDAQ 100: {e}")
    return []

def get_ftse100_tickers():
    """FTSE 100"""
    url = "https://en.wikipedia.org/wiki/FTSE_100_Index"
    try:
        tables = pd.read_html(url)
        for table in tables:
            if 'Ticker' in table.columns or 'EPIC' in table.columns:
                col = 'EPIC' if 'EPIC' in table.columns else 'Ticker'
                name_col = 'Company' if 'Company' in table.columns else table.columns[0]
                return [(str(t).strip() + '.L', str(n), 'Various', 'FTSE 100')
                        for t, n in zip(table[col], table[name_col]) if str(t) != 'nan']
    except Exception as e:
        print(f"Fehler FTSE 100: {e}")
    return []

def get_nikkei_tickers():
    """Nikkei 225 - repräsentative Auswahl"""
    # Bekannte große japanische Unternehmen mit Yahoo Finance Symbolen
    return [
        ('7203.T', 'Toyota Motor', 'Consumer Cyclical', 'Nikkei'),
        ('6758.T', 'Sony Group', 'Technology', 'Nikkei'),
        ('9984.T', 'SoftBank Group', 'Technology', 'Nikkei'),
        ('6501.T', 'Hitachi', 'Industrials', 'Nikkei'),
        ('9432.T', 'NTT', 'Communication', 'Nikkei'),
        ('8306.T', 'Mitsubishi UFJ', 'Financial', 'Nikkei'),
        ('6954.T', 'Fanuc', 'Industrials', 'Nikkei'),
        ('4063.T', 'Shin-Etsu Chemical', 'Basic Materials', 'Nikkei'),
        ('7974.T', 'Nintendo', 'Technology', 'Nikkei'),
        ('6367.T', 'Daikin Industries', 'Industrials', 'Nikkei'),
        ('4502.T', 'Takeda Pharma', 'Healthcare', 'Nikkei'),
        ('8035.T', 'Tokyo Electron', 'Technology', 'Nikkei'),
        ('9983.T', 'Fast Retailing', 'Consumer Cyclical', 'Nikkei'),
    ]

def get_additional_large_caps():
    """Weitere große internationale Unternehmen"""
    return [
        # China / Hong Kong
        ('0700.HK', 'Tencent Holdings', 'Technology', 'HSI'),
        ('9988.HK', 'Alibaba Group', 'Technology', 'HSI'),
        ('3690.HK', 'Meituan', 'Technology', 'HSI'),
        ('1299.HK', 'AIA Group', 'Financial', 'HSI'),
        ('0941.HK', 'China Mobile', 'Communication', 'HSI'),
        # Indien
        ('RELIANCE.NS', 'Reliance Industries', 'Energy', 'NIFTY'),
        ('TCS.NS', 'Tata Consultancy', 'Technology', 'NIFTY'),
        ('HDFCBANK.NS', 'HDFC Bank', 'Financial', 'NIFTY'),
        ('INFY.NS', 'Infosys', 'Technology', 'NIFTY'),
        ('ICICIBANK.NS', 'ICICI Bank', 'Financial', 'NIFTY'),
        # Kanada
        ('SHOP.TO', 'Shopify', 'Technology', 'TSX'),
        ('RY.TO', 'Royal Bank of Canada', 'Financial', 'TSX'),
        ('TD.TO', 'TD Bank', 'Financial', 'TSX'),
        # Australien
        ('BHP.AX', 'BHP Group', 'Basic Materials', 'ASX'),
        ('CBA.AX', 'Commonwealth Bank', 'Financial', 'ASX'),
        # Schweiz
        ('NESN.SW', 'Nestlé', 'Consumer Defensive', 'SMI'),
        ('ROG.SW', 'Roche', 'Healthcare', 'SMI'),
        ('NOVN.SW', 'Novartis', 'Healthcare', 'SMI'),
        ('ABBN.SW', 'ABB', 'Industrials', 'SMI'),
        # Niederlande
        ('ASML.AS', 'ASML Holding', 'Technology', 'AEX'),
        ('INGA.AS', 'ING Group', 'Financial', 'AEX'),
        # Frankreich (EURONEXT)
        ('MC.PA', 'LVMH', 'Consumer Cyclical', 'CAC 40'),
        ('OR.PA', "L'Oréal", 'Consumer Defensive', 'CAC 40'),
        ('SAN.PA', 'Sanofi', 'Healthcare', 'CAC 40'),
        ('TTE.PA', 'TotalEnergies', 'Energy', 'CAC 40'),
        ('AIR.PA', 'Airbus', 'Industrials', 'CAC 40'),
        # Spanien
        ('SAN.MC', 'Banco Santander', 'Financial', 'IBEX 35'),
        ('IBE.MC', 'Iberdrola', 'Utilities', 'IBEX 35'),
        # Dänemark
        ('NOVO-B.CO', 'Novo Nordisk', 'Healthcare', 'OMXC'),
    ]


# ─────────────────────────────────────────────
#  BEWERTUNGSFUNKTIONEN
# ─────────────────────────────────────────────

def is_tech(sector):
    return sector and 'tech' in sector.lower()

def is_financial(sector):
    fin_keywords = ['bank', 'financial', 'insurance', 'real estate', 'reit']
    return sector and any(k in sector.lower() for k in fin_keywords)

def score_roe(roe, sector):
    """Eigenkapitalrentabilität"""
    if roe is None: return 0, None
    roe_pct = roe * 100
    if roe_pct > 15: return 1, roe_pct
    elif roe_pct >= 10: return 0, roe_pct
    else: return -1, roe_pct

def score_equity_ratio(equity_ratio_pct, sector):
    """Eigenkapitalquote (branchenabhängig)"""
    if equity_ratio_pct is None: return 0, None
    if is_tech(sector):
        if equity_ratio_pct > 45: return 1, equity_ratio_pct
        elif equity_ratio_pct >= 30: return 0, equity_ratio_pct
        else: return -1, equity_ratio_pct
    elif is_financial(sector):
        if equity_ratio_pct > 10: return 1, equity_ratio_pct
        elif equity_ratio_pct >= 5: return 0, equity_ratio_pct
        else: return -1, equity_ratio_pct
    else:
        if equity_ratio_pct > 25: return 1, equity_ratio_pct
        elif equity_ratio_pct >= 15: return 0, equity_ratio_pct
        else: return -1, equity_ratio_pct

def score_ebit_margin(ebit_margin, sector):
    """Gewinnmarge (EBIT)"""
    if ebit_margin is None or is_financial(sector): return 0, ebit_margin
    margin_pct = ebit_margin * 100
    if margin_pct > 12: return 1, margin_pct
    elif margin_pct >= 6: return 0, margin_pct
    else: return -1, margin_pct

def score_pe_current(pe, sector):
    """Aktuelles KGV"""
    if pe is None or pe < 0: return -1, pe
    if is_tech(sector):
        if pe < 22: return 1, pe
        elif pe <= 33: return 0, pe
        else: return -1, pe
    else:
        if pe < 12: return 1, pe
        elif pe <= 16: return 0, pe
        else: return -1, pe

def score_pe_5y(pe_5y, sector):
    """Durchschnittliches KGV (5 Jahre, Näherung)"""
    # Gleiche Logik wie aktuelles KGV
    return score_pe_current(pe_5y, sector)

def score_price_vs_index_6m(stock_6m, index_6m):
    """Kursveränderung 6 Monate vs. Index"""
    if stock_6m is None or index_6m is None: return 0, None
    diff = stock_6m - index_6m
    if diff > 5: return 1, diff
    elif diff >= -5: return 0, diff
    else: return -1, diff

def score_price_vs_index_12m(stock_12m, index_12m):
    """Kursveränderung 12 Monate vs. Index"""
    if stock_12m is None or index_12m is None: return 0, None
    diff = stock_12m - index_12m
    if diff > 5: return 1, diff
    elif diff >= -5: return 0, diff
    else: return -1, diff

def score_momentum(score_6m, score_12m):
    """Kursmomentum"""
    if score_6m == 1 and score_12m in (0, -1): return 1
    elif score_6m == -1 and score_12m in (0, 1): return -1
    else: return 0

def score_earnings_growth(growth):
    """Erwartetes Gewinnwachstum"""
    if growth is None: return 0, None
    growth_pct = growth * 100
    if growth_pct > 5: return 1, growth_pct
    elif growth_pct >= -5: return 0, growth_pct
    else: return -1, growth_pct

def score_earnings_revision(rev):
    """Veränderung der Gewinnschätzung (Näherung über analyst target)"""
    if rev is None: return 0, None
    if rev > 0.05: return 1, rev * 100
    elif rev >= -0.05: return 0, rev * 100
    else: return -1, rev * 100

def score_quarterly_reaction(reaction):
    """Reaktion auf Quartalszahlen (Näherung)"""
    if reaction is None: return 0, None
    if reaction > 1: return 1, reaction
    elif reaction >= -1: return 0, reaction
    else: return -1, reaction

def score_pbv(pbv, sector):
    """Kurs-Buchwert-Verhältnis"""
    if pbv is None or is_tech(sector): return 0, pbv
    if pbv < 1.5: return 1, pbv
    elif pbv <= 2.5: return 0, pbv
    else: return -1, pbv

def abstand(current_price, high_52w):
    """Abstand = prozentuale Differenz Kurs zu 52-Wochen-Hoch"""
    if current_price is None or high_52w is None or high_52w == 0:
        return None
    return ((high_52w - current_price) / high_52w) * 100

def get_price_change_pct(ticker_obj, months):
    """Berechnet Kursveränderung der letzten N Monate"""
    try:
        end = datetime.now()
        start = end - timedelta(days=months * 30)
        hist = ticker_obj.history(start=start, end=end)
        if len(hist) < 2:
            return None
        first = hist['Close'].iloc[0]
        last = hist['Close'].iloc[-1]
        return ((last - first) / first) * 100
    except:
        return None

# Näherungswerte für Marktindizes (werden bei jedem Skriptlauf aktualisiert)
INDEX_CHANGES = {}

def get_index_change(index_symbol, months):
    """Holt Indexveränderung"""
    key = f"{index_symbol}_{months}"
    if key in INDEX_CHANGES:
        return INDEX_CHANGES[key]
    try:
        idx = yf.Ticker(index_symbol)
        chg = get_price_change_pct(idx, months)
        INDEX_CHANGES[key] = chg
        return chg
    except:
        return None

INDEX_MAP = {
    'S&P 500': '^GSPC',
    'NASDAQ 100': '^NDX',
    'DAX': '^GDAXI',
    'EURO STOXX 50': '^STOXX50E',
    'FTSE 100': '^FTSE',
    'Nikkei': '^N225',
    'HSI': '^HSI',
    'NIFTY': '^NSEI',
    'TSX': '^GSPTSE',
    'ASX': '^AXJO',
    'SMI': '^SSMI',
    'AEX': '^AEX',
    'CAC 40': '^FCHI',
    'IBEX 35': '^IBEX',
    'OMXC': '^OMXC25',
    'CDAX': '^CDAX',
    'MDAX': '^MDAXI',
}


# ─────────────────────────────────────────────
#  HAUPT-FUNKTION: EINZELNE AKTIE VERARBEITEN
# ─────────────────────────────────────────────

def process_ticker(symbol, name, sector, exchange):
    """Holt Daten und berechnet Rating für eine Aktie"""
    try:
        t = yf.Ticker(symbol)
        info = t.info

        if not info or 'currentPrice' not in info and 'regularMarketPrice' not in info:
            return None

        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        if not current_price:
            return None

        # Basisdaten
        sector_actual = info.get('sector', sector)
        name_actual = info.get('shortName') or info.get('longName') or name
        currency = info.get('currency', 'USD')
        market_cap = info.get('marketCap')
        high_52w = info.get('fiftyTwoWeekHigh')
        ex = info.get('exchange') or exchange

        # Finanzkennzahlen
        roe = info.get('returnOnEquity')
        total_equity = info.get('totalStockholderEquity') or info.get('bookValue')
        total_assets = info.get('totalAssets')
        equity_ratio = None
        if total_equity and total_assets and total_assets > 0:
            equity_ratio = (total_equity / total_assets) * 100

        ebit_margin = info.get('ebitdaMargins')  # Näherung
        pe_current = info.get('trailingPE') or info.get('forwardPE')
        pe_forward = info.get('forwardPE')
        pbv = info.get('priceToBook')
        earnings_growth = info.get('earningsGrowth') or info.get('revenueGrowth')

        # Kursveränderungen
        idx_sym = INDEX_MAP.get(exchange, '^GSPC')
        change_6m = get_price_change_pct(t, 6)
        change_12m = get_price_change_pct(t, 12)
        idx_6m = get_index_change(idx_sym, 6)
        idx_12m = get_index_change(idx_sym, 12)

        # Bewertung der 12 Kennzahlen
        s_roe, v_roe = score_roe(roe, sector_actual)
        s_eq, v_eq = score_equity_ratio(equity_ratio, sector_actual)
        s_ebit, v_ebit = score_ebit_margin(ebit_margin, sector_actual)
        s_pe, v_pe = score_pe_current(pe_current, sector_actual)
        s_pe5, v_pe5 = score_pe_5y(pe_forward, sector_actual)  # Näherung
        s_6m, v_6m = score_price_vs_index_6m(change_6m, idx_6m)
        s_12m, v_12m = score_price_vs_index_12m(change_12m, idx_12m)
        s_mom = score_momentum(s_6m, s_12m)
        s_grow, v_grow = score_earnings_growth(earnings_growth)
        s_rev, v_rev = score_earnings_revision(earnings_growth)  # Näherung
        s_qtr = 0   # Quartalszahlen-Reaktion: Datenpunkt nicht frei verfügbar
        s_pbv, v_pbv = score_pbv(pbv, sector_actual)

        total_score = s_roe + s_eq + s_ebit + s_pe + s_pe5 + s_6m + s_12m + s_mom + s_grow + s_rev + s_qtr + s_pbv

        # Kaufempfehlung
        is_large_cap = (market_cap or 0) >= 10_000_000_000
        buy_threshold = 4 if is_large_cap else 6
        if total_score >= buy_threshold:
            recommendation = "buy"
        elif total_score >= 0:
            recommendation = "watch"
        else:
            recommendation = "sell"

        ab = abstand(current_price, high_52w)

        return {
            "symbol": symbol,
            "name": name_actual,
            "sector": sector_actual,
            "exchange": exchange,
            "currency": currency,
            "price": round(current_price, 2) if current_price else None,
            "marketCap": market_cap,
            "high52w": round(high_52w, 2) if high_52w else None,
            "abstand": round(ab, 2) if ab is not None else None,
            "rating": total_score,
            "recommendation": recommendation,
            "details": {
                "eigenkapitalrentabilitaet": {"score": s_roe, "value": round(v_roe, 2) if v_roe else None, "unit": "%"},
                "eigenkapitalquote": {"score": s_eq, "value": round(v_eq, 2) if v_eq else None, "unit": "%"},
                "ebitMarge": {"score": s_ebit, "value": round(v_ebit, 2) if v_ebit else None, "unit": "%"},
                "kgvAktuell": {"score": s_pe, "value": round(v_pe, 2) if v_pe else None, "unit": ""},
                "kgv5Jahre": {"score": s_pe5, "value": round(v_pe5, 2) if v_pe5 else None, "unit": ""},
                "kursVs6M": {"score": s_6m, "value": round(v_6m, 2) if v_6m else None, "unit": "%"},
                "kursVs12M": {"score": s_12m, "value": round(v_12m, 2) if v_12m else None, "unit": "%"},
                "momentum": {"score": s_mom, "value": None, "unit": ""},
                "gewinnwachstum": {"score": s_grow, "value": round(v_grow, 2) if v_grow else None, "unit": "%"},
                "gewinnrevision": {"score": s_rev, "value": round(v_rev, 2) if v_rev else None, "unit": "%"},
                "quartalszahlen": {"score": s_qtr, "value": None, "unit": "%"},
                "kbv": {"score": s_pbv, "value": round(v_pbv, 2) if v_pbv else None, "unit": ""},
            },
            "updatedAt": datetime.now().isoformat()
        }

    except Exception as e:
        print(f"  FEHLER {symbol}: {e}")
        return None


# ─────────────────────────────────────────────
#  HAUPTPROGRAMM
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  StockRater – Datenbeschaffung")
    print("=" * 60)

    # Aktienlisten zusammenstellen
    print("\n[1/3] Aktienlisten laden...")
    all_stocks = []
    seen = set()

    sources = [
        ("S&P 500", get_sp500_tickers),
        ("NASDAQ 100", get_nasdaq100_tickers),
        ("DAX", get_dax_tickers),
        ("EURO STOXX 50", get_stoxx50_tickers),
        ("FTSE 100", get_ftse100_tickers),
        ("Nikkei", get_nikkei_tickers),
        ("International", get_additional_large_caps),
    ]

    for source_name, func in sources:
        try:
            tickers = func()
            added = 0
            for ticker_data in tickers:
                sym = ticker_data[0]
                if sym not in seen:
                    seen.add(sym)
                    all_stocks.append(ticker_data)
                    added += 1
            print(f"  ✓ {source_name}: {added} Aktien")
        except Exception as e:
            print(f"  ✗ {source_name}: {e}")

    print(f"\n  Gesamt: {len(all_stocks)} eindeutige Symbole")

    # Auf MAX_STOCKS begrenzen
    if len(all_stocks) > MAX_STOCKS:
        all_stocks = all_stocks[:MAX_STOCKS]

    # Daten von yfinance holen
    print(f"\n[2/3] Finanzdaten abrufen ({len(all_stocks)} Aktien)...")
    print("  (Dies kann einige Minuten dauern...)\n")

    results = []
    errors = 0

    for i, (symbol, name, sector, exchange) in enumerate(all_stocks):
        print(f"  [{i+1}/{len(all_stocks)}] {symbol} – {name[:40]}", end=" ")
        stock_data = process_ticker(symbol, name, sector, exchange)
        if stock_data:
            results.append(stock_data)
            rec_icon = {"buy": "✓", "watch": "~", "sell": "✗"}.get(stock_data['recommendation'], '?')
            print(f"→ Rating: {stock_data['rating']:+d} {rec_icon}")
        else:
            errors += 1
            print("→ übersprungen")
        time.sleep(DELAY_BETWEEN_REQUESTS)

    # Sortieren nach Rating (absteigend)
    results.sort(key=lambda x: x['rating'], reverse=True)

    # JSON speichern
    print(f"\n[3/3] Speichern als {OUTPUT_FILE}...")
    import os
    os.makedirs("docs", exist_ok=True)

    output = {
        "metadata": {
            "count": len(results),
            "updatedAt": datetime.now().isoformat(),
            "errors": errors,
            "version": "1.0"
        },
        "stocks": results
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  ✓ {len(results)} Aktien gespeichert")
    print(f"  ✗ {errors} Fehler")
    print(f"\n  Kaufempfehlungen: {sum(1 for r in results if r['recommendation'] == 'buy')}")
    print(f"  Beobachten:      {sum(1 for r in results if r['recommendation'] == 'watch')}")
    print(f"  Verkaufen:       {sum(1 for r in results if r['recommendation'] == 'sell')}")
    print(f"\n✅ Fertig! Kopiere '{OUTPUT_FILE}' in deinen GitHub Pages Ordner.")
    print("=" * 60)


if __name__ == "__main__":
    main()
