# Actas de la v3.1.2 para las pruebas

Exportadas con la app **v3.1.2** (`b9e940f`) el 24/10/2026, en un Pixel 7 emulado (Playwright), para comprobar que las
versiones siguientes abren, migran y rehacen igual las actas de esa versión (`tests/e2e_identificacion.py`, sección
«v3.1.3», y desde la v3.2 también `tests/e2e_seguimiento.py`, sección «v3.2»).

| Archivo | Contenido |
|---|---|
| `av01.zip` | EXP-V312-AV-01 emitida (01/10/2026 09:00): indicaciones A1 y A2 |
| `av02.zip` | EXP-V312-AV-02 emitida (08/10/2026 10:00): A1 cumplida, A2 pendiente con nuevo plazo, nueva B1 |
| `av03-borrador.zip` | EXP-V312-AV-03 en borrador en Acuerdos (15/10/2026 11:00): seguimiento de A2 y B1 (esta, cumplida), con el origen de la v3.1.2 (una sola acta) |
| `pdf-av01.txt`, `pdf-av02.txt` | Texto del PDF que generó la v3.1.2 (normalizado como `comun.texto_pdf`) |
| `huellas-pdf.json` | SHA-256 del contenido de cada página de esos PDF |

No se deben regenerar con una versión posterior: son la referencia de lo que se distribuyó.
