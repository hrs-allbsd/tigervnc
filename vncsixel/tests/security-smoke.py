#!/usr/bin/env python3
"""Exercise RSA-AES trust and TLS using private Xvnc servers and a PTY.

Temporary keys, certificates, passwords and trust stores never leave the fixture.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import socket
import subprocess
import tempfile
import termios
import time
import threading

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('viewer',type=Path)
parser.add_argument('--report',required=True,type=Path)
args=parser.parse_args()
checks=[]
def controlling_tty():
    os.setsid(); fcntl.ioctl(0,termios.TIOCSCTTY,0)
with tempfile.TemporaryDirectory() as directory, open(os.devnull,'wb') as null:
    root=Path(directory)
    (root/'home').mkdir()
    for name in ('rsa1','rsa2'):
        subprocess.run(['openssl','genrsa','-out',str(root/name),'2048'],stdout=null,stderr=null,check=True)
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'tls.key'),
        '-out',str(root/'tls.crt'),'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost',
        '-addext','basicConstraints=critical,CA:TRUE','-days','1'],stdout=null,stderr=null,check=True)
    subprocess.run(['openssl','pkey','-in',str(root/'rsa1'),'-pubout','-out',str(root/'rsa1.pub')],stdout=null,stderr=null,check=True)
    fingerprint=subprocess.check_output(['python3',str(Path(__file__).with_name('host-key-fingerprint.py')),str(root/'rsa1.pub')],text=True).strip()
    password=root/'passwd'
    password.write_bytes(subprocess.check_output(['vncpasswd','-f'],input=b'fixture\n'))
    password.chmod(0o600)
    def start(security,key='rsa1',port=None,certificate='tls.crt'):
        if port is None:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        r,w=os.pipe()
        log=(root/'server.log').open('wb')
        server=subprocess.Popen(['Xvnc','-displayfd',str(w),'-geometry','320x240','-noreset',
            '-localhost','-rfbport',str(port),'-SecurityTypes',security,'-PasswordFile',str(password),
            '-RSAKey',str(root/key),'-X509Cert',str(root/certificate),'-X509Key',str(root/'tls.key'),
            '-UseBlacklist=0'],pass_fds=(w,),stdout=log,stderr=log)
        os.close(w)
        if not select.select([r],[],[],15)[0]:
            server.terminate();server.wait();raise AssertionError('Xvnc launch timeout')
        ready=os.read(r,80);os.close(r);log.close()
        assert ready, (root/'server.log').read_text()
        return server,port
    def run(label,security,port,options=(),answer=None,accepted=True,expected=None,host='localhost'):
        master,slave=pty.openpty();saved=termios.tcgetattr(slave)
        env=dict(os.environ,VNC_PASSWORD='fixture')
        env.pop('VNC_USERNAME',None)
        env.pop('DISPLAY',None);env.pop('WINDOWID',None)
        # Isolate default trust files as well as explicit KnownHosts cases.
        env['HOME']=str(root/'home')
        env['XDG_DATA_HOME']=str(root/'xdg')
        env['XDG_CONFIG_HOME']=str(root/'config')
        pidfile,perf=root/'viewer.pid',root/'perf.json'
        perf.unlink(missing_ok=True)
        wrapper='pidfile=$1; shift; "$@" & p=$!; echo $p > "$pidfile"; wait $p; result=$?; printf "SEC_DONE:%s\\n" "$result"; read ignored; exit "$result"'
        viewer=subprocess.Popen(['/bin/sh','-c',wrapper,'security',str(pidfile),str(args.viewer.resolve()),
            '-SecurityTypes='+security,'-ViewOnly','-PerfLog='+str(perf),*options,host+'::'+str(port)],
            env=env,stdin=slave,stdout=slave,stderr=slave,preexec_fn=controlling_tty)
        transcript,pending=bytearray(),bytearray()
        responses={b'\x1b[c':b'\x1b[?63;1;4c',b'\x1b[14t':b'\x1b[4;468;600t',
            b'\x1b[16t':b'\x1b[6;13;6t',b'\x1b[?1;1;0S':b'\x1b[?1;0;256S',
            b'\x1b[?2;1;0S':b'\x1b[?2;0;600;468S',b'\x1b[?1016$p':b'\x1b[?1016;2$y',b'\x1b[?4m':b'\x1b[>4;0m'}
        answered=stopped=False
        try:
            deadline=time.monotonic()+20
            while b'SEC_DONE:' not in transcript:
                assert time.monotonic()<deadline,(label,'timeout',bytes(transcript[-500:]))
                if not select.select([master],[],[],.05)[0]:continue
                chunk=os.read(master,65536);assert chunk
                transcript.extend(chunk);pending.extend(chunk)
                if b'or no [no]: ' in transcript and not answered:
                    assert answer is not None,(label,'unexpected trust prompt')
                    os.write(master,answer.encode()+b'\n');answered=True
                for query,response in responses.items():
                    while query in pending:
                        offset=pending.index(query);del pending[:offset+len(query)]
                        os.write(master,response)
                if b'\x1bP' in transcript and b'\x1b\\' in transcript and not stopped:
                    assert accepted,(label,'unexpected framebuffer before rejection')
                    os.kill(int(pidfile.read_text()),signal.SIGTERM);stopped=True
            assert (b'SEC_DONE:0' in transcript)==accepted,(label,bytes(transcript[-700:]))
            assert answered==(answer is not None),(label,'missing prompt',bytes(transcript[-1200:]),(root/'server.log').read_text()[-1000:])
            if expected:assert expected.encode() in transcript,(label,bytes(transcript[-700:]))
            if accepted:assert json.loads(perf.read_text())['frames']>0,label
            assert termios.tcgetattr(slave)==saved,(label,'termios changed')
            os.write(master,b'\n');viewer.wait(timeout=5)
            checks.append(label)
        finally:
            if viewer.poll() is None:
                if pidfile.exists():
                    try:os.kill(int(pidfile.read_text()),signal.SIGTERM)
                    except ProcessLookupError:pass
                viewer.kill();viewer.wait()
            os.close(master);os.close(slave)
    def expire_in_handshake(port,deadline):
        # Hold the first ClientHello after CRL import, then let TLS finish.
        listener=socket.socket()
        listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(10)
        proxyport=listener.getsockname()[1]
        stop=threading.Event();observed=[];errors=[]
        def forward():
            tail=b''
            try:
                with listener.accept()[0] as downstream, socket.create_connection(('127.0.0.1',port),10) as upstream:
                    while not stop.is_set():
                        readable,_,_=select.select([downstream,upstream],[],[],.1)
                        for source in readable:
                            chunk=source.recv(65536)
                            if not chunk:return
                            if source is downstream:
                                if not observed and b'\x16\x03' in tail+chunk:
                                    observed.append(time.time())
                                    if stop.wait(max(0,deadline-time.time()+1)):return
                                tail=chunk[-1:]
                            (upstream if source is downstream else downstream).sendall(chunk)
            except (ConnectionResetError,BrokenPipeError):
                pass
            except Exception as error:
                if not stop.is_set():errors.append(str(error))
        thread=threading.Thread(target=forward,daemon=True);thread.start()
        return proxyport,stop,thread,listener,observed,errors
    store=root/'known_hosts'
    options=['-KnownHosts='+str(store)]
    server,port=start('RA2_256')
    try:
        run('strict unknown rejected','RA2_256',port,[*options,'-StrictHostKeyChecking'],accepted=False)
        assert not store.exists()
        run('unknown empty answer rejects','RA2_256',port,options,answer='',accepted=False)
        run('oversized answer rejected','RA2_256',port,options,answer='yes'+'x'*40,accepted=False)
        run('one-time acceptance','RA2_256',port,options,answer='once')
        assert not store.exists()
        run('explicit save','RA2_256',port,options,answer='yes',expected=fingerprint)
        run('default store explicit save','RA2_256',port,answer='yes')
        run('default store strict match','RA2_256',port,['-StrictHostKeyChecking'])
        assert (root/'xdg/tigervnc/vncsixel_rsa_known_hosts').exists()
        before=store.read_bytes();assert store.stat().st_mode&0o777==0o600
        run('stored key accepted without prompt','RA2_256',port,[*options,'-StrictHostKeyChecking'])
        assert store.read_bytes()==before
        bad=root/'unsafe';bad.write_bytes(before);bad.chmod(0o666)
        run('unsafe store rejected','RA2_256',port,['-KnownHosts='+str(bad)],accepted=False,expected='Unsafe RSA')
        bad.chmod(0o600);bad.write_text('malformed\n')
        run('malformed store rejected','RA2_256',port,['-KnownHosts='+str(bad)],accepted=False,expected='Malformed RSA')
    finally:server.terminate();server.wait(timeout=10)
    server,_=start('RA2_256',key='rsa2',port=port)
    try:
        run('changed key rejected','RA2_256',port,options,accepted=False,expected='RSA host key changed')
        assert store.read_bytes()==before
    finally:server.terminate();server.wait(timeout=10)
    for security in ('RA2','RA2ne','RA2ne_256'):
        server,port=start(security)
        try:
            run(security+' one-time interoperability',security,port,options,answer='once')
            if security=='RA2':run('existing default directory reused',security,port,answer='yes')
        finally:server.terminate();server.wait(timeout=10)
    for security in ('TLSVnc','X509Vnc'):
        server,port=start(security)
        try:
            if security=='X509Vnc':
                run('untrusted X509 rejected',security,port,accepted=False)
                run('trusted X509 accepted',security,port,['-X509CA='+str(root/'tls.crt')])
                run('X509 name mismatch rejected',security,port,['-X509CA='+str(root/'tls.crt')],accepted=False,host='127.0.0.1')
            else:run('anonymous TLS interoperability',security,port)
        finally:server.terminate();server.wait(timeout=10)
    # A temporary CA issues valid, expired, future and wrong-purpose leaves.
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'ca.key'),
        '-out',str(root/'ca.crt'),'-subj','/CN=Fixture CA','-addext','basicConstraints=critical,CA:TRUE',
        '-days','3650'],stdout=null,stderr=null,check=True)
    (root/'index').write_text(''); (root/'serial').write_text('1000\n'); (root/'crlnumber').write_text('2000\n')
    (root/'newcerts').mkdir()
    config=root/'ca.cnf'
    config.write_text(f"""[ca]
