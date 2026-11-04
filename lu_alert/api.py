"""HTTP client for the LU-Alert dataset on data.public.lu (standard library only, no Domoticz).

Two requests exist: the description of the dataset (a JSON document that lists one file per CAP message) and one
alert file. Both go over https only (a redirect to http is refused), the certificate is always verified, every answer
is size-limited (also after decompression), and the dataset request is conditional (ETag / Last-Modified) when the
server supports it.

The file addresses come out of the dataset description, so they are not trusted blindly: a file is only requested
from the host of the dataset or from a host in the same domain (``data.public.lu`` -> ``*.public.lu``), or from a host
the user allowed in ``.env`` (LU_ALLOWED_HOSTS). An address anywhere else is never requested, a redirect to one is
refused: it could point Domoticz at a device in your own network.
"""
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
import zlib
from typing import Any, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from .constants import MAX_DATASET_BYTES, MAX_XML_BYTES, USER_AGENT

# error kinds: the controller decides how long to wait from them
NETWORK, TLS, HTTP, DATA, TOO_LARGE, CONFIG, BLOCKED = (
    "network", "tls", "http", "data", "too-large", "config", "blocked")


class ApiError(Exception):
    def __init__(self, message: str, kind: str = NETWORK) -> None:
        super().__init__(message)
        self.kind = kind


class Resource(NamedTuple):
    """One alert file of the dataset."""
    url: str
    modified: str                   # "last_modified|checksum": tells whether the file changed, and sorts by age
    title: str = ""


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https and only to a host the client may talk to."""

    def __init__(self, allowed) -> None:
        self._allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != "https":
            raise urllib.error.HTTPError(req.full_url, code, "redirect to a URL that is not https: refused", headers, fp)
        if not self._allowed(newurl):
            raise urllib.error.HTTPError(req.full_url, code, "redirect to %s: refused (not a host of the data portal)"
                                         % (urlsplit(newurl).hostname or "?"), headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _family(host: str) -> str:
    """The domain a file may come from: the last two labels of a host name (``data.public.lu`` -> ``public.lu``);
    an IP address or a single-label name stands for itself."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) > 2 else host


