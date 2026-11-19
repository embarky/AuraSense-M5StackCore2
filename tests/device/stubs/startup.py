# Test stand-in for the UIFlow "startup" module (no hardware needed)
from _dummy import Dummy


def __getattr__(name):
    return Dummy()
