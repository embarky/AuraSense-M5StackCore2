# Test stand-in for MicroPython's requests module: records every call.
calls = []


class Resp:
    def __init__(self, code, body):
        self.status_code = code
        self._body = body
        self.content = b"RIFF" + b"\0" * 60

    def json(self):
        return self._body

    def close(self):
        pass


def post(url, data=None, headers=None, timeout=None):
    calls.append(("POST", url, headers))
    return Resp(200, {"status": "ok"})


def get(url, headers=None, timeout=None):
    calls.append(("GET", url, headers))
    return Resp(200, {"forecast": [], "location": "X"})
