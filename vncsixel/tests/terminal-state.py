#!/usr/bin/env python3
"""Record xterm modes while preserving the caller's terminal settings."""
import json
import os
from pathlib import Path
import re
import select
import sys
import termios
import time
import tty

fd = os.open('/dev/tty', os.O_RDWR)
saved = termios.tcgetattr(fd)
result = {}
try:
    tty.setraw(fd)
    for mode in [25, 80, 1003, 1004, 1006, 1016, 1049, 1070, 2004]:
        os.write(fd, ('\x1b[?%d$p' % mode).encode())
        response = b''
        end = time.monotonic() + .25
        match = None
        while time.monotonic() < end:
            if select.select([fd], [], [], max(0, end - time.monotonic()))[0]:
                response += os.read(fd, 1024)
                match = re.search(rb'\x1b\[\?' + str(mode).encode() + rb';([0-4])\$y', response)
                if match:
                    break
        if not match:
            raise RuntimeError('no DECRQM reply for ' + str(mode))
        result[str(mode)] = int(match[1])
finally:
    termios.tcsetattr(fd, termios.TCSANOW, saved)
    os.close(fd)
Path(sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
