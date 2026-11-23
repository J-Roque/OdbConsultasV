import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
_spec = importlib.util.spec_from_file_location("check_secrets", _PATH)
check_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_secrets)


class CheckSecretsTests(unittest.TestCase):
    def test_forbidden_paths(self):
        for path in (".env", ".env.local", "certs/server.key", ".cache/mtc-cookies.pkl", "artifacts/x.json"):
            with self.subTest(path=path):
                self.assertTrue(check_secrets._forbidden(path))
        for path in (".env.example", "src/obd_consultas/api/app.py", "docs/API.md"):
            with self.subTest(path=path):
                self.assertFalse(check_secrets._forbidden(path))

    def test_detects_secrets(self):
        samples = (
            "OBD_API_TOKEN=" + "a1b2c3d4" * 5,
            "proxy = 'http://juan:" + "s3cr3t0@10.0.0.1:8080'",
            "key = 'ghp_" + "A" * 36 + "'",
            "-----BEGIN RSA " + "PRIVATE KEY-----",
        )
        for text in samples:
            with self.subTest(text=text[:20]):
                self.assertTrue(check_secrets.scan_text("x.py", text))

    def test_ignores_placeholders_and_allowed_lines(self):
        samples = (
            "OBD_API_TOKEN=",
            "OBD_PROXY_URL=http://usuario:clave@host:puerto",
            "TOKEN = 'real-looking-value-123456'  # secret-scan: allow",
            "headers={'X-OBD-Token': TOKEN}",
        )
        for text in samples:
            with self.subTest(text=text[:20]):
                self.assertEqual(check_secrets.scan_text("x.py", text), [])


if __name__ == "__main__":
    unittest.main()
