import ssl
import unittest
from urllib.error import URLError
from unittest.mock import patch
from urllib.request import Request

from actions.secure_network import TLS_CONTEXT, _SecureRedirectHandler, validate_outbound_url, secure_request


class SecureNetworkTests(unittest.TestCase):
    def test_tls_requires_certificate_and_hostname_verification(self):
        self.assertEqual(TLS_CONTEXT.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(TLS_CONTEXT.check_hostname)
        self.assertGreaterEqual(TLS_CONTEXT.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_public_https_is_allowed(self):
        self.assertEqual(validate_outbound_url('https://example.com/api'), 'https://example.com/api')

    def test_public_http_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unencrypted HTTP'):
            validate_outbound_url('http://example.com/api')

    def test_loopback_http_allowed_only_when_explicit(self):
        with self.assertRaises(ValueError):
            validate_outbound_url('http://127.0.0.1:11434/api/tags')
        self.assertTrue(validate_outbound_url('http://127.0.0.1:11434/api/tags', allow_loopback_http=True))

    def test_private_lan_http_allowed_only_when_explicit(self):
        with self.assertRaises(ValueError):
            validate_outbound_url('http://192.168.1.20:8123/api')
        self.assertTrue(validate_outbound_url('http://192.168.1.20:8123/api', allow_private_http=True))

    def test_credentials_in_url_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Credentials'):
            validate_outbound_url('https://user:pass@example.com/api')

    def test_https_redirect_cannot_downgrade_to_http(self):
        handler = _SecureRedirectHandler()
        request = Request('https://example.com/start')
        with self.assertRaises(URLError):
            handler.redirect_request(request, None, 302, 'Found', {}, 'http://example.com/insecure')

    def test_public_redirect_to_http_is_rejected(self):
        handler = _SecureRedirectHandler()
        request = Request('https://example.com/start')
        with self.assertRaises(URLError):
            handler.redirect_request(request, None, 302, 'Found', {}, 'http://evil.example/collect')

    def test_requests_client_rejects_public_http_before_network_call(self):
        with self.assertRaisesRegex(ValueError, 'Unencrypted HTTP'):
            secure_request('GET', 'http://example.com')

    def test_requests_redirect_is_checked_before_following(self):
        class FakeResponse:
            status_code = 302
            headers = {'Location': 'http://downgrade.example/private'}
            def close(self):
                pass

        class FakeSession:
            def __init__(self):
                self.called = 0
            def request(self, *args, **kwargs):
                self.called += 1
                return FakeResponse()
            def close(self):
                pass

        fake = FakeSession()
        with patch('actions.secure_network.secure_requests_session', return_value=fake):
            with self.assertRaisesRegex(ValueError, 'Unencrypted HTTP'):
                secure_request('GET', 'https://example.com/start')
        self.assertEqual(fake.called, 1)

    def test_private_dns_http_requires_resolved_private_addresses(self):
        with patch('actions.secure_network.socket.getaddrinfo', return_value=[(None, None, None, None, ('192.168.1.8', 0))]):
            self.assertTrue(validate_outbound_url('http://homeassistant.lan:8123', allow_private_http=True))
        with patch('actions.secure_network.socket.getaddrinfo', return_value=[(None, None, None, None, ('8.8.8.8', 0))]):
            with self.assertRaises(ValueError):
                validate_outbound_url('http://public-host.invalid', allow_private_http=True)


if __name__ == '__main__':
    unittest.main()
