"""Pruebas de configuracion del motor; no abren navegadores ni usan red."""
import os
import unittest
from unittest.mock import patch

from obd_consultas.infrastructure.scrapling_engine import (
    browser_options,
    parse_html,
    proxy_rotator_from_env,
)


class EngineTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            os.environ,
            {"OBD_PROXY_URL": "", "OBD_PROXY_ROTATION": ""},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_browser_defaults_are_conservative(self):
        options = browser_options()
        self.assertTrue(options["headless"])
        self.assertTrue(options["solve_cloudflare"])
        self.assertTrue(options["block_ads"])
        self.assertEqual(options["locale"], "es-PE")
        self.assertEqual(options["timezone_id"], "America/Lima")
        self.assertGreaterEqual(options["retries"], 1)

    def test_proxy_from_environment(self):
        with patch.dict(os.environ, {"OBD_PROXY_URL": "http://proxy.test:8080"}):
            self.assertEqual(browser_options()["proxy"], "http://proxy.test:8080")
            self.assertEqual(
                browser_options(proxy="http://other.test:9090")["proxy"],
                "http://other.test:9090",
            )

    def test_proxy_rotation_from_environment(self):
        with patch.dict(os.environ, {"OBD_PROXY_ROTATION": "http://a:1, http://b:2"}):
            rotator = proxy_rotator_from_env()
            self.assertIsNotNone(rotator)
            self.assertEqual(type(rotator).__name__, "ProxyRotator")

    def test_profile_is_absolute(self):
        options = browser_options(profile=".perfil")
        self.assertTrue(options["user_data_dir"].endswith(".perfil"))

    def test_http_session_exposes_get_and_post(self):
        from obd_consultas.infrastructure.scrapling_engine import http_session

        with http_session() as session:
            self.assertTrue(callable(session.get))
            self.assertTrue(callable(session.post))

    def test_parse_html_uses_scrapling_selectors(self):
        page = parse_html("<html><body><p class='x'>hola</p></body></html>")
        self.assertEqual(page.css(".x::text").get(), "hola")
        self.assertEqual(page.xpath("//p/text()").get(), "hola")


if __name__ == "__main__":
    unittest.main()
