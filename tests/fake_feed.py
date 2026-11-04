"""A fake data.public.lu on a real (optionally TLS) HTTP server: the dataset description and the alert files.

    feed.add("a1", cap_xml(...), modified="2026-11-02T10:00:00")   publish a file
    feed.remove("a1")                                              take it off the list (the file stays served)
    feed.fail.append(("status", 503))     the next request answers HTTP 503
    feed.fail.append(("drop",))           the next request is cut off without an answer
    feed.fail.append(("garbage",))        the next request answers 200 with text that is not what it should be
    feed.fail.append(("redirect", url))   the next request answers 302
    feed.fail.append(("hang", seconds))   the next request is not answered for that long
    feed.fail.append(("ok",))             the next request is served normally (to fail a later one)
    feed.gzip = True                      answers are gzip-compressed
    feed.etag = True                      the dataset description carries an ETag and honours If-None-Match
    feed.dataset_extra = {...}            extra top-level keys of the description
"""
import gzip
import hashlib
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATASET_PATH = "/api/1/datasets/67aca67bcaea3ae62308114f/"


class FakeFeed:
    def __init__(self):
        self.files = {}                 # name -> (bytes, modified)
        self.listed = []                # names in the description
        self.requests = []              # path of every request
        self.fail = []
        self.gzip = False
        self.etag = False
        self.conditional = []           # (If-None-Match) seen on the description
        self.dataset_extra = {}
        self.resource_extra = {}        # name -> dict merged into that resource
        self.lock = threading.Lock()
        self.server = None
        self.thread = None
        self.scheme = "http"

    def start(self, certfile=None, keyfile=None):
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.state = self
        if certfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile, keyfile)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
            self.scheme = "https"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    @property
    def base(self):
        return "%s://127.0.0.1:%d" % (self.scheme, self.server.server_address[1])

    @property
    def dataset_url(self):
        return self.base + DATASET_PATH

    def add(self, name, xml, modified="2026-11-02T10:00:00"):
        data = xml if isinstance(xml, bytes) else xml.encode("utf-8")
        with self.lock:
            self.files[name] = (data, modified)
            if name not in self.listed:
                self.listed.append(name)

    def remove(self, name):
        with self.lock:
            self.listed.remove(name)

    def count(self, prefix):
        return len([p for p in self.requests if p.startswith(prefix)])

    def description(self):
        with self.lock:
            resources = []
            for name in self.listed:
                data, modified = self.files[name]
                item = {"title": name, "url": "%s/files/%s.xml" % (self.base, name), "format": "xml",
                        "mime": "application/xml", "last_modified": modified,
                        "checksum": {"type": "sha1", "value": hashlib.sha1(data).hexdigest()}}
                item.update(self.resource_extra.get(name, {}))
                resources.append(item)
            resources.append({"title": "specification", "url": self.base + "/files/cap-lu.pdf", "format": "pdf",
                              "mime": "application/pdf", "last_modified": "2026-03-19T07:29:19"})
            doc = {"id": "67aca67bcaea3ae62308114f", "title": "Alertes du système LU-Alert", "resources": resources}
            doc.update(self.dataset_extra)
            return json.dumps(doc).encode("utf-8")


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass                            # a client that hangs up or speaks the wrong protocol is part of the tests


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        state = self.server.state
        headers = dict(extra or {})
        if state.gzip and body:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        state = self.server.state
        path = self.path
        with state.lock:
            state.requests.append(path)
            fail = state.fail.pop(0) if state.fail else None
        if fail:
            kind = fail[0]
            if kind == "status":
                return self._send(fail[1], b"error", "text/plain")
            if kind == "drop":
                self.close_connection = True
                self.connection.close()
                return
            if kind == "garbage":
                return self._send(200, b"this is not what you asked for", "text/plain")
            if kind == "hang":
                time.sleep(fail[1])
                self.close_connection = True
                return
            if kind == "redirect":
                self.send_response(302)
                self.send_header("Location", fail[1])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if path == DATASET_PATH:
            body = state.description()
            extra = {}
            if state.etag:
                tag = '"%s"' % hashlib.sha1(body).hexdigest()
                seen = self.headers.get("If-None-Match")
                state.conditional.append(seen)
                if seen == tag:
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                extra["ETag"] = tag
            return self._send(200, body, extra=extra)
        if path.startswith("/files/") and path.endswith(".xml"):
            name = path[len("/files/"):-len(".xml")]
            with state.lock:
                entry = state.files.get(name)
            if entry is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, entry[0], "application/xml")
        return self._send(404, b"not found", "text/plain")
