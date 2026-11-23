"""Adaptador para capturas del resultado visible de APESEG; no importa sesiones."""
import re
from urllib.parse import urlparse

from obd_consultas.domain.models import QueryStatus, normalize_plate
from obd_consultas.providers.soat import SoatParseError, parse_soat, soat_result

# Lee exclusivamente nodos del resultado visible. Compartido por el navegador Python.
CAPTURE_SCRIPT = r"""root => {
  const card = root.querySelector('article');
  return {
    format: 'apeseg-dom-v1', source_url: location.href,
    plate: card.querySelector('.soat-card__placa strong')?.textContent.trim(),
    current: {
      state: card.querySelector('.soat-badge')?.textContent.trim(),
      dates: Array.from(card.querySelectorAll('.soat-vigencia__fechas > span')).map(n => n.textContent.trim()),
      fields: Object.fromEntries(Array.from(card.querySelectorAll('.soat-dato')).map(n => [n.querySelector('dt')?.textContent.trim(), n.querySelector('dd')?.textContent.trim()]))
    },
    history_count: root.querySelector('.soat-historial__contador')?.textContent.trim() || '1',
    history: Array.from(root.querySelectorAll('.soat-timeline__item')).map(n => ({
      company: n.querySelector('strong')?.textContent.trim(),
      state: n.querySelector('.soat-badge')?.textContent.trim(),
      dates: n.querySelector('.soat-timeline__fechas')?.textContent.trim(),
      details: Array.from(n.querySelectorAll('.soat-timeline__meta > span')).map(s => s.textContent.trim())
    }))
  };
}"""


def dates(value):
    if not isinstance(value, str):
        raise SoatParseError('Fechas visibles ausentes.')
    found = re.findall(r'\d{2}/\d{2}/\d{4}', value)
    if len(found) != 2:
        raise SoatParseError('Se esperaban dos fechas de vigencia.')
    return found


def parse_dom_capture(capture: object, plate: str) -> dict[str, object]:
    plate = normalize_plate(plate)
    if not isinstance(capture, dict) or capture.get('format') != 'apeseg-dom-v1':
        raise SoatParseError('Formato de captura no reconocido.')
    url = urlparse(str(capture.get('source_url', '')))
    if url.scheme != 'https' or url.hostname != 'www.apeseg.org.pe' or url.path.rstrip('/') != '/consultas-soat':
        raise SoatParseError('La captura no indica el portal SOAT esperado.')
    if capture.get('plate') != plate:
        raise SoatParseError('La captura corresponde a otra placa.')
    current = capture.get('current')
    history = capture.get('history')
    if not isinstance(current, dict) or not isinstance(history, list):
        raise SoatParseError('Resultado visible incompleto.')
    fields = current.get('fields')
    current_dates = current.get('dates')
    if not isinstance(fields, dict) or not isinstance(current_dates, list) or not all(isinstance(x, str) for x in current_dates):
        raise SoatParseError('Faltan los campos del certificado principal.')
    start, end = dates(' '.join(current_dates))
    main = {
        'Placa': plate, 'Estado': current.get('state'),
        'NombreCompania': fields.get('Compañía de seguros'),
        'NumeroPoliza': fields.get('N.° de certificado'),
        'FechaInicio': start, 'FechaFin': end,
        'TipoCertificado': fields.get('Tipo de certificado'),
        'NombreUsoVehiculo': fields.get('Uso del vehículo'),
        'NombreClaseVehiculo': fields.get('Clase de vehículo'),
    }
    try:
        count = int(capture.get('history_count', ''))
    except (ValueError, TypeError) as exc:
        raise SoatParseError('Contador de historial invalido.') from exc
    if not 1 <= count <= 1000:
        raise SoatParseError('Contador de historial fuera de rango.')
    if not history:
        if count != 1:
            raise SoatParseError('Falta desplegar el historial completo.')
        certificates = [main]
    else:
        if len(history) != count:
            raise SoatParseError('El historial capturado esta incompleto.')
        certificates = []
        for row in history:
            if not isinstance(row, dict):
                raise SoatParseError('Fila de historial invalida.')
            start, end = dates(row.get('dates'))
            details = row.get('details')
            if not isinstance(details, list) or not all(isinstance(x, str) for x in details):
                raise SoatParseError('Metadatos de historial invalidos.')
            policy = [x.removeprefix('Cert. ').strip() for x in details if x.startswith('Cert. ')]
            if len(policy) != 1:
                raise SoatParseError('Falta el numero de certificado en el historial.')
            certificates.append({'Placa': plate, 'Estado': row.get('state'),
                                 'NombreCompania': row.get('company'), 'NumeroPoliza': policy[0],
                                 'FechaInicio': start, 'FechaFin': end,
                                 'TipoCertificado': next((x for x in details if x in {'DIGITAL', 'FISICO'}), None)})
        first = certificates[0]
        for key in ('Estado', 'NombreCompania', 'NumeroPoliza', 'FechaInicio', 'FechaFin'):
            if first[key] != main[key]:
                raise SoatParseError('El certificado principal no coincide con el historial.')
        first.update(main)
    data = parse_soat({'placa': plate, 'certificados': certificates}, plate)
    data['capture'] = {'method': 'browser_dom', 'history_complete': True,
                       'captured_at': capture.get('captured_at')}
    return data


def result_from_dom_capture(capture: object, plate: str, *, imported: bool = False):
    try:
        data = parse_dom_capture(capture, plate)
    except SoatParseError as exc:
        return soat_result(plate, QueryStatus.PARSE_ERROR, str(exc))
    capture = data['capture']
    assert isinstance(capture, dict)  # parse_dom_capture siempre la crea
    capture['method'] = 'imported_browser_dom' if imported else 'browser_dom'
    message = 'Captura importada y procesada; no se realizo una consulta nueva.' if imported else 'Resultado visible obtenido del portal APESEG.'
    return soat_result(plate, QueryStatus.SUCCESS, message, data)
