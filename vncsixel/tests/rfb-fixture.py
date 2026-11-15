#!/usr/bin/env python3
"""Local deterministic raw-RFB server for renderer tests (no credentials)."""
import select
import socket
import struct
import threading
import time


class Server:
    def __init__(self, width=599, height=431, on_key=None, textured=False, cursor=False, server_format=None):
        self.width, self.height = width, height
        self.on_key = on_key
        self.cursor = cursor
        self.server_format = server_format or (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        self.client_format = None
        self.encodings = set()
        self.key_events = []
        self.requested = False
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        self.condition = threading.Condition()
        initial = bytearray(b'\xff\xff\xff\0' * width * height)
        if textured:
            for y in range(height):
                for x in range(width):
                    c = (x * 17 + y * 29) & 255
                    initial[(y * width + x) * 4:(y * width + x + 1) * 4] = bytes(
                        ((c & 3) * 255 // 3, ((c >> 2) & 7) * 255 // 7,
                         (c >> 5) * 255 // 7, 0))
        for y in range(12):
            initial[y * width * 4:(y * width + 12) * 4] = b'\xff\0\0\0' * 12
        self.pending = [(0, 0, width, height, 0, bytes(initial))]
        self.sent = 0
        self.error = None
        self.closed = False
        self.conn = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def update(self, x, y, width, height, pixels):
        assert len(pixels) == width * height * 4
        self.update_rects([(x, y, width, height, pixels)])

    def update_rects(self, rectangles):
        for x, y, width, height, pixels in rectangles:
            assert len(pixels) == width * height * 4
        self.update_encoded([(x, y, w, h, 0, data) for x, y, w, h, data in rectangles])

    def update_encoded(self, rectangles):
        """Queue already encoded RFB rectangles, including pseudo encodings."""
        with self.condition:
            assert self.pending is None
            self.pending = rectangles
            self.condition.notify_all()

    def run(self):
        try:
            self.conn, _ = self.listener.accept()
            conn = self.conn
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

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
                *self.server_format, len(name)) + name)
            while not self.closed:
                with self.condition:
                    if self.requested and self.pending is not None:
                        cursor = (struct.pack('!HHHHi', 0, 0, 8, 8, -239) +
                            b'\xff\0\xff\0' * 64 + b'\xff' * 8) if self.cursor and not self.sent else b''
                        packet = struct.pack('!BBH', 0, 0, len(self.pending) + bool(cursor)) + cursor
                        for x, y, w, h, encoding, data in self.pending:
                            packet += struct.pack('!HHHHi', x, y, w, h, encoding) + data
                        conn.sendall(packet)
                        self.pending = None
                        self.requested = False
                        self.sent += 1
                        self.condition.notify_all()
                if not select.select([conn], [], [], .005)[0]:
                    continue
                message = receive(1)[0]
                if message == 0:
                    self.client_format = struct.unpack('!BBBBHHHBBB3x', receive(19)[3:])
                    assert self.client_format == (32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
                elif message == 2:
                    count = struct.unpack('!H', receive(3)[1:])[0]
                    self.encodings = set(struct.unpack('!' + 'i' * count, receive(count * 4)))
                elif message == 3:
                    receive(9)
                    self.requested = True
                elif message == 4 and self.on_key is not None:
                    down, key = struct.unpack('!B2xI', receive(7))
                    self.key_events.append((time.monotonic_ns(), down, key))
                    self.on_key(self, down, key)
                elif message == 5 and self.on_key is not None:
                    receive(5)  # Cleanup/mouse events in interactive tests
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
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.conn.close()
        self.listener.close()
        self.thread.join(timeout=3)
        if self.error:
            raise self.error
