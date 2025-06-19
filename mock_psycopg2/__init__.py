class DummyCursor:
    def execute(self, *args, **kwargs):
        pass
    def fetchone(self):
        return None

class DummyConnection:
    def cursor(self):
        return DummyCursor()
    def commit(self):
        pass

def connect(*args, **kwargs):
    return DummyConnection()
