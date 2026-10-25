# Actas de la v3.1.4 para las pruebas

Emitidas y exportadas con la app **v3.1.4** el 25/10/2026, en un Pixel 7 emulado (Playwright), para comprobar que las
versiones siguientes rehacen igual el PDF de las actas de esa versión (`tests/e2e_identificacion.py`): coordenadas UTM
ETRS89 de la visita y de las fotos, en el huso de la visita, y fotos de la cámara y de la galería.

| Archivo | Contenido |
|---|---|
| `av01.zip` | EXP-V314-AV-01 emitida: GPS en la Cartuja de Sevilla, al oeste del meridiano 6° O (UTM en el huso 29); Ana Cascajosa (TEAMBIMCIVIL S.L., de la lista) y Juan Pérez Gómez (escrito), sin firma; 3 fotos: de la cámara (posición del teléfono), de la galería con su GPS (al este del 6° O, en el huso de la visita) y de la galería sin GPS; 2 indicaciones |
| `av02.zip` | EXP-V314-AV-02 emitida («Nueva visita»): sin cobertura, con coordenadas manuales al este del 6° O (huso 30); seguimiento de las 2 (cumplida y pendiente con nuevo plazo); 1 foto de la cámara (en el huso 30 de la visita) |
| `pdf-av01.txt`, `pdf-av02.txt` | Texto del PDF que generó la v3.1.4 (normalizado como `comun.texto_pdf`) |
| `huellas-pdf.json` | SHA-256 del contenido de cada página de esos PDF |

No se deben regenerar con una versión posterior: son la referencia de lo que se distribuyó.
