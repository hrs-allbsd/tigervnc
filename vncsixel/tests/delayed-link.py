#!/usr/bin/env python3
"""Bounded loopback-only TCP relay with fixed delay in each direction.

This models propagation delay, not packet loss, congestion or WAN jitter.
"""
from collections import deque
import select
import socket
import threading
import time


class DelayedLink:
    def __init__(self, port, one_way_ms=0, queue_limit=262144):
        if not 0 <= one_way_ms <= 500 or queue_limit < 1:
            raise ValueError('delay must be 0..500 ms and queue_limit positive')
        self.target = port
        self.delay = one_way_ms / 1000
        self.limit = queue_limit
        self.stop = threading.Event()
        self.error = None
        self.forwarded = [0, 0]
        self.peak_queued = [0, 0]
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        peers = []
        try:
            while not self.stop.is_set():
                try:
                    client, _ = self.listener.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            peers.append(client)
            peers.append(socket.create_connection(('127.0.0.1', self.target), 5))
            for peer in peers:
                peer.setblocking(False)
                peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Queue i contains bytes read from peer i, destined for peer 1-i.
            queues = [deque(), deque()]
            queued = [0, 0]
            reading, shutdown = [True, True], [False, False]
            while not self.stop.is_set():
                for i in range(2):
                    if not reading[i] and not queues[i] and not shutdown[i]:
                        peers[1-i].shutdown(socket.SHUT_WR)
                        shutdown[i] = True
                if not any(reading) and not any(queues):
                    return
                now = time.monotonic()
                readers = [peers[i] for i in range(2) if reading[i] and queued[i] < self.limit]
                writers = [peers[1-i] for i in range(2) if queues[i] and queues[i][0][0] <= now]
                waits = [.05] + [q[0][0]-now for q in queues if q and q[0][0] > now]
                readable, writable, _ = select.select(readers, writers, [], min(waits))
                for i in range(2):
                    if peers[i] in readable:
                        try:
                            data = peers[i].recv(min(65536, self.limit-queued[i]))
                        except BlockingIOError:
                            continue
                        if not data:
                            reading[i] = False
                        else:
                            queues[i].append((time.monotonic()+self.delay, memoryview(data)))
                            queued[i] += len(data)
                            self.peak_queued[i] = max(self.peak_queued[i], queued[i])
                    if peers[1-i] in writable:
                        due, data = queues[i][0]
                        try:
                            sent = peers[1-i].send(data)
                        except BlockingIOError:
                            continue
                        if not sent:
                            raise RuntimeError('relay write made no progress')
                        queued[i] -= sent
                        self.forwarded[i] += sent
                        if sent == len(data):
                            queues[i].popleft()
                        else:
                            queues[i][0] = (due, data[sent:])
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as error:
            if not self.stop.is_set():
                self.error = error
        finally:
            for peer in peers:
                peer.close()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=6)
        self.listener.close()
        if self.thread.is_alive():
            raise RuntimeError('relay did not stop')
        if self.error:
            raise self.error

    def metrics(self):
        return {'one_way_ms': self.delay*1000, 'queue_limit_bytes': self.limit,
                'forwarded_bytes': self.forwarded, 'peak_queued_bytes': self.peak_queued}
