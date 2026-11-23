import unittest
from dataclasses import replace

from obd_consultas.application.queries import QueryService
from obd_consultas.bootstrap import build_service
from obd_consultas.domain.models import QueryResult, QueryStatus, Source, normalize_plate
from obd_consultas.providers.catalog import SOURCES


class RecordingProvider:
    info = replace(SOURCES[0], implemented=True)

    def __init__(self):
        self.plates = []

    def query(self, plate):
        self.plates.append(plate)
        return QueryResult(Source.SOAT, plate, QueryStatus.SUCCESS, self.info.url,
                           "Resultado sintetico para prueba", {"test_fixture": True})


class QueryTests(unittest.TestCase):
    def test_normalizes_plate_before_calling_provider(self):
        provider = RecordingProvider()
        result = QueryService([provider]).query(Source.SOAT, " abc-123 ")
        self.assertEqual(provider.plates, ["ABC123"])
        self.assertEqual(result.plate, "ABC123")

    def test_invalid_plate_does_not_call_provider(self):
        provider = RecordingProvider()
        with self.assertRaises(ValueError):
            QueryService([provider]).query(Source.SOAT, "ABC/123")
        self.assertEqual(provider.plates, [])

    def test_accepts_seven_characters(self):
        self.assertEqual(normalize_plate("abc-1234"), "ABC1234")

    def test_unvalidated_sources_never_return_success_or_data(self):
        service = build_service()
        for source in Source:
            with self.subTest(source=source):
                result = service.query(source, "ABC123")
                expected = QueryStatus.REQUIRES_INTERACTION
                self.assertEqual(result.status, expected)
                self.assertEqual(result.data, {})
                self.assertIsNotNone(result.queried_at.tzinfo)
                self.assertEqual(result.to_dict()["status"], expected.value)

    def test_duplicate_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            QueryService([RecordingProvider(), RecordingProvider()])
