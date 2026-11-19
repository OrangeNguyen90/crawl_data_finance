from marketdata.collectors.base import CollectorError
from marketdata.collectors.cftc import CftcCollector
from marketdata.collectors.cme import CmeCollector
from marketdata.collectors.cboe import CboeCollector
from marketdata.collectors.eurex import EurexCollector
from marketdata.collectors.dukascopy import DukascopyCollector
from marketdata.collectors.firstrate import FirstRateCollector

COLLECTORS = {"cftc": CftcCollector, "cme": CmeCollector, "cboe": CboeCollector,
              "eurex": EurexCollector, "dukascopy": DukascopyCollector, "firstrate": FirstRateCollector}


def get_collector(name):
    if name not in COLLECTORS:
        raise CollectorError("Unknown source")
    return COLLECTORS[name]()

