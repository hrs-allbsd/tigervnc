#!/usr/bin/env python3
"""Print vncsixel's SHA256 RSA-AES fingerprint from a PEM public key.

Export with: openssl pkey -in server-private.pem -pubout -out server-public.pem
Run this on a trusted machine; do not obtain the key over an unverified link.
"""
import argparse
import hashlib
import struct
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('public_key')
args=parser.parse_args()
# Convert a PEM public key to the PKCS#1 RSA public-key sequence.
key=subprocess.check_output(['openssl','rsa','-pubin','-in',args.public_key,
    '-RSAPublicKey_out','-outform','DER'],stderr=subprocess.DEVNULL)
def value(data,offset,tag):
    assert data[offset]==tag,'invalid RSA public-key DER tag'
    length=data[offset+1];start=offset+2
    if length&128:
        count=length&127
        assert 1<=count<=4,'invalid DER length'
        length=int.from_bytes(data[start:start+count],'big');start+=count
    assert start+length<=len(data),'truncated RSA public key'
    return data[start:start+length],start+length
sequence,end=value(key,0,0x30)
assert end==len(key)
n,offset=value(sequence,0,2)
e,end=value(sequence,offset,2)
assert end==len(sequence) and not n[0]&128 and not e[0]&128
n=n.lstrip(b'\0');e=e.lstrip(b'\0')
assert 128<=len(n)<=1024 and 0<len(e)<=len(n),'unsupported RSA key size'
wire=struct.pack('!I',len(n)*8)+n+e.rjust(len(n),b'\0')
print('SHA256:'+hashlib.sha256(wire).hexdigest())
