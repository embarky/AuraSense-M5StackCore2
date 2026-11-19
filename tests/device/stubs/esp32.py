# Test stand-in for the UIFlow "esp32" module (no hardware needed)
from _dummy import Dummy


def __getattr__(name):
    return Dummy()
