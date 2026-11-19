# Test stand-in for the UIFlow "m5things" module (no hardware needed)
from _dummy import Dummy


def __getattr__(name):
    return Dummy()
