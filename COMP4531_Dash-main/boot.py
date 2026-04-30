# CircuitPython boot.py
# Remounts CIRCUITPY writable from firmware side so code.py can write log.txt.
# Side-effect: USB host sees the drive as READ-ONLY while this is active.
#
# To flash via web dashboard again:
#   Double-tap the reset button quickly -> safe mode (yellow LED flicker).
#   Safe mode skips boot.py -> USB becomes writable -> flash normally.
#   Single reset returns to log mode.
import storage
storage.remount('/', readonly=False)
