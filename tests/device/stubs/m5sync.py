# Test stand-in for the UIFlow "m5sync" module (no hardware needed)
from _dummy import Dummy


def __getattr__(name):
    return Dummy()
