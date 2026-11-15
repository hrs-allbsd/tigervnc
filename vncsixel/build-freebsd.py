#!/usr/bin/env python3
"""Configure and build vncsixel out of tree on FreeBSD at nice 20."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--build-dir', type=Path)
parser.add_argument('--jobs', type=int, default=4)
parser.add_argument('--test', action='store_true')
parser.add_argument('--without-host-cursor', action='store_true')
args = parser.parse_args()
if platform.system() != 'FreeBSD' or args.jobs < 1:
    parser.error('FreeBSD and a positive --jobs value are required')
source = Path(__file__).resolve().parent.parent
build = (args.build_dir or source.parent / 'obj/freebsd-sixel').resolve()
if build == source or source in build.parents:
    parser.error('build directory must be outside the source tree')
os.setpriority(os.PRIO_PROCESS, 0, 20)
assert os.getpriority(os.PRIO_PROCESS, 0) == 20
print('Build nice: 20', flush=True)
epoch = subprocess.check_output(['git', '-C', str(source), 'show', '-s', '--format=%ct'], text=True)
stamp = datetime.fromtimestamp(int(epoch), timezone.utc).strftime('%Y-%m-%d %H:%M')
cmd = ['cmake', '-S', str(source), '-B', str(build), '-G', 'Ninja',
       '-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DCMAKE_PREFIX_PATH=/usr/local',
       '-DBUILD_SIXEL_VIEWER=ON', '-DBUILD_VIEWER=OFF', '-DBUILD_JAVA=OFF',
       '-DBUILD_X11=OFF', '-DCMAKE_DISABLE_FIND_PACKAGE_X11=ON',
       '-DENABLE_H264=OFF', '-DENABLE_AUDIO=OFF', '-DENABLE_WAYLAND=OFF',
       '-DENABLE_PAM=OFF', '-DENABLE_SELINUX=OFF', '-DENABLE_SYSTEMD=OFF',
       '-DENABLE_PWQUALITY=OFF', '-DINSTALL_SYSTEMD_UNITS=OFF',
       '-DENABLE_GNUTLS=ON', '-DENABLE_NETTLE=ON', '-DENABLE_NLS=ON',
       '-DBUILD_TIMESTAMP=' + stamp]
if args.without_host_cursor:
    cmd.append('-DENABLE_HOST_CURSOR=OFF')
else:
    cmd.append('-DENABLE_HOST_CURSOR=ON')
if args.test:
    cmd.append('-DCMAKE_REQUIRE_FIND_PACKAGE_GTest=ON')
subprocess.run(cmd, check=True)
targets = ['vncsixel'] + (['vncsixel-input-tests', 'vncsixel-memory-tests'] if args.test else [])
subprocess.run(['cmake', '--build', str(build), '--parallel', str(args.jobs),
                '--target', *targets], check=True)
if args.test:
    subprocess.run(['ctest', '--test-dir', str(build / 'vncsixel'),
                    '--output-on-failure', '--no-tests=error'], check=True)
print('Viewer:', build / 'vncsixel/vncsixel')
