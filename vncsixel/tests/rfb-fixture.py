#!/usr/bin/env python3
"""Local deterministic raw-RFB server for renderer tests (no credentials)."""
import socket
import struct
import threading


class Server:
    def __init__(self, width=599, height=431):
        self.width, self.height = width, height
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.condition = threading.Condition()
        initial = bytearray(b'\xff\xff\xff\0' * width * height)
        for y in range(12):
            initial[y * width * 4:(y * width + 12) * 4] = b'\xff\0\0\0' * 12
        self.pending = (0, 0, width, height, bytes(initial))
        self.sent = 0
        self.error = None
        self.closed = False
        self.conn = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def update(self, x, y, width, height, pixels):
        assert len(pixels) == width * height * 4
        with self.condition:
            assert self.pending is None
            self.pending = (x, y, width, height, pixels)
            self.condition.notify_all()

    def run(self):
        try:
            self.conn, _ = self.listener.accept()
            conn = self.conn

            def receive(n):
                data = b''
                while len(data) < n:
                    part = conn.recv(n - len(data))
                    if not part:
                        raise EOFError()
                    data += part
                return data

            conn.sendall(b'RFB 003.008\n')
            assert receive(12) == b'RFB 003.008\n'
            conn.sendall(b'\x01\x01')  # None
            assert receive(1) == b'\x01'
            conn.sendall(struct.pack('!I', 0))
            assert receive(1) == b'\x01', 'client did not request shared access'
            name = b'Deterministic renderer fixture'
            conn.sendall(struct.pack('!HHBBBBHHHBBB3xI', self.width, self.height,
                32, 24, 0, 1, 255, 255, 255, 16, 8, 0, len(name)) + name)
            while not self.closed:
                message = receive(1)[0]
                if message == 0:
                    receive(19)  # SetPixelFormat
                elif message == 2:
                    count = struct.unpack('!H', receive(3)[1:])[0]
                    receive(count * 4)
                elif message == 3:
                    receive(9)
                    with self.condition:
                        self.condition.wait_for(lambda: self.closed or self.pending is not None)
                        if self.closed:
                            break
                        x, y, w, h, data = self.pending
                        conn.sendall(struct.pack('!BBHHHHHi', 0, 0, 1, x, y, w, h, 0) + data)
                        self.pending = None
                        self.sent += 1
                        self.condition.notify_all()
                else:
                    raise AssertionError('unexpected client message: ' + str(message))
        except (EOFError, OSError):
            pass
        except Exception as error:
            self.error = error

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.conn:
            self.conn.close()
        self.listener.close()
        self.thread.join(timeout=3)
        if self.error:
            raise self.error
