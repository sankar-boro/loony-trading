"""
Central instrument registry for Loony Trading.

Single source of truth for all tradable symbols — used by every script,
the backtester, the strategy engine, and the dashboard API.

Each stock entry has:
  isin        — NSE ISIN (forms the Upstox instrument_key: NSE_EQ|{isin})
  name        — Full company name
  sector      — Broad sector (Banking, IT, Energy, ...)
  industry    — Sub-industry
  market_cap  — Large Cap / Mid Cap / Small Cap
  fno         — F&O eligible (can trade futures & options)
  nifty50     — Member of Nifty 50 index
  nifty_next  — Member of Nifty Next 50 index

Every instrument key in the code base comes from here — never hardcode an
ISIN or an "NSE_INDEX|..." string elsewhere (tests/test_instrument_isins.py
enforces it). Look keys up instead:

    INSTRUMENTS["TCS"]                  # stock or index, by symbol
    INDEX_INSTRUMENTS["NIFTY50"]        # "NSE_INDEX|Nifty 50"
    STOCK_UNIVERSE["TCS"]["isin"]       # bare ISIN

Usage:
    from config.instruments import INSTRUMENTS, STOCK_UNIVERSE, get_sector_map

    ikey = INSTRUMENTS["RELIANCE"]           # "NSE_EQ|INE002A01018"
    sector_groups = get_sector_map()         # {"Banking": ["HDFCBANK", ...], ...}
    fno_stocks = get_fno_symbols()           # ["RELIANCE", "TCS", ...]
"""
from __future__ import annotations
from typing import Dict, List

