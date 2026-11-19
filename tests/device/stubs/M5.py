# Test stand-in for UIFlow's M5 module. `from M5 import *` needs real names.
from _dummy import Dummy

Lcd = Dummy()
Widgets = Dummy()
BtnA = Dummy()
BtnB = Dummy()
BtnC = Dummy()
Speaker = Dummy()
Mic = Dummy()
Power = Dummy()
Display = Dummy()


def begin(*a):
    pass


def update(*a):
    pass


def __getattr__(name):
    return Dummy()
