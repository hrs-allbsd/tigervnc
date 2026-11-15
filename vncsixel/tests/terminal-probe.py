#!/usr/bin/env python3
"""Exercise terminal negotiation with a responding PTY, without X11."""
import fcntl
import os
import pty
import select
import subprocess
import sys
import termios
import time


def controlling_tty():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def check(colors=1024, queries=True, options=(), graphics=(600, 468), expected=b'colors 256', status=0):
    master, slave = pty.openpty()
    saved = termios.tcgetattr(slave)
    wrapper = '"$@"; status=$?; printf "PROBE_DONE:%s\\n" "$status"; read ignored; exit "$status"'
    process = subprocess.Popen(['/bin/sh', '-c', wrapper, 'probe', sys.argv[1],
        *options, '--terminal-check'], stdin=slave, stdout=slave, stderr=slave,
        preexec_fn=controlling_tty)
    responses = {b'\x1b[c': b'\x1b[?63;1;4c',
        b'\x1b[14t': b'\x1b[4;468;600t' if queries else b'',
        b'\x1b[16t': b'\x1b[6;13;6t' if queries else b'',
        b'\x1b[?1;1;0S': ('\x1b[?1;0;%dS' % colors).encode(),
        b'\x1b[?2;1;0S': ('\x1b[?2;0;%d;%dS' % graphics).encode(),
        b'\x1b[?1016$p': b'\x1b[?1016;2$y', b'\x1b[?4m': b'\x1b[>4;0m'}
    transcript = bytearray()
    pending = bytearray()
    start = time.monotonic()
    try:
        while b'PROBE_DONE:' not in transcript:
            assert time.monotonic() - start < 10, repr(transcript)
            if not select.select([master], [], [], .1)[0]: continue
            chunk = os.read(master, 4096)
            assert chunk, repr(transcript)
            transcript.extend(chunk)
            pending.extend(chunk)
            for query, response in responses.items():
                while query in pending:
                    offset = pending.index(query)
                    del pending[:offset + len(query)]
                    if response: os.write(master, response)
        assert expected in transcript, repr(transcript)
        assert ('PROBE_DONE:%d' % status).encode() in transcript
        assert termios.tcgetattr(slave) == saved, 'termios not restored'
        elapsed = time.monotonic() - start
        os.write(master, b'\n')
        process.wait(timeout=5)
        assert process.returncode == status
        return elapsed
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
        os.close(master); os.close(slave)


assert check() < 1.0, 'completed queries unnecessarily waited for deadlines'
check(colors=16, expected=b'colors 8')
check(colors=4, expected=b'at least 8 SIXEL colors', status=1)
check(queries=False, options=('-CellSize=6x13', '-PixelSize=600x468'))
check(graphics=(300, 300), expected=b'300x276')
check(queries=False, expected=b'Invalid terminal geometry', status=1)
check(options=('-CellSize=0x13',), expected=b'Invalid terminal geometry', status=1)
check(options=('-PixelSize=600x468bad',), expected=b'dimensions must be WxH', status=1)
print('PASS: fast queries, color limits, geometry overrides, graphics bounds, invalid sizes, termios')
