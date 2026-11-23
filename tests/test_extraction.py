"""Pruebas sinteticas del extractor; no consultan portales reales."""
import unittest

from obd_consultas.infrastructure.extraction import (
    ExtractionError,
    Field,
    extract_rows,
    extract_table,
    selector_html,
    to_markdown,
    to_text,
)

PAGE = """
<html>
  <body>
    <table id="vehiculos">
      <tr><th>Placa</th><th>Estado</th><th>Fecha</th></tr>
      <tr><td>ABC123</td><td>VIGENTE</td><td>2026-12-31</td></tr>
      <tr><td>XYZ987</td><td>VENCIDO</td><td>2025-12-31</td></tr>
    </table>
    <div class="item" data-id="1">
      <a href="/ficha/1">Primero</a><span class="precio">S/ 10.50</span>
    </div>
    <div class="item" data-id="2">
      <a href="/ficha/2">Segundo</a><span class="precio">S/ 20.00</span>
    </div>
    <p class="dup">uno</p><p class="dup">dos</p>
  </body>
</html>
"""

FIELDS = (
    Field("id", "", mode="attr", attr="data-id"),
    Field("nombre", "a::text"),
    Field("url", "a", mode="url"),
    Field("precio", ".precio::text", pattern=r"S/\s*([\d.]+)"),
)


class ExtractionTests(unittest.TestCase):
    def test_extracts_rows_with_attributes_urls_and_patterns(self):
        rows = extract_rows(PAGE, "div.item", FIELDS, url="https://example.test/")
        self.assertEqual(rows, [
            {"id": "1", "nombre": "Primero", "url": "https://example.test/ficha/1", "precio": "10.50"},
            {"id": "2", "nombre": "Segundo", "url": "https://example.test/ficha/2", "precio": "20.00"},
        ])

    def test_extracts_table_as_records(self):
        rows = extract_table(PAGE, "table#vehiculos")
        self.assertEqual([row["placa"] for row in rows], ["ABC123", "XYZ987"])
        self.assertEqual(rows[0]["estado"], "VIGENTE")

    def test_supports_xpath_rows_and_fields(self):
        rows = extract_rows(
            PAGE,
            "//div[@class='item']",
            (Field("nombre", ".//a", engine="xpath"),),
            engine="xpath",
        )
        self.assertEqual([row["nombre"] for row in rows], ["Primero", "Segundo"])

    def test_missing_required_field_fails(self):
        with self.assertRaises(ExtractionError):
            extract_rows(PAGE, "div.item", (Field("ausente", ".no-existe"),))

    def test_optional_field_is_none(self):
        rows = extract_rows(
            PAGE,
            "div.item",
            (Field("ausente", ".no-existe", required=False),),
        )
        self.assertIsNone(rows[0]["ausente"])

    def test_multiple_values(self):
        rows = extract_rows(
            PAGE,
            "div.item",
            (Field("enlaces", "a", mode="url", multiple=True),),
            url="https://example.test/",
        )
        self.assertEqual(rows[0]["enlaces"], ["https://example.test/ficha/1"])

    def test_no_rows_can_be_explicitly_allowed(self):
        self.assertEqual(extract_rows(PAGE, "tr.no-existe", FIELDS, require_rows=False), [])
        with self.assertRaises(ExtractionError):
            extract_rows(PAGE, "tr.no-existe", FIELDS)

    def test_markdown_text_and_html_outputs(self):
        markdown = to_markdown(PAGE, "div.item")
        self.assertIn("Primero", markdown)
        self.assertIn("/ficha/1", markdown)
        self.assertNotIn("<div", markdown)
        self.assertIn("uno", to_text(PAGE, "p.dup"))
        self.assertIn('<a href="/ficha/2">', selector_html(PAGE, "div.item:nth-of-type(2)"))

    def test_invalid_selector_becomes_extraction_error(self):
        with self.assertRaises(ExtractionError):
            extract_rows(PAGE, "div[", FIELDS)


if __name__ == "__main__":
    unittest.main()
