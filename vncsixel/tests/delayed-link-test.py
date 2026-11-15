#!/usr/bin/env python3
"""Check relay delay, bounded queues, byte ordering and TCP half-closes."""
import hashlib
import importlib.util
from pathlib import Path
import socket
import threading
import time
import unittest

spec=importlib.util.spec_from_file_location('link',Path(__file__).with_name('delayed-link.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class RelayTest(unittest.TestCase):
    def exchange(self,payload,delay,limit):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
        errors=[]
        def respond():
            try:
                with listener.accept()[0] as peer:
                    peer.settimeout(10)
                    parts=[]
                    while True:
                        part=peer.recv(8192)
                        if not part:break
                        parts.append(part)
                    received=b''.join(parts)
                    assert hashlib.sha256(received).digest()==hashlib.sha256(payload).digest()
                    peer.sendall(received[::-1]);peer.shutdown(socket.SHUT_WR)
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=respond,daemon=True);thread.start()
        relay=module.DelayedLink(listener.getsockname()[1],delay,limit)
        try:
            with socket.create_connection(('127.0.0.1',relay.port),5) as client:
                client.settimeout(10);start=time.monotonic()
                client.sendall(payload);client.shutdown(socket.SHUT_WR)
                parts=[]
                while True:
                    part=client.recv(4096)
                    if not part:break
                    parts.append(part)
                self.assertEqual(payload[::-1],b''.join(parts))
                self.assertGreaterEqual(time.monotonic()-start,delay*2/1000)
            thread.join(timeout=10);self.assertFalse(thread.is_alive())
            self.assertFalse(errors,errors)
            self.assertEqual(relay.forwarded,[len(payload),len(payload)])
            self.assertTrue(all(value<=limit for value in relay.peak_queued))
        finally:
            relay.close();listener.close();thread.join(timeout=6)

    def test_delayed_half_close(self):
        self.exchange(b'hello\0TCP\xff'*100,10,4096)

    def test_large_ordered_transfer_under_backpressure(self):
        self.exchange(bytes(range(256))*8192,1,4096)

    def test_zero_delay_and_tiny_queue(self):
        self.exchange(bytes(range(256)),0,7)

    def test_target_failure_is_reported(self):
        # Reserve a loopback port without listening, forcing connect refusal.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1',0))
            relay=module.DelayedLink(unavailable.getsockname()[1])
            with socket.create_connection(('127.0.0.1',relay.port),5) as client:
                client.settimeout(5)
                self.assertEqual(client.recv(1),b'')
            with self.assertRaises(ConnectionRefusedError):relay.close()

    def test_stop_without_client(self):
        relay=module.DelayedLink(1,10)
        relay.close()
        self.assertFalse(relay.thread.is_alive())

if __name__=='__main__':unittest.main()
