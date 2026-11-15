#!/usr/bin/env python3
"""Test authentication input using a PTY and a local RFB server (no X11)."""
import fcntl
import os
from pathlib import Path
import pty
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time


def controlling_tty():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def check(plain=True, credentials=None, options=(), interactive=False):
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    env = {k: v for k, v in os.environ.items()
           if k not in ('VNC_USERNAME', 'VNC_PASSWORD')}
    env.update(credentials or {})
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        listener.settimeout(10)
        # Keep the controlling session alive to inspect termios after exit.
        wrapper = '"$@"; status=$?; printf "AUTH_DONE\\n"; read ignored; exit "$status"'
        viewer = subprocess.Popen(['/bin/sh', '-c', wrapper, 'auth-test', sys.argv[1],
            '-SecurityTypes=' + ('Plain' if plain else 'VncAuth'), *options,
            '127.0.0.1::' + str(listener.getsockname()[1])], env=env,
            stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling_tty)
        transcript = bytearray()

        def drain():
            chunk = os.read(master, 4096)
            transcript.extend(chunk)
            return bool(chunk)

        def prompt(text):
            end = time.monotonic() + 10
            while text not in transcript:
                assert time.monotonic() < end, repr(transcript)
                if select.select([master], [], [], .1)[0]:
                    assert drain(), repr(transcript)

        try:
            with listener.accept()[0] as conn:
                conn.settimeout(10)

                def receive(n):
                    data = b''
                    end = time.monotonic() + 10
                    while len(data) < n:
                        assert time.monotonic() < end, (n, data, transcript)
                        readable = select.select([conn, master], [], [], .1)[0]
                        # PTY output must be drained while getpass restores
                        # termios with TCSAFLUSH, which waits for output.
                        if master in readable:
                            drain()
                        if conn in readable:
                            part = conn.recv(n - len(data))
                            assert part, 'unexpected disconnect'
                            data += part
                    return data

                conn.sendall(b'RFB 003.008\n')
                assert receive(12) == b'RFB 003.008\n'
                security = 19 if plain else 2
                conn.sendall(bytes([1, security]))
                assert receive(1) == bytes([security])
                if plain:
                    conn.sendall(b'\x00\x02')  # VeNCrypt 0.2
                    assert receive(2) == b'\x00\x02'
                    conn.sendall(b'\x00\x01' + struct.pack('!I', 256))
                    assert receive(4) == struct.pack('!I', 256)  # Plain
                else:
                    conn.sendall(bytes(range(16)))  # Fixed VNC challenge
                if interactive:
                    prompt(b'VNC username: ')
                    os.write(master, b'echo-user\n')
                    prompt(b'VNC password: ')
                    assert b'echo-user' in transcript, 'username not echoed'
                    assert not termios.tcgetattr(slave)[3] & termios.ECHO
                    os.write(master, b'hidden-password\n')
                if plain:
                    ulen, plen = struct.unpack('!II', receive(8))
                    response = (receive(ulen), receive(plen))
                    expected = ((b'echo-user', b'hidden-password') if interactive else
                        (env['VNC_USERNAME'].encode(), env['VNC_PASSWORD'].encode()))
                    assert response == expected
                else:
                    response = receive(16)
                reason = b'Expected test rejection'
                conn.sendall(struct.pack('!II', 1, len(reason)) + reason)
                prompt(b'AUTH_DONE')
                assert termios.tcgetattr(slave) == before, 'termios not restored'
                if not interactive:
                    assert b'VNC username:' not in transcript
                    assert b'VNC password:' not in transcript
                assert b'hidden-password' not in transcript, 'password echoed'
                os.write(master, b'\n')
                end = time.monotonic() + 10
                while viewer.poll() is None:
                    assert time.monotonic() < end, 'viewer did not exit'
                    if select.select([master], [], [], .1)[0]:
                        drain()
                assert viewer.returncode == 1
                return response
        finally:
            if viewer.poll() is None:
                viewer.kill()
                viewer.wait()
            os.close(master)
            os.close(slave)


check(interactive=True)
check(credentials={'VNC_USERNAME': 'ignored'}, interactive=True)
check(credentials={'VNC_PASSWORD': 'ignored'}, interactive=True)
check(credentials={'VNC_USERNAME': 'env-user', 'VNC_PASSWORD': 'env-password'})
check(credentials={'VNC_USERNAME': '', 'VNC_PASSWORD': ''})
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'passwd'
    # vncpasswd -f output for the test password "secret42".
    path.write_bytes(bytes.fromhex('89c281f1b7fe89d6'))
    path.chmod(0o600)
    check(options=('-passwd', str(path)), interactive=True)
    check(credentials={'VNC_USERNAME': 'env-user', 'VNC_PASSWORD': 'env-password'},
          options=('-passwd', str(path)))
    reference = check(plain=False, credentials={'VNC_PASSWORD': 'secret42'})
    for options in [('-passwd', str(path)), ('-PasswordFile', str(path)),
                    ('PasswordFile=' + str(path),), ('--PasswordFile=' + str(path),)]:
        assert check(plain=False, options=options) == reference
    path.write_bytes(b'invalid')
    assert check(plain=False, credentials={'VNC_PASSWORD': 'secret42'},
                 options=('-passwd', str(path))) == reference
print('PASS: prompts/echo, environment, empty/partial values, password files, precedence, termios')
