"""Test certificates, made once per test run with openssl: a root CA and a server certificate for localhost."""
import atexit
import os
import shutil
import subprocess
import tempfile

EXTENSIONS = (
    "subjectAltName=DNS:localhost,IP:127.0.0.1\n"
    "basicConstraints=critical,CA:FALSE\n"
    "keyUsage=critical,digitalSignature,keyEncipherment\n"
    "extendedKeyUsage=serverAuth\n"
    "subjectKeyIdentifier=hash\n"
    "authorityKeyIdentifier=keyid\n"
)
_cache = {}


def available():
    return shutil.which("openssl") is not None


def _openssl(*args, cwd):
    subprocess.run(("openssl",) + args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_ca(folder, name):
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", name + ".key", "-out", name + ".pem",
             "-days", "2", "-subj", "/CN=Test Root CA " + name, "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-addext", "subjectKeyIdentifier=hash", cwd=folder)


def get():
    """(folder, ca file, other CA file, server certificate, server key); the folder is removed at exit."""
    if not _cache:
        folder = tempfile.mkdtemp(prefix="lualert-tls-")
        atexit.register(shutil.rmtree, folder, True)
        make_ca(folder, "ca")
        make_ca(folder, "other")
        with open(os.path.join(folder, "ext.cnf"), "w") as fh:
            fh.write(EXTENSIONS)
        _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr", "-subj", "/CN=localhost",
                 cwd=folder)
        _openssl("x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out",
                 "srv.pem", "-days", "2", "-extfile", "ext.cnf", cwd=folder)
        _cache["certs"] = (folder, os.path.join(folder, "ca.pem"), os.path.join(folder, "other.pem"),
                           os.path.join(folder, "srv.pem"), os.path.join(folder, "srv.key"))
    return _cache["certs"]
