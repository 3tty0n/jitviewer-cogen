
import re
from numpy import zeros

def g():
    return 1

def loop():
    i = 0
    while i < 10000:
        if i & 2:
            i += g()
        else:
            i += 3

def other_loop():
    for i in range(2000):
        re.search("0", str(i))

if __name__ == '__main__':
    loop()
    other_loop()
    a = zeros(10000)
    repr(a + a / a)
