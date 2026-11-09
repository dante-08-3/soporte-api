# Sistema automatizado de gestión de solicitudes de soporte técnico

API REST en **Flask** + **PostgreSQL (Neon)**, desplegada en **Render**, alimentada por
**Google Forms → Google Sheets → n8n**, con notificaciones por **Gmail** y dashboard en Sheets.

```
Google Form → Sheets (Respuestas) → n8n → POST /api/solicitudes → Neon
                    ↑                  │          (genera folio)
                    └── Folio/Estado ──┤
                                       └→ Gmail (solicitante + alerta Alta/Urgente)
Sheets (Dashboard) ← fórmulas sobre Respuestas
```

## Estructura

| Archivo | Contenido |
|---|---|
| `app.py` | API Flask |
| `schema.sql` | Tabla `solicitudes` (se crea sola al arrancar) |
| `requirements.txt` | Dependencias |
| `render.yaml` | Despliegue en Render (Blueprint) |
| `.env.example` | Variables de entorno |
| `google/Codigo.gs` | Apps Script: crea el Form y el Dashboard |
| `n8n/workflow_solicitudes.json` | Workflow para importar en n8n |

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Estado del servicio |
| GET | `/api/solicitudes?categoria=&prioridad=&estado=&limit=` | Lista |
| GET | `/api/solicitudes/<folio>` | Consulta por folio |
| POST | `/api/solicitudes` | Registra y genera folio (`X-API-Key`) |
| PATCH | `/api/solicitudes/<folio>/estado` | Cambia estado (`X-API-Key`) |
| GET | `/api/estadisticas` | Totales por categoría, prioridad y estado |

Folio: `SOP-AAAA-00000` (prefijo configurable con `PREFIJO_FOLIO`).

## Ejecutar localmente

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # pon tu DATABASE_URL de Neon y una API_KEY
python app.py                 # http://localhost:5000
```

## Despliegue (resumen)

1. **Neon:** crea un proyecto y copia la cadena de conexión (pooled, `sslmode=require`).
2. **Render:** New → Web Service desde este repo.
   Build: `pip install -r requirements.txt` · Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60`
   Variables: `DATABASE_URL`, `API_KEY`, `PREFIJO_FOLIO=SOP`.
3. **Google:** hoja nueva → Extensiones → Apps Script → pega `google/Codigo.gs` → ejecuta `crearFormulario` y luego `crearDashboard`.
4. **n8n:** importa el JSON, asigna credenciales de Google Sheets y Gmail, elige la hoja/pestaña `Respuestas`, pon tu URL de Render y tu API_KEY, y activa el workflow.

La documentación técnica completa (arquitectura, base de datos, API, workflow, dashboard, pruebas) está en el documento de entrega.