# ── Full stock universe ────────────────────────────────────────────────────────
# fmt: off
STOCK_UNIVERSE: Dict[str, dict] = {

    # ── Banking & Financial Services ─────────────────────────────────────────
    "HDFCBANK":    {"name": "HDFC Bank",                  "isin": "INE040A01034", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ICICIBANK":   {"name": "ICICI Bank",                 "isin": "INE090A01021", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "SBIN":        {"name": "State Bank of India",        "isin": "INE062A01020", "sector": "Banking",      "industry": "PSU Bank",             "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "AXISBANK":    {"name": "Axis Bank",                  "isin": "INE238A01034", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "KOTAKBANK":   {"name": "Kotak Mahindra Bank",        "isin": "INE237A01036", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "INDUSINDBK":  {"name": "IndusInd Bank",              "isin": "INE095A01012", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "BANKBARODA":  {"name": "Bank of Baroda",             "isin": "INE028A01039", "sector": "Banking",      "industry": "PSU Bank",             "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "PNB":         {"name": "Punjab National Bank",       "isin": "INE160A01022", "sector": "Banking",      "industry": "PSU Bank",             "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "CANBK":       {"name": "Canara Bank",                "isin": "INE476A01022", "sector": "Banking",      "industry": "PSU Bank",             "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "FEDERALBNK":  {"name": "Federal Bank",               "isin": "INE171A01029", "sector": "Banking",      "industry": "Private Bank",         "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},
    "BAJFINANCE":  {"name": "Bajaj Finance",              "isin": "INE296A01032", "sector": "Finance",      "industry": "NBFC",                 "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "BAJAJFINSV":  {"name": "Bajaj Finserv",              "isin": "INE918I01026", "sector": "Finance",      "industry": "Financial Services",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "CHOLAFIN":    {"name": "Cholamandalam Investment",   "isin": "INE121A01024", "sector": "Finance",      "industry": "NBFC",                 "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "SHRIRAMFIN":  {"name": "Shriram Finance",            "isin": "INE721A01047", "sector": "Finance",      "industry": "NBFC",                 "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "HDFCLIFE":    {"name": "HDFC Life Insurance",        "isin": "INE795G01014", "sector": "Finance",      "industry": "Life Insurance",       "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "SBILIFE":     {"name": "SBI Life Insurance",         "isin": "INE123W01016", "sector": "Finance",      "industry": "Life Insurance",       "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},

    # ── IT & Software ─────────────────────────────────────────────────────────
    "TCS":         {"name": "Tata Consultancy Services",  "isin": "INE467B01029", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "INFY":        {"name": "Infosys",                    "isin": "INE009A01021", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "WIPRO":       {"name": "Wipro",                      "isin": "INE075A01022", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "HCLTECH":     {"name": "HCL Technologies",           "isin": "INE860A01027", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "TECHM":       {"name": "Tech Mahindra",              "isin": "INE669C01036", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "LTIM":        {"name": "LTIMindtree",                "isin": "INE214T01019", "sector": "IT",           "industry": "IT Services",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "PERSISTENT":  {"name": "Persistent Systems",         "isin": "INE262H01021", "sector": "IT",           "industry": "Software",             "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": True},
    "MPHASIS":     {"name": "Mphasis",                    "isin": "INE356A01018", "sector": "IT",           "industry": "Software",             "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},
    "COFORGE":     {"name": "Coforge",                    "isin": "INE591G01025", "sector": "IT",           "industry": "Software",             "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},

    # ── Energy & Oil/Gas ──────────────────────────────────────────────────────
    "RELIANCE":    {"name": "Reliance Industries",        "isin": "INE002A01018", "sector": "Energy",       "industry": "Oil & Gas",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ONGC":        {"name": "ONGC",                       "isin": "INE213A01029", "sector": "Energy",       "industry": "Oil Exploration",      "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "IOC":         {"name": "Indian Oil Corporation",     "isin": "INE242A01010", "sector": "Energy",       "industry": "Oil Refinery",         "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "BPCL":        {"name": "BPCL",                       "isin": "INE029A01011", "sector": "Energy",       "industry": "Oil Refinery",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "HPCL":        {"name": "HPCL",                       "isin": "INE094A01015", "sector": "Energy",       "industry": "Oil Refinery",         "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "GAIL":        {"name": "GAIL India",                 "isin": "INE129A01019", "sector": "Energy",       "industry": "Gas Distribution",     "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "NTPC":        {"name": "NTPC",                       "isin": "INE733E01010", "sector": "Energy",       "industry": "Power Generation",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "POWERGRID":   {"name": "Power Grid Corporation",     "isin": "INE752E01010", "sector": "Energy",       "industry": "Power Transmission",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "TATAPOWER":   {"name": "Tata Power",                 "isin": "INE245A01021", "sector": "Energy",       "industry": "Power Generation",     "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "ADANIGREEN":  {"name": "Adani Green Energy",         "isin": "INE364U01010", "sector": "Energy",       "industry": "Renewable Energy",     "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": False},
    "ADANIENT":    {"name": "Adani Enterprises",          "isin": "INE423A01024", "sector": "Energy",       "industry": "Conglomerate",         "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ADANIPORTS":  {"name": "Adani Ports",                "isin": "INE742F01042", "sector": "Infrastructure","industry": "Ports & Logistics",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "COALINDIA":   {"name": "Coal India",                 "isin": "INE522F01014", "sector": "Energy",       "industry": "Mining",               "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},

    # ── Automobile & EV ───────────────────────────────────────────────────────
    "MARUTI":      {"name": "Maruti Suzuki",              "isin": "INE585B01010", "sector": "Automobile",   "industry": "Passenger Vehicles",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "TATAMOTORS":  {"name": "Tata Motors",                "isin": "INE155A01022", "sector": "Automobile",   "industry": "Auto & EV",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "MM":          {"name": "Mahindra & Mahindra",        "isin": "INE101A01026", "sector": "Automobile",   "industry": "Auto & EV",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "EICHERMOT":   {"name": "Eicher Motors",              "isin": "INE066A01021", "sector": "Automobile",   "industry": "Motorcycles",          "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "HEROMOTOCO":  {"name": "Hero MotoCorp",              "isin": "INE158A01026", "sector": "Automobile",   "industry": "2-Wheeler",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "BAJAJ-AUTO":  {"name": "Bajaj Auto",                 "isin": "INE917I01010", "sector": "Automobile",   "industry": "2-Wheeler",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "TVSMOTOR":    {"name": "TVS Motor",                  "isin": "INE494B01023", "sector": "Automobile",   "industry": "2-Wheeler",            "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "ASHOKLEY":    {"name": "Ashok Leyland",              "isin": "INE208A01029", "sector": "Automobile",   "industry": "Commercial Vehicles",  "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},

    # ── Pharma & Healthcare ───────────────────────────────────────────────────
    "SUNPHARMA":   {"name": "Sun Pharma",                 "isin": "INE044A01036", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "DRREDDY":     {"name": "Dr. Reddy's Labs",           "isin": "INE089A01031", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "CIPLA":       {"name": "Cipla",                      "isin": "INE059A01026", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "DIVISLAB":    {"name": "Divi's Laboratories",        "isin": "INE361B01024", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "APOLLOHOSP":  {"name": "Apollo Hospitals",           "isin": "INE437A01024", "sector": "Healthcare",   "industry": "Hospitals",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "LUPIN":       {"name": "Lupin",                      "isin": "INE326A01037", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "AUROPHARMA":  {"name": "Aurobindo Pharma",           "isin": "INE406A01037", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "TORNTPHARM":  {"name": "Torrent Pharma",             "isin": "INE685A01028", "sector": "Pharma",       "industry": "Pharmaceuticals",      "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": True},

    # ── FMCG & Consumer ──────────────────────────────────────────────────────
    "HINDUNILVR":  {"name": "Hindustan Unilever",         "isin": "INE030A01027", "sector": "FMCG",         "industry": "Consumer Goods",       "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ITC":         {"name": "ITC",                        "isin": "INE154A01025", "sector": "FMCG",         "industry": "Diversified FMCG",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "NESTLEIND":   {"name": "Nestlé India",               "isin": "INE239A01024", "sector": "FMCG",         "industry": "Food & Beverages",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "BRITANNIA":   {"name": "Britannia Industries",       "isin": "INE216A01030", "sector": "FMCG",         "industry": "Food & Beverages",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "DABUR":       {"name": "Dabur India",                "isin": "INE016A01026", "sector": "FMCG",         "industry": "Personal Care",        "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "GODREJCP":    {"name": "Godrej Consumer Products",   "isin": "INE102D01028", "sector": "FMCG",         "industry": "Personal Care",        "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "MARICO":      {"name": "Marico",                     "isin": "INE196A01026", "sector": "FMCG",         "industry": "Personal Care",        "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "TATACONSUM":  {"name": "Tata Consumer Products",     "isin": "INE192A01025", "sector": "FMCG",         "industry": "Food & Beverages",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "COLPAL":      {"name": "Colgate-Palmolive India",    "isin": "INE259A01022", "sector": "FMCG",         "industry": "Personal Care",        "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},

    # ── Infrastructure, Cement & Industrials ─────────────────────────────────
    "LT":          {"name": "Larsen & Toubro",            "isin": "INE018A01030", "sector": "Infrastructure","industry": "Engineering & EPC",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ULTRACEMCO":  {"name": "UltraTech Cement",           "isin": "INE481G01011", "sector": "Cement",       "industry": "Cement",               "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "GRASIM":      {"name": "Grasim Industries",          "isin": "INE047A01021", "sector": "Cement",       "industry": "Cement & Chemicals",   "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "AMBUJACEM":   {"name": "Ambuja Cements",             "isin": "INE079A01024", "sector": "Cement",       "industry": "Cement",               "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ACC":         {"name": "ACC",                        "isin": "INE012A01025", "sector": "Cement",       "industry": "Cement",               "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "SHREECEM":    {"name": "Shree Cement",               "isin": "INE070A01015", "sector": "Cement",       "industry": "Cement",               "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "SIEMENS":     {"name": "Siemens India",              "isin": "INE003A01024", "sector": "Industrials",  "industry": "Capital Goods",        "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "ABB":         {"name": "ABB India",                  "isin": "INE117A01022", "sector": "Industrials",  "industry": "Capital Goods",        "market_cap": "Large Cap", "fno": False, "nifty50": False, "nifty_next": True},
    "BEL":         {"name": "Bharat Electronics",         "isin": "INE263A01024", "sector": "Defence",      "industry": "Defence Electronics",  "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "HAL":         {"name": "Hindustan Aeronautics",      "isin": "INE066F01020", "sector": "Defence",      "industry": "Aerospace & Defence",  "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},

    # ── Metals & Mining ───────────────────────────────────────────────────────
    "TATASTEEL":   {"name": "Tata Steel",                 "isin": "INE081A01020", "sector": "Metals",       "industry": "Steel",                "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "JSWSTEEL":    {"name": "JSW Steel",                  "isin": "INE019A01038", "sector": "Metals",       "industry": "Steel",                "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "HINDALCO":    {"name": "Hindalco Industries",        "isin": "INE038A01020", "sector": "Metals",       "industry": "Aluminium",            "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "VEDL":        {"name": "Vedanta",                    "isin": "INE205A01025", "sector": "Metals",       "industry": "Diversified Metals",   "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "SAIL":        {"name": "Steel Authority of India",   "isin": "INE114A01011", "sector": "Metals",       "industry": "Steel",                "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": False},

    # ── Telecom & Internet ────────────────────────────────────────────────────
    "BHARTIARTL":  {"name": "Bharti Airtel",              "isin": "INE397D01024", "sector": "Telecom",      "industry": "Telecom Services",     "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "IDEA":        {"name": "Vodafone Idea",              "isin": "INE669E01016", "sector": "Telecom",      "industry": "Telecom Services",     "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},
    "ZOMATO":      {"name": "Zomato",                     "isin": "INE758T01015", "sector": "Consumer Internet","industry": "Food Delivery",    "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "PAYTM":       {"name": "Paytm (One97)",              "isin": "INE982J01020", "sector": "Fintech",      "industry": "Digital Payments",     "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},
    "NYKAA":       {"name": "Nykaa (FSN E-Commerce)",     "isin": "INE388Y01029", "sector": "Consumer Internet","industry": "E-Commerce",       "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},

    # ── Consumer Discretionary ────────────────────────────────────────────────
    "TITAN":       {"name": "Titan Company",              "isin": "INE280A01028", "sector": "Consumer",     "industry": "Jewellery & Watches",  "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "ASIANPAINT":  {"name": "Asian Paints",               "isin": "INE021A01026", "sector": "Consumer",     "industry": "Paints",               "market_cap": "Large Cap", "fno": True,  "nifty50": True,  "nifty_next": False},
    "PIDILITIND":  {"name": "Pidilite Industries",        "isin": "INE318A01026", "sector": "Consumer",     "industry": "Adhesives & Chemicals","market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "BERGEPAINT":  {"name": "Berger Paints",              "isin": "INE463A01038", "sector": "Consumer",     "industry": "Paints",               "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "PAGEIND":     {"name": "Page Industries (Jockey)",   "isin": "INE761H01022", "sector": "Consumer",     "industry": "Apparel",              "market_cap": "Mid Cap",   "fno": True,  "nifty50": False, "nifty_next": False},

    # ── Real Estate ───────────────────────────────────────────────────────────
    "DLF":         {"name": "DLF",                        "isin": "INE271C01023", "sector": "Real Estate",  "industry": "Residential RE",       "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "GODREJPROP":  {"name": "Godrej Properties",          "isin": "INE484J01027", "sector": "Real Estate",  "industry": "Residential RE",       "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": True},
    "PRESTIGE":    {"name": "Prestige Estates",           "isin": "INE811K01011", "sector": "Real Estate",  "industry": "Residential RE",       "market_cap": "Large Cap", "fno": True,  "nifty50": False, "nifty_next": False},
}
# fmt: on

# ── Index instruments ─────────────────────────────────────────────────────────
INDEX_INSTRUMENTS: Dict[str, str] = {
    "NIFTY50":    "NSE_INDEX|Nifty 50",
    "NIFTY":      "NSE_INDEX|Nifty 50",
    "BANKNIFTY":  "NSE_INDEX|Nifty Bank",
    "NIFTYBANK":  "NSE_INDEX|Nifty Bank",
    "NIFTYIT":    "NSE_INDEX|Nifty IT",
    "FINNIFTY":   "NSE_INDEX|Nifty Fin Service",
    "VIXINDIA":   "NSE_INDEX|India VIX",
    "MIDCAP":     "NSE_INDEX|NIFTY MIDCAP 150",
    "NIFTYMIDCAP": "NSE_INDEX|Nifty Midcap 50",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MIDCAP SELECT",
    "NIFTYAUTO":  "NSE_INDEX|Nifty Auto",
    "NIFTYFMCG":  "NSE_INDEX|Nifty FMCG",
    "SENSEX":     "BSE_INDEX|SENSEX",
    # Not in the Upstox master yet; data_engine/gift_nifty.py probes it and
    # falls back to Nifty 50.
    "GIFTNIFTY":  "NSE_INDEX|GIFT NIFTY",
}

# ── Derived: flat symbol → instrument_key map (for Upstox API calls) ─────────
INSTRUMENTS: Dict[str, str] = {
    sym: f"NSE_EQ|{data['isin']}"
    for sym, data in STOCK_UNIVERSE.items()
}
INSTRUMENTS.update(INDEX_INSTRUMENTS)

# ── Sector colour palette (for UI) ────────────────────────────────────────────
SECTOR_COLORS: Dict[str, str] = {
    "Banking":          "#3b82f6",  # blue
    "Finance":          "#6366f1",  # indigo
    "IT":               "#8b5cf6",  # violet
    "Energy":           "#f59e0b",  # amber
    "Automobile":       "#10b981",  # emerald
    "Pharma":           "#14b8a6",  # teal
    "Healthcare":       "#06b6d4",  # cyan
    "FMCG":             "#f97316",  # orange
    "Infrastructure":   "#84cc16",  # lime
    "Cement":           "#a8a29e",  # stone
    "Industrials":      "#78716c",  # warm gray
    "Defence":          "#ef4444",  # red
    "Metals":           "#b45309",  # amber-dark
    "Telecom":          "#ec4899",  # pink
    "Consumer Internet":"#0ea5e9",  # sky
    "Fintech":          "#a855f7",  # purple
    "Consumer":         "#22c55e",  # green
    "Real Estate":      "#f43f5e",  # rose
}


# ── Helper functions ──────────────────────────────────────────────────────────

def get_sector_map() -> Dict[str, List[str]]:
    """Returns {sector: [sym, ...]} ordered by sector name."""
    result: Dict[str, List[str]] = {}
    for sym, data in STOCK_UNIVERSE.items():
        sector = data["sector"]
        result.setdefault(sector, []).append(sym)
    return dict(sorted(result.items()))


def get_fno_symbols() -> List[str]:
    return [s for s, d in STOCK_UNIVERSE.items() if d["fno"]]


def get_nifty50_symbols() -> List[str]:
    return [s for s, d in STOCK_UNIVERSE.items() if d["nifty50"]]


def get_symbols_by_sector(sector: str) -> List[str]:
    return [s for s, d in STOCK_UNIVERSE.items() if d["sector"] == sector]


def get_large_cap_symbols() -> List[str]:
    return [s for s, d in STOCK_UNIVERSE.items() if d["market_cap"] == "Large Cap"]


def symbol_info(symbol: str) -> dict:
    """Returns metadata for a symbol, or empty dict if unknown."""
    return STOCK_UNIVERSE.get(symbol.upper(), {})
