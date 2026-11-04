"""The client against a fake data.public.lu on a real TLS server: what is requested, what is refused, what is said."""
import gzip
import ssl
import unittest

import helpers  # noqa: F401
from helpers import start_feed
from lu_alert import api
from lu_alert.api import ApiError, Client, _family, _newest_xml_files
from lu_alert.constants import MAX_XML_BYTES


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.fake, self.context = start_feed(self)

    def client(self, **kw):
        kw.setdefault("timeout", 3)
        return Client(self.fake.dataset_url, ssl_context=self.context, **kw)


class ListingTests(ApiCase):
    def test_the_newest_xml_files_come_first_and_other_formats_are_left_out(self):
        self.fake.add("old", "<a/>", modified="2026-11-01T08:00:00")
        self.fake.add("new", "<a/>", modified="2026-11-02T09:00:00")
        self.fake.add("mid", "<a/>", modified="2026-11-02T01:00:00")
        found = self.client().list_resources(100)
        self.assertEqual([r.url.rsplit("/", 1)[1] for r in found], ["new.xml", "mid.xml", "old.xml"])
        self.assertTrue(found[0].modified.startswith("2026-11-02T09:00:00|"))

    def test_the_limit(self):
        for i in range(5):
            self.fake.add("f%d" % i, "<a/>", modified="2026-11-02T0%d:00:00" % i)
        self.assertEqual([r.url.rsplit("/", 1)[1] for r in self.client().list_resources(2)], ["f4.xml", "f3.xml"])

    def test_an_empty_dataset(self):
        self.assertEqual(self.client().list_resources(100), [])

    def test_the_format_may_be_given_by_the_mime_type_alone(self):
        self.fake.add("a", "<a/>")
        self.fake.resource_extra["a"] = {"format": "", "mime": "text/xml"}
        self.assertEqual(len(self.client().list_resources(10)), 1)
        self.fake.resource_extra["a"] = {"format": "json", "mime": "application/json"}
        self.assertEqual(self.client().list_resources(10), [])

    def test_a_changed_file_has_another_version_stamp(self):
        self.fake.add("a", "<a>1</a>", modified="2026-11-02T09:00:00")
        first = self.client().list_resources(10)[0].modified
        self.fake.add("a", "<a>2</a>", modified="2026-11-02T09:00:00")
        self.assertNotEqual(self.client().list_resources(10)[0].modified, first)

    def test_odd_entries_are_skipped(self):
        found = _newest_xml_files([None, "x", {"format": "xml"}, {"url": 5, "format": "xml"},
                                   {"url": "https://a/b.xml", "format": "XML", "checksum": "bad"}])
        self.assertEqual([r.url for r in found], ["https://a/b.xml"])

    def test_a_request_carries_a_user_agent_and_asks_for_gzip(self):
        self.client().list_resources(10)
        self.assertEqual(self.fake.requests, ["/api/1/datasets/67aca67bcaea3ae62308114f/"])

    def test_gzip_answers_are_decoded(self):
        self.fake.gzip = True
        self.fake.add("a", "<alert>é</alert>")
        client = self.client()
        self.assertEqual(len(client.list_resources(10)), 1)
        self.assertEqual(client.get_xml(self.fake.base + "/files/a.xml"), "<alert>é</alert>".encode("utf-8"))

    def test_the_description_is_requested_conditionally(self):
        self.fake.etag = True
        self.fake.add("a", "<a/>")
        client = self.client()
        first = client.list_resources(10)
        second = client.list_resources(10)          # HTTP 304: the cached list
        self.assertEqual(first, second)
        self.assertEqual(len(self.fake.conditional), 2)
        self.assertIsNone(self.fake.conditional[0])
        self.assertTrue(self.fake.conditional[1].startswith('"'))
        self.assertEqual(client.list_resources(1), first[:1])

    def test_a_not_modified_without_a_copy_is_an_error(self):
        client = self.client()
        client._etag = "x"
        self.fake.etag = True
        self.fake.fail.append(("status", 304))
        with self.assertRaises(ApiError) as caught:
            client.list_resources(10)
        self.assertEqual(caught.exception.kind, api.DATA)


class FailureTests(ApiCase):
    def error(self, call):
        with self.assertRaises(ApiError) as caught:
            call()
        return caught.exception

    def test_http_errors(self):
        self.fake.fail.append(("status", 503))
        exc = self.error(lambda: self.client().list_resources(10))
        self.assertEqual(exc.kind, api.HTTP)
        self.assertIn("dataset description: HTTP 503", str(exc))

    def test_a_connection_that_is_cut_off(self):
        self.fake.fail.append(("drop",))
        self.assertEqual(self.error(lambda: self.client().list_resources(10)).kind, api.NETWORK)

    def test_an_answer_that_is_not_json(self):
        self.fake.fail.append(("garbage",))
        exc = self.error(lambda: self.client().list_resources(10))
        self.assertEqual(exc.kind, api.DATA)
        self.assertIn("not JSON", str(exc))

    def test_json_without_resources(self):
        for extra in ({"resources": "no"}, {"resources": None}):
            self.fake.dataset_extra = extra
            exc = self.error(lambda: self.client().list_resources(10))
            self.assertEqual(exc.kind, api.DATA)
            self.assertIn("no 'resources' list", str(exc))

    def test_no_answer_in_time(self):
        self.fake.fail.append(("hang", 2))
        exc = self.error(lambda: self.client(timeout=1).list_resources(10))
        self.assertEqual(exc.kind, api.NETWORK)
        self.assertIn("no answer within 1 s", str(exc))

    def test_a_server_that_is_not_there(self):
        client = Client("https://127.0.0.1:1/x", timeout=2, ssl_context=self.context)
        self.assertEqual(self.error(lambda: client.list_resources(10)).kind, api.NETWORK)

    def test_a_certificate_that_is_not_trusted_says_where_to_look(self):
        exc = self.error(lambda: Client(self.fake.dataset_url, timeout=3).list_resources(10))   # the system's CAs only
        self.assertEqual(exc.kind, api.TLS)
        self.assertIn("certificate of the server is not trusted", str(exc))
        self.assertIn("SSL_CERT_FILE", str(exc))

    def test_a_file_that_is_too_large(self):
        self.fake.add("big", b"x" * (MAX_XML_BYTES + 1))
        exc = self.error(lambda: self.client().get_xml(self.fake.base + "/files/big.xml"))
        self.assertEqual(exc.kind, api.TOO_LARGE)

    def test_a_gzip_bomb_is_stopped_after_decompression(self):
        self.fake.add("bomb", b"\0" * (MAX_XML_BYTES * 5))
        self.fake.gzip = True            # about 5 kB on the wire, 10 MB decompressed
        exc = self.error(lambda: self.client().get_xml(self.fake.base + "/files/bomb.xml"))
        self.assertEqual(exc.kind, api.TOO_LARGE)
        self.assertIn("after decompression", str(exc))

    def test_a_missing_file(self):
        exc = self.error(lambda: self.client().get_xml(self.fake.base + "/files/nothing.xml"))
        self.assertEqual((exc.kind, str(exc)), (api.HTTP, "alert file: HTTP 404 Not Found"))


