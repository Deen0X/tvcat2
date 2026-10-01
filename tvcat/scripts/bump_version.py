"""Sube el segundo dígito de __version__ en gateway.py (2.2 -> 2.3).
Uso: python scripts/bump_version.py [--set X.Y] [--major]
Sin argumentos: +1 al minor. No toca el codename.
"""
import re
import os
import sys

GW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gateway.py")


def bump(path, set_to=None, major=False):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', src)
    if not m:
        raise SystemExit("No se encontró __version__ en %s" % path)
    old = m.group(1)
    if set_to:
        new = set_to.strip()
    else:
        parts = re.findall(r"\d+", old)
        nums = [int(x) for x in parts[:3]] + [0] * (3 - len(parts[:3]))
        if major:
            nums = [nums[0] + 1, 0, 0]
        else:
            nums[1] += 1
            nums[2] = 0
        new = "%d.%d" % (nums[0], nums[1])
        if len(parts) > 2 or (len(parts) == 3 and int(parts[2]) != 0):
            new += ".%d" % nums[2]
    src = src[:m.start(1)] + new + src[m.end(1):]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print("%s -> %s" % (old, new))


if __name__ == "__main__":
    args = sys.argv[1:]
    set_to = None
    major = False
    for i, a in enumerate(args):
        if a == "--set" and i + 1 < len(args):
            set_to = args[i + 1]
        if a == "--major":
            major = True
    bump(GW, set_to=set_to, major=major)
