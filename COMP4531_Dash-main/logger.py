# Minimal file logger for CircuitPython mesh nodes.
# Requires boot.py to have called storage.remount('/', readonly=False).
# Writes to /log.txt, rotates to /log_old.txt when > LOG_MAX bytes.
import os
import time

LOG_FILE = '/log.txt'
LOG_OLD  = '/log_old.txt'
LOG_MAX  = 40960   # 40 KB

_t0 = time.monotonic()

def init():
    _write_raw("=== boot N{} ===\n".format(_get_node_id()))

def _get_node_id():
    try:
        import __main__
        return getattr(__main__, 'NODE_ID', '?')
    except Exception:
        return '?'

def _write_raw(text):
    try:
        try:
            size = os.stat(LOG_FILE)[6]
        except OSError:
            size = 0
        if size > LOG_MAX:
            try:
                os.remove(LOG_OLD)
            except OSError:
                pass
            try:
                os.rename(LOG_FILE, LOG_OLD)
            except OSError:
                pass
        with open(LOG_FILE, 'a') as f:
            f.write(text)
    except Exception as e:
        print("LOG ERR: {}".format(e))

def log(msg):
    ts = "{:.2f}".format(time.monotonic() - _t0)
    _write_raw("[{}] {}\n".format(ts, msg))