class SecurityTests(ApiCase):
    def error(self, call):
        with self.assertRaises(ApiError) as caught:
            call()
        return caught.exception

    def test_only_https_is_requested(self):
        exc = self.error(lambda: self.client().get_xml("http://127.0.0.1:1/a.xml"))
        self.assertEqual(exc.kind, api.CONFIG)
        self.assertEqual(self.fake.requests, [])

    def test_a_host_outside_the_portal_is_never_requested(self):
        exc = self.error(lambda: self.client().get_xml("https://192.168.1.10/a.xml"))
        self.assertEqual(exc.kind, api.BLOCKED)
        self.assertIn("is not a host of the data portal", str(exc))
        self.assertIn("LU_ALLOWED_HOSTS", str(exc))

    def test_the_hosts_a_file_may_come_from(self):
        client = Client("https://data.public.lu/api/1/datasets/x/", allowed_hosts=("files.example.lu",))
        for url in ("https://data.public.lu/a.xml", "https://static.data.public.lu/a.xml", "https://public.lu/a.xml",
                    "https://files.example.lu/a.xml", "https://sub.files.example.lu/a.xml", "https://DATA.public.lu./a"):
            self.assertTrue(client.host_allowed(url), url)
        for url in ("https://evil.example/a.xml", "https://public.lu.evil.example/a.xml", "https://notpublic.lu/a.xml",
                    "https://example.lu/a.xml", "https:///a.xml", "https://[bad/a.xml", ""):
            self.assertFalse(client.host_allowed(url), url)

    def test_an_address_stands_for_itself(self):
        self.assertEqual(_family("127.0.0.1"), "127.0.0.1")
        self.assertEqual(_family("data.public.lu"), "public.lu")
        self.assertEqual(_family("a.b.data.public.lu"), "public.lu")
        self.assertEqual(_family("localhost"), "localhost")

    def test_the_allowed_host_list_opens_a_host_up(self):
        client = Client("https://data.public.lu/x/", allowed_hosts=("127.0.0.1",))
        self.assertTrue(client.host_allowed("https://127.0.0.1:9/a.xml"))

    def test_a_redirect_to_http_is_refused(self):
        self.fake.fail.append(("redirect", "http://127.0.0.1:1/x"))
        exc = self.error(lambda: self.client().list_resources(10))
        self.assertEqual(exc.kind, api.HTTP)
        self.assertIn("not https: refused", str(exc))

    def test_a_redirect_to_a_foreign_host_is_refused(self):
        self.fake.fail.append(("redirect", "https://192.168.1.10/x"))
        exc = self.error(lambda: self.client().list_resources(10))
        self.assertEqual(exc.kind, api.HTTP)
        self.assertIn("redirect to 192.168.1.10: refused", str(exc))

    def test_a_redirect_to_the_same_host_is_followed(self):
        self.fake.add("a", "<a/>")
        self.fake.fail.append(("redirect", self.fake.dataset_url))
        self.assertEqual(len(self.client().list_resources(10)), 1)

    def test_content_encodings_other_than_gzip_are_refused(self):
        class Response:
            headers = {"Content-Encoding": "br"}

            def read(self, n):
                return b"x"
        with self.assertRaises(ApiError) as caught:
            api._read_limited(Response(), 100, "alert file")
        self.assertEqual(caught.exception.kind, api.DATA)

    def test_gzip_that_is_broken(self):
        class Response:
            headers = {"Content-Encoding": "gzip"}

            def read(self, n):
                return gzip.compress(b"hello")[:-6]
        with self.assertRaises(ApiError) as caught:
            api._read_limited(Response(), 100, "alert file")
        self.assertEqual(caught.exception.kind, api.DATA)
        self.assertIn("ends too early", str(caught.exception))


class PlainHttpTests(unittest.TestCase):
    def test_a_server_that_does_not_speak_tls_is_a_tls_or_network_error(self):
        from fake_feed import FakeFeed
        fake = FakeFeed().start()
        self.addCleanup(fake.stop)
        with self.assertRaises(ApiError) as caught:
            Client(fake.dataset_url.replace("http://", "https://"), timeout=2,
                   ssl_context=ssl.create_default_context()).list_resources(10)
        self.assertIn(caught.exception.kind, (api.TLS, api.NETWORK))


if __name__ == "__main__":
    unittest.main()
