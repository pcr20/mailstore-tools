#!/bin/sh
# Build the MailStore DBCRYPT crypt plugin against a Firebird 4 install.
# Usage: FB=/opt/firebird ./build.sh   (defaults to /opt/firebird)
set -e
FB="${FB:-/opt/firebird}"
g++ -shared -fPIC -O2 -I"$FB/include" MsDbCrypt.cpp -o DBCRYPT.so -lcrypto
echo "built DBCRYPT.so -> install with: cp DBCRYPT.so $FB/plugins/ and add the plugins.conf entry"
