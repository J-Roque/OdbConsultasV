# Plan de cobertura de fuentes

Este documento es el inventario de datos vehiculares que queremos poder consultar
y el estado real de cada fuente. No es una promesa de fecha: una fuente solo se
marca como implementada cuando se inspecciono el portal, se valido con una placa
autorizada y se documento su contrato.

Los pasos para agregar una fuente estan en [ARQUITECTURA.md](ARQUITECTURA.md).
Ninguna fuente se da por soportada solo porque exista una URL publica.

## Estados

| Estado | Significado |
|---|---|
| **Implementado** | Consulta real, validada y contrato documentado |
| **Parcial** | Se obtiene parte del dato; el resto viene en imagen o falta exponerlo |
| **Por validar** | Falta inspeccionar si existe consulta publica por placa |
| **Requiere datos adicionales** | La fuente pide documento, provincia u otro dato |
| **Excluido** | No se incorpora por riesgo de datos sensibles o acceso restringido |

## Fuentes actuales

| Fuente | Dato objetivo | Estado | Detalle |
|---|---|---|---|
| APESEG / SOAT | Vigencia y aseguradora | **Implementado** | `data.soat_vigente`, `data.vigente` y `data.certificados` con aseguradora, numero de poliza y vigencias. Ver [SOAT.md](SOAT.md). |
| MTC | Revision tecnica y vigencias CITV | **Implementado** | Hasta tres registros en `data.registros`, etiquetados `ULTIMO`, `PENULTIMO` y `ANTEPENULTIMO`, con `data.vigente`. Modo desatendido con OCR local. Ver [MTC.md](MTC.md). |
| SUNARP | Propiedad, datos tecnicos y estado de robo | **Implementado** | La imagen TIVE se entrega en `data.tarjeta` y sus campos se leen con OCR local en `data.vehiculo` (valor y confianza por campo). `alerta_robo` es campo JSON. Ver [SUNARP.md](SUNARP.md). |
| SUTRAN | Papeletas e infracciones por placa | **Implementado** | Consulta publica por la API oficial. Funciona con navegador visible como respaldo ante Turnstile y devuelve `data.documentos`, las fuentes consultadas y el criterio normalizado. |

### Cierre de SUNARP

- La tarjeta TIVE se estructura con RapidOCR local. Cada campo lleva su
  confianza; la imagen oficial se conserva en `data.tarjeta`.
- La placa leida y la de las sedes se comparan con la placa consultada. El
  resultado expone `plate_verified` y `vehiculo.placa_coincide`; si las sedes no
  coinciden, el conector devuelve `parse_error`.
- Los campos que la tarjeta no muestra (`vin`, `anio_modelo`) quedan en `null`:
  no se inventan valores para completarlos.
- El estado de robo se conserva literalmente desde `msgAlertaRobo` en
  `data.alerta_robo`.

## Fuentes por incorporar

| Fuente | Dato objetivo | Estado | Proximo paso |
|---|---|---|---|
| ATU | Validar el alcance publico de multas por placa | **Por validar** | Comprobar si las multas por placa son publicas y que campos muestran. Revisar restricciones de privacidad antes de guardar o exponer datos de sanciones. |
| SBS | Comprobar si tiene consulta publica por placa o unicamente por aseguradora | **Por validar** | Confirmar si la busqueda es por placa o solo por aseguradora. Si es por aseguradora, evaluar si aporta algo sobre lo que ya da SOAT. |
| SUNAT | Consulta vehicular / tributaria | **Requiere datos adicionales** | Verificar que se necesita numero de documento u otros datos. Sin ese dato no se incorpora a la consulta por placa. |
| AAP | Confirmar si su consulta esta disponible por placa | **Por validar** | Comprobar si existe busqueda por placa y si los datos difieren de APESEG. Evitar duplicar SOAT sin ganancia. |
| INFOGAS / FISE | Confirmar si la instalacion GNV/GLP se consulta por placa | **Por validar** | Verificar si hay consulta por placa o solo listados de talleres autorizados. Nota: el portal MTC ya muestra un listado de talleres de conversion GNV/GLP, pero no por placa. |
| SAT | Consulta por placa con contexto provincial | **Requiere datos adicionales** | Confirmar la provincia requerida y si admite placa o documento. Definir como se pediria ese contexto desde la APK. |

## Fuente exclusion

| Fuente | Motivo |
|---|---|
| PNP / DIROVE | **Excluido** para una app publica. Puede implicar datos sensibles de personas y vehiculos, ademas de restricciones de acceso. No se integra. |

## Orden sugerido

1. **Cerrar SUNARP**: definir si propiedad y datos tecnicos se estructuran o se
   entregan solo como imagen. Es la unica fuente actual con dato parcial.
2. **Validar SUTRAN y AAP**: son las mas cercanas al patron ya resuelto (consulta
   por placa con formulario publico).
3. **Validar INFOGAS / FISE y ATU**: requieren revisar alcance publico y
   privacidad antes de escribir cualquier conector.
4. **SBS y SAT**: solo si confirman consulta por placa o si aceptamos pedir el
   dato adicional en la APK.
5. **SUNAT**: queda condicionado a obtener el documento del usuario.
6. **PNP / DIROVE**: no se trabaja.

## Reglas para cualquier fuente nueva

- Inspeccionar el formulario y el resultado reales antes de escribir selectores.
- No inventar datos ni convertir errores o bloqueos en `not_found`.
- Respetar terminos del portal y limitar reintentos y frecuencia.
- No registrar placas completas, propietarios, cookies ni cuerpos de respuesta
  en logs.
- Documentar fecha de validacion, campos soportados, limitaciones y estado.
