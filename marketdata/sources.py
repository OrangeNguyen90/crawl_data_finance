SOURCES = {
    "cftc": ("https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm", "cot", "weekly"),
    "cme": ("https://www.cmegroup.com/market-data/daily-bulletin.html", "daily_statistics", "daily"),
    "eurex": ("https://www.eurex.com/ex-en/data/free-reference-data-api", "reference", "periodic"),
    "cboe": ("https://www.cboe.com/markets/us/futures/market-statistics/daily/futures/", "daily_statistics", "daily"),
    "dukascopy": ("https://www.dukascopy.com/swiss/english/marketwatch/historical/", "fx_prices", "manual"),
    "firstrate": ("https://firstratedata.com/", "sample", "manual"),
}


def ensure_sources():
    from marketdata.models import DataSource

    for name, (url, kind, frequency) in SOURCES.items():
        DataSource.objects.get_or_create(name=name, defaults={"provider_type": kind,
            "official_url": url, "data_frequency": frequency,
            "license_status": "public_source" if name == "cftc" else "unverified",
            "enabled": name == "cftc"})
