class Ticker:
    def __init__(self, ticker):
        self.ticker = ticker
    @property
    def info(self):
        return {"sector": "Technology"}
