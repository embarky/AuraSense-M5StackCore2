# Test stand-in for the UIFlow "unit" module (no hardware needed)
from _dummy import Dummy


def __getattr__(name):
    return Dummy()
