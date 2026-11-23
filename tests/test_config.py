from pathlib import Path
import tempfile
import unittest

from obd_consultas.config import load_env_file, parse_env


class EnvFileTests(unittest.TestCase):
    def test_parse(self):
        text = "# comentario\nA=1\nexport B='dos tres'\nC=\"x#y\"\nD=valor # nota\n\n"
        self.assertEqual(parse_env(text), {"A": "1", "B": "dos tres", "C": "x#y", "D": "valor"})

    def test_invalid_line(self):
        with self.assertRaises(ValueError):
            parse_env("sin-igual")

    def test_existing_env_wins_and_values_are_not_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("OBD_API_TOKEN=del-archivo\nOTRA=1\n", encoding="utf-8")  # secret-scan: allow
            env = {"OBD_API_TOKEN": "del-entorno"}
            self.assertEqual(load_env_file(path, env), ["OTRA"])
            self.assertEqual(env["OBD_API_TOKEN"], "del-entorno")
            self.assertEqual(env["OTRA"], "1")

    def test_missing_file(self):
        self.assertEqual(load_env_file(Path("no-existe.env"), {}), [])


if __name__ == "__main__":
    unittest.main()
