"""Catalogo de portales; las URL se mantienen fuera de la CLI y la API."""
from obd_consultas.domain.models import Source, SourceInfo

SOURCES = (
    SourceInfo(Source.SOAT, "APESEG / SOAT", "https://www.apeseg.org.pe/consultas-soat/", implemented=True),
    SourceInfo(Source.SUNARP, "SUNARP / Consulta vehicular", "https://consultavehicular.sunarp.gob.pe/", implemented=True),
    SourceInfo(Source.MTC, "MTC / Revision tecnica", "https://portal.mtc.gob.pe/reportedgtt/form/frmconsultaplacaitv.aspx", implemented=True),
    SourceInfo(Source.SUTRAN, "SUTRAN / Papeletas", "https://digital.sutran.gob.pe/", implemented=False),
)
