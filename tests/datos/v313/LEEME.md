# Actas de la v3.1.3 para las pruebas

Emitidas y exportadas con la app **v3.1.3** el 25/10/2026, en un Pixel 7 emulado (Playwright), para comprobar que las
versiones siguientes rehacen igual el PDF de las actas de esa versión (`tests/e2e_identificacion.py`, sección «v3.1.3»):
técnico y asistente de «TEAMBIMCIVIL S.L.» elegidos de la lista, otro asistente escrito, y responsables de la lista y
escritos.

| Archivo | Contenido |
|---|---|
| `av01.zip` | EXP-V313-AV-01 emitida: Ana Cascajosa (TEAMBIMCIVIL S.L., de la lista) y Juan Pérez Gómez (Constructora Sur, escrito), sin firma; 2 fotos; 3 indicaciones con responsable de la lista («Constructora Sur · Jefe de obra», «TEAMBIMCIVIL S.L. · Director de Obra») y escrito («Ayuntamiento · Policía Local») |
| `av02.zip` | EXP-V313-AV-02 emitida («Nueva visita»): seguimiento de las 3 (cumplida, pendiente con nuevo plazo y anulada); 1 foto |
| `pdf-av01.txt`, `pdf-av02.txt` | Texto del PDF que generó la v3.1.3 (normalizado como `comun.texto_pdf`) |
| `huellas-pdf.json` | SHA-256 del contenido de cada página de esos PDF |

No se deben regenerar con una versión posterior: son la referencia de lo que se distribuyó.
