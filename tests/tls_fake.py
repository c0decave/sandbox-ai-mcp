"""Stand-ins for the services of the servers that reach a user's own host (kubernetes, grafana, imap): a throwaway CA
with a server and a client certificate made with cryptography (in every image's shared lock), and an HTTPS server on
loopback that records what it was asked. Nothing leaves the machine; the keys live in a temporary folder."""
from __future__ import annotations

import datetime as dt
import http.server
import ipaddress
import json
from pathlib import Path
import ssl
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _pem_key(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


class Authority:
    """A CA, a certificate for 127.0.0.1/localhost signed by it (the server's) and one for a client; PEM bytes."""

    def __init__(self, common: str = "sandbox-ai-mcp test CA"):
        now = dt.datetime.now(dt.timezone.utc)
        self._folder = tempfile.TemporaryDirectory(prefix="tls-fake-")
        self.folder = Path(self._folder.name)
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca = (x509.CertificateBuilder().subject_name(_name(common)).issuer_name(_name(common))
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                           content_commitment=False, key_encipherment=False, data_encipherment=False,
                                           key_agreement=False, encipher_only=False, decipher_only=False),
                             critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        self.ca = ca.public_bytes(serialization.Encoding.PEM)

        def leaf(common_name, usage, names=None):
            key = ec.generate_private_key(ec.SECP256R1())
            builder = (x509.CertificateBuilder().subject_name(_name(common_name)).issuer_name(ca.subject)
                       .public_key(key.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
                       .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                       .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
                       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                                      critical=False))
            if names:
                builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
            return builder.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM), _pem_key(key)

        self.server_cert, self.server_key = leaf(
            "localhost", ExtendedKeyUsageOID.SERVER_AUTH,
            [x509.DNSName("localhost"), x509.DNSName("kube.test"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])
        self.client_cert, self.client_key = leaf("agent", ExtendedKeyUsageOID.CLIENT_AUTH)
        for name, data in (("ca.pem", self.ca), ("server.pem", self.server_cert), ("server.key", self.server_key)):
            (self.folder / name).write_bytes(data)

    def server_context(self, client_certificates: bool = False) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.folder / "server.pem", self.folder / "server.key")
        if client_certificates:
            context.load_verify_locations(cadata=self.ca.decode())
            context.verify_mode = ssl.CERT_OPTIONAL
        return context

    def close(self):
        self._folder.cleanup()


class Recorder:
    """What the stand-in was asked: method, path, query (parse_qs), headers, the client's certificate subject."""

    def __init__(self):
        self.requests = []

    def paths(self):
        return [r["path"] for r in self.requests]


def https_server(authority: Authority | None, respond, client_certificates: bool = False):
    """An HTTP(S) server on 127.0.0.1 (a port of its own): RESPOND(request) -> (status, body, headers) for every
    GET/POST/PUT/DELETE/PATCH, the body bytes or a JSON-able value. Returns (server, base URL, recorder); the caller
    shuts it down (server.shutdown(), server.server_close())."""
    recorder = Recorder()

    class Handler(http.server.BaseHTTPRequestHandler):
        def handle_any(self):
            split = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            peer = None
            if authority is not None:
                certificate = self.connection.getpeercert()
                if certificate:
                    peer = dict(item[0] for item in certificate.get("subject", ()))
            request = {"method": self.command, "path": split.path, "query": parse_qs(split.query),
                       "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body, "peer": peer}
            recorder.requests.append(request)
            status, data, headers = respond(request)
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            headers = {"Content-Type": "application/json", **(headers or {})}
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = handle_any  # noqa: N815

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    if authority is not None:
        server.socket = authority.server_context(client_certificates).wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scheme = "https" if authority is not None else "http"
    return server, f"{scheme}://127.0.0.1:{server.server_address[1]}", recorder