def _read_limited(response: Any, limit: int, what: str) -> bytes:
    """The body of a response, decompressed, at most ``limit`` bytes (an ApiError otherwise)."""
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ApiError("%s is larger than %d bytes" % (what, limit), TOO_LARGE)
    encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    if encoding in ("gzip", "x-gzip"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out = decoder.decompress(raw, limit + 1)
        except zlib.error as exc:
            raise ApiError("%s is not valid gzip data: %s" % (what, exc), DATA)
        if len(out) > limit or decoder.unconsumed_tail:
            raise ApiError("%s is larger than %d bytes after decompression" % (what, limit), TOO_LARGE)
        if not decoder.eof:
            raise ApiError("%s: the gzip data ends too early (the answer was cut off)" % what, DATA)
        return out
    if encoding not in ("", "identity"):
        raise ApiError("%s uses the unsupported content encoding %r" % (what, encoding), DATA)
    return raw


class Client:
    def __init__(self, dataset_url: str, timeout: int = 10, ssl_context: Optional[ssl.SSLContext] = None,
                 user_agent: str = USER_AGENT, allowed_hosts: Iterable[str] = ()) -> None:
        self.dataset_url = dataset_url
        self.timeout = timeout
        self.user_agent = user_agent
        self._home = (urlsplit(dataset_url).hostname or "").lower().rstrip(".")
        self._family = _family(self._home)
        self._extra = tuple(h.lower().strip().strip(".") for h in allowed_hosts if h.strip().strip("."))
        self._opener = urllib.request.build_opener(
            _HttpsOnly(self.host_allowed), urllib.request.HTTPSHandler(context=ssl_context or ssl.create_default_context()))
        self._etag: Optional[str] = None
        self._modified: Optional[str] = None
        self._last_list: Optional[List[Resource]] = None

    def host_allowed(self, url: str) -> bool:
        """May this client request ``url``? The dataset's own host, its domain, or a host from LU_ALLOWED_HOSTS."""
        try:
            host = (urlsplit(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        if not host:
            return False
        if host == self._home or host == self._family or host.endswith("." + self._family):
            return True
        return any(host == extra or host.endswith("." + extra) for extra in self._extra)

    # -- requests -------------------------------------------------------------------------------------------
    def _get(self, url: str, accept: str, limit: int, what: str,
             headers: Optional[dict] = None) -> Tuple[Optional[bytes], Any]:
        """(body, response headers) of ``url``; (None, None) for HTTP 304. Raises ApiError."""
        if urlsplit(url).scheme.lower() != "https":
            raise ApiError("%s: only https URLs are used, got %s" % (what, url.split("?")[0]), CONFIG)
        if not self.host_allowed(url):
            raise ApiError("%s: %s is not a host of the data portal (%s) and is not requested; if the portal moved "
                           "its files, add the host to LU_ALLOWED_HOSTS in .env"
                           % (what, urlsplit(url).hostname or "?", self._family), BLOCKED)
        request = urllib.request.Request(url, headers=dict({"User-Agent": self.user_agent, "Accept": accept,
                                                            "Accept-Encoding": "gzip"}, **(headers or {})))
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return _read_limited(response, limit, what), response.headers
        except urllib.error.HTTPError as exc:
            exc.close()                                     # frees the connection of an answer we do not read
            if exc.code == 304:
                return None, None
            raise ApiError("%s: HTTP %d %s" % (what, exc.code, exc.reason), HTTP)
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise ApiError("%s: TLS error: the certificate of the server is not trusted (%s). Check the system's "
                               "certificate store, or the SSL_CERT_FILE of the Domoticz service" % (what, reason.verify_message), TLS)
            if isinstance(reason, ssl.SSLError):
                raise ApiError("%s: TLS error: %s" % (what, reason), TLS)
            raise ApiError("%s: %s" % (what, reason), NETWORK)
        except (socket.timeout, TimeoutError):
            raise ApiError("%s: no answer within %d s" % (what, self.timeout), NETWORK)
        except ssl.SSLError as exc:
            raise ApiError("%s: TLS error: %s" % (what, exc), TLS)
        except (OSError, ValueError) as exc:               # connection reset, incomplete read, bad URL
            raise ApiError("%s: %s: %s" % (what, type(exc).__name__, exc), NETWORK)

    def list_resources(self, max_resources: int) -> List[Resource]:
        """The newest alert files of the dataset, newest first."""
        headers = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._modified:
            headers["If-Modified-Since"] = self._modified
        body, seen = self._get(self.dataset_url, "application/json", MAX_DATASET_BYTES, "dataset description", headers)
        if body is None:
            if self._last_list is None:
                raise ApiError("dataset description: HTTP 304 without a cached copy", DATA)
            return self._last_list[:max_resources]
        try:
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError("dataset description: the answer is not JSON (did the data portal change its API?)", DATA)
        resources = data.get("resources") if isinstance(data, dict) else None
        if not isinstance(resources, list):
            raise ApiError("dataset description: no 'resources' list in the answer", DATA)
        listed = _newest_xml_files(resources)
        self._last_list = listed
        self._etag = seen.get("ETag") if seen is not None else None
        self._modified = seen.get("Last-Modified") if seen is not None else None
        return listed[:max_resources]

    def get_xml(self, url: str) -> bytes:
        body, _ = self._get(url, "application/xml, text/xml", MAX_XML_BYTES, "alert file")
        if body is None:
            raise ApiError("alert file: unexpected HTTP 304", DATA)
        return body


def _newest_xml_files(resources: List[Any]) -> List[Resource]:
    found = []
    for item in resources:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        fmt = str(item.get("format") or "").lower()
        mime = str(item.get("mime") or "").lower()
        if fmt != "xml" and "xml" not in mime:
            continue
        checksum = item.get("checksum")
        digest = checksum.get("value", "") if isinstance(checksum, dict) else ""
        stamp = str(item.get("last_modified") or item.get("published") or item.get("created_at") or "")
        found.append(Resource(item["url"], "%s|%s" % (stamp, digest), str(item.get("title") or "")))
    found.sort(key=lambda r: r.modified, reverse=True)
    return found
