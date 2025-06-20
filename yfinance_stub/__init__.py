import pandas as pd

class Ticker:
    def __init__(self, ticker):
        self.ticker = ticker
    @property
    def info(self):
        return {"sector": "Technology"}

def download(ticker, start=None, end=None, progress=False):
    index = pd.date_range(start=start, end=end, freq='D')[:-1]
    return pd.DataFrame({"Close": [0.0] * len(index)}, index=index)
