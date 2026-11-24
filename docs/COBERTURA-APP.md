# Cobertura para la app ObdScanner

Que datos por placa necesita la app `D:\ObdScanner` y cuales ya puede dar este
backend. Revisado el 23/11/2026 sobre `PlateLookupService.cs` de la app.

Hoy la app no usa este backend: consulta **ApisTED** (`https://apisted.com/api/`)
con un token Bearer que el usuario guarda en el telefono. Conectar la app con
ObdConsultas es un MVP posterior; este documento fija que falta para llegar ahi.

## Fuentes que consume la app

| Clave en la app | Ruta ApisTED | Creditos | Fuente en ObdConsultas | Estado |
|---|---|---|---|---|
| `sunarp` | `sunarp/consulta-vehicular` | 60 | `sunarp` | Implementado (TIVE + OCR) |
| `soat` | `apeseg/soat` | 1 | `soat` | Implementado |
| `citv` | `mtc/revision-tecnica` | 30 | `mtc` | Implementado |
| `sutran` | `mtc/sutran/record` | 5 | `sutran` | Parcial: validado sin documentos |
| `capture` | `sat/capturas` | 25 | `sat` | Parcial: validado sin orden de captura |
| `callao` | `sat/callao/papeletas` | 25 | — | **Falta**: papeletas del Callao |
| `atu` | `mtc/atu/infracciones` | 20 | `atu` | Parcial: validado sin infracciones |
| `history` (opcional) | `sunarp/historial-vehicular` | 60 | — | **Falta**: transferencias y gravamenes |

Una inspeccion completa gasta 166 creditos (226 con historial). ObdConsultas
cubre hoy 141 de esos 166: SOAT, MTC y SUNARP implementados (91) mas SUTRAN,
SAT capturas y ATU en estado parcial (50). Falta el Callao (25).

La app usa ademas la API de NHTSA (`vpic.nhtsa.dot.gov`) para decodificar el VIN.
Es gratuita y no requiere conector propio.

### Hueco de la propia app

La app consulta la **orden de captura** del SAT de Lima, pero no las **papeletas**
del SAT de Lima. Tiene papeletas del Callao y de la ATU. Para autos de Lima es
probable que la mayoria de multas esten en SAT Lima, asi que conviene agregarla
cuando exista el conector.

## Diferencias de contrato

La app lee el JSON con nombres fijos. Solo SOAT coincide hoy con nuestro
contrato; el resto necesita un adaptador al formato de ApisTED (mejor en este
backend que reescribir los parsers de la app).

| Fuente | La app espera | ObdConsultas entrega |
|---|---|---|
| SOAT | `encontrado`, `vigente`, `soat_vigente`, `certificados[]` con `estado`, `aseguradora`, `vigencia_desde/hasta` | Lo mismo. Fechas ISO: la app ya las acepta |
| SUNARP | `vehiculo.{marca, modelo, color, ...}` como texto; `propietarios` texto en la raiz; `alerta_robo` | Cada campo como `{valor, confianza}`; `propietarios.valor` es lista dentro de `vehiculo`; `vehiculo` puede ser `OcrUnavailable` |
| MTC (CITV) | `revisiones[]` con `estado`, `resultado`, `vigencia_*`, `observaciones[].detalle`; `vigente` booleano | `registros[]`; `observaciones` texto; `vigente` es el registro vigente o `null` |
| SUTRAN | `infracciones[]` con `fecha`, `infraccion`/`falta`, `calificacion`/`estado`, `deuda`; `monto_total` | `documentos[]` sin forma validada |
| SAT capturas | `tiene_orden_captura`, `ordenes[].detalle` | Lo mismo, mas `ordenes[].campos`, `mensaje` y `actualizado_al` |
| Callao / ATU | `encontrado`, `papeletas[]` o `infracciones[]`, `deuda_total` | ATU: `tiene_infracciones`, `infracciones[]` (filas de la tabla, montos como texto); sin `deuda_total`. Callao: — |
| Historial SUNARP | `transferencias_de_propiedad`, `total_asientos`, `alerta_robo.{reportado, detalle}`, `gravamenes.{tiene_cargas_vigentes, actos[], aviso}` | — |

## Orden sugerido

1. **SAT Lima, orden de captura**: es la alerta mas grave para un comprador.
2. **SUTRAN**: funciona; falta validar un caso con documentos.
3. **ATU** (funciona; falta un caso con infracciones) y **papeletas del Callao**.
4. **Papeletas SAT Lima**: no esta en la app, pero cubre el hueco de arriba.
5. **Historial y gravamenes SUNARP**: lento y complejo; puede seguir en ApisTED.

Cada fuente nueva sigue las reglas de [PLAN.md](PLAN.md): inspeccionar el portal
real antes de escribir el conector y validar con una placa autorizada.

## Notas

- El costo de ApisTED (unos S/ 0.17 por inspeccion) no es el motivo para
  reemplazarlo. El valor de conectores propios es independencia y control de
  los datos personales (SUNARP trae nombres de propietarios).
- Revisar los terminos de cada portal antes de exponer sus datos en un servicio.