default_ca = fixture
[fixture]
database = {root}/index
new_certs_dir = {root}/newcerts
certificate = {root}/ca.crt
private_key = {root}/ca.key
serial = {root}/serial
crlnumber = {root}/crlnumber
default_md = sha256
default_days = 1
default_crl_days = 1
unique_subject = no
policy = names
[names]
commonName = supplied
[server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost
[client]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = clientAuth
subjectAltName = DNS:localhost
""")
    subprocess.run(['openssl','req','-new','-key',str(root/'tls.key'),'-out',str(root/'leaf.csr'),
        '-subj','/CN=localhost'],stdout=null,stderr=null,check=True)
    ca=['openssl','ca','-batch','-config',str(config)]
    for name,extension,dates in [('valid','server',[]),
        ('expired','server',['-startdate','20000101000000Z','-enddate','20010101000000Z']),
        ('future','server',['-startdate','20990101000000Z','-enddate','21000101000000Z']),
        ('client','client',[])]:
        subprocess.run([*ca,'-in',str(root/'leaf.csr'),'-out',str(root/(name+'.crt')),
            '-extensions',extension,*dates],stdout=null,stderr=null,check=True)
    subprocess.run([*ca,'-gencrl','-out',str(root/'empty.crl')],stdout=null,stderr=null,check=True)
    # Empty, correctly signed CRLs must still be within their validity window.
    for name,begin,end in [('stale','20000101000000Z','20010101000000Z'),
        ('future','20990101000000Z','21000101000000Z')]:
        subprocess.run([*ca,'-gencrl','-crl_lastupdate',begin,'-crl_nextupdate',end,
            '-out',str(root/(name+'.crl'))],stdout=null,stderr=null,check=True)
    for name in ('stale','future'):
        for order,parts in [('first',[name,'empty']),('last',['empty',name])]:
            (root/(name+'-'+order+'.crl')).write_bytes(
                b''.join((root/(part+'.crl')).read_bytes() for part in parts))
    (root/'current-bundle.crl').write_bytes((root/'empty.crl').read_bytes()*2)
    subprocess.run([*ca,'-revoke',str(root/'valid.crt')],stdout=null,stderr=null,check=True)
    subprocess.run([*ca,'-gencrl','-out',str(root/'revoked.crl')],stdout=null,stderr=null,check=True)
    (root/'invalid.crl').write_text('invalid CRL\n')
    (root/'zero.crl').write_text('')
    (root/'invalid.ca').write_text('invalid CA\n')
    (root/'zero.ca').write_text('')
    for name,accepted in [('valid',True),('expired',False),('future',False),('client',False)]:
        server,port=start('X509Vnc',certificate=name+'.crt')
        try:
            run(name+' leaf certificate','X509Vnc',port,['-X509CA='+str(root/'ca.crt')],accepted=accepted)
            if name=='valid':
                run('non-revoked CRL accepts','X509Vnc',port,['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/'empty.crl')])
                run('current CRL bundle accepts','X509Vnc',port,
                    ['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/'current-bundle.crl')])
                for crl in ('stale','future','stale-first','stale-last','future-first','future-last'):
                    diagnostic='X509CRL has expired' if crl.startswith('stale') else 'X509CRL is not yet valid'
                    run(crl+' CRL rejected','X509Vnc',port,
                        ['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/(crl+'.crl'))],
                        accepted=False,expected=diagnostic)
                deadline=int(time.time())+8
                nextupdate=datetime.fromtimestamp(deadline,timezone.utc).strftime('%Y%m%d%H%M%SZ')
                subprocess.run([*ca,'-gencrl','-crl_nextupdate',nextupdate,
                    '-out',str(root/'short.crl')],stdout=null,stderr=null,check=True)
                proxyport,stop,thread,listener,observed,errors=expire_in_handshake(port,deadline)
                try:
                    run('CRL expires during TLS handshake','X509Vnc',proxyport,
                        ['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/'short.crl')],
                        accepted=False,expected='X509CRL has expired')
                    assert observed and observed[0]<deadline,'ClientHello must precede CRL expiry'
                    assert not errors,errors
                finally:
                    stop.set();listener.close();thread.join(timeout=11)
                    assert not thread.is_alive(),'TLS proxy did not stop'
                run('revoked leaf rejected','X509Vnc',port,['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/'revoked.crl')],accepted=False)
                for filename in ('missing.crl','invalid.crl','zero.crl'):
                    run(filename+' rejected','X509Vnc',port,['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/filename)],accepted=False,expected='Cannot load specified X509CRL file')
                for filename in ('missing.ca','invalid.ca','zero.ca'):
                    run(filename+' rejected','X509Vnc',port,['-X509CA='+str(root/filename)],accepted=False,expected='Cannot load specified X509CA file')
                run('case-insensitive split CRL rejected','X509Vnc',port,
                    ['-X509CA='+str(root/'ca.crt'),'--x509crl',str(root/'missing.crl')],
                    accepted=False,expected='Cannot load specified X509CRL file')
                run('explicit default CRL rejected','X509Vnc',port,
                    ['-X509CA='+str(root/'ca.crt'),'X509CRL='+str(root/'config/tigervnc/x509_crl.pem')],
                    accepted=False,expected='Cannot load specified X509CRL file')
                run('empty CRL override accepts','X509Vnc',port,
                    ['-X509CA='+str(root/'ca.crt'),'-X509CRL='+str(root/'missing.crl'),'-X509CRL='])
        finally:server.terminate();server.wait(timeout=10)
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps({'checks':checks,'scope':'private Xvnc, generated keys/certificate and dummy password'},indent=2)+'\n')
print('PASS: '+', '.join(checks))
