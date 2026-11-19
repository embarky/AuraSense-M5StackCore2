# Generic stand-in object: any attribute or call returns another stand-in.
class Dummy:
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return Dummy()

    def __getattr__(self, name):
        return Dummy()

    def __int__(self):
        return 0

    def __bool__(self):
        return False
