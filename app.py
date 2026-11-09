"""
Sistema automatizado de gestión de solicitudes de soporte técnico
API REST en Flask + PostgreSQL (Neon), desplegada en Render.

Endpoints
---------
GET    /                                 Estado del servicio
GET    /api/solicitudes                  Lista (filtros: categoria, prioridad, estado, limit)
GET    /api/solicitudes/<folio>          Consulta una solicitud por folio
POST   /api/solicitudes                  Registra una solicitud y genera su folio
PATCH  /api/solicitudes/<folio>/estado   Cambia el estado de una solicitud
GET    /api/estadisticas                 Totales por categoría, prioridad y estado
"""

import os
import re
from datetime import datetime
from functools import wraps
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
API_KEY = os.getenv("API_KEY")  # si está vacío, los endpoints de escritura no piden llave
PREFIJO_FOLIO = os.getenv("PREFIJO_FOLIO", "SOP")

CATEGORIAS = ["Hardware", "Software", "Red e Internet", "Cuentas y accesos", "Impresoras", "Otro"]
PRIORIDADES = ["Baja", "Media", "Alta", "Urgente"]
ESTADOS = ["Recibida", "En proceso", "Resuelta", "Cerrada"]
CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = Flask(__name__)
app.json.ensure_ascii = False
app.json.sort_keys = False
CORS(app)


# ----------------------------------------------------------------- utilidades
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("Falta la variable de entorno DATABASE_URL")
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """Crea la tabla si no existe (se ejecuta al arrancar)."""
    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)


def normalizar(valor, opciones):
    """Devuelve la opción canónica sin importar mayúsculas/acentos del Form."""
    if valor is None:
        return None
    limpio = str(valor).strip().lower()
    for op in opciones:
        if op.lower() == limpio:
            return op
    return None


def serializar(fila):
    if fila is None:
        return None
    fila = dict(fila)
    for k in ("fecha_registro", "fecha_actualizacion"):
        if isinstance(fila.get(k), datetime):
            fila[k] = fila[k].isoformat()
    return fila


def requiere_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if API_KEY and request.headers.get("X-API-Key") != API_KEY:
            return jsonify(error="API key inválida o ausente (encabezado X-API-Key)"), 401
        return f(*args, **kwargs)
    return wrapper


def error(msg, codigo=400, **extra):
    return jsonify(error=msg, **extra), codigo


# ------------------------------------------------------------------ endpoints
@app.get("/")
def salud():
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM solicitudes")
            total = cur.fetchone()["total"]
        db = "conectada"
    except Exception as e:  # noqa: BLE001
        total, db = None, f"error: {e.__class__.__name__}"
    return jsonify(
        servicio="API de Solicitudes de Soporte Técnico",
        estado="activo",
        base_de_datos=db,
        total_solicitudes=total,
        endpoints=[
            "GET /api/solicitudes",
            "GET /api/solicitudes/<folio>",
            "POST /api/solicitudes",
            "PATCH /api/solicitudes/<folio>/estado",
            "GET /api/estadisticas",
        ],
    )


@app.get("/api/solicitudes")
def listar():
    filtros, valores = [], []
    for campo, opciones in (("categoria", CATEGORIAS), ("prioridad", PRIORIDADES), ("estado", ESTADOS)):
        v = request.args.get(campo)
        if v:
            canon = normalizar(v, opciones)
            if not canon:
                return error(f"Valor inválido para {campo}", opciones_validas=opciones)
            filtros.append(f"{campo} = %s")
            valores.append(canon)

    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    except ValueError:
        return error("limit debe ser numérico")

    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM solicitudes {where} ORDER BY fecha_registro DESC LIMIT %s",
            (*valores, limit),
        )
        filas = [serializar(f) for f in cur.fetchall()]
    return jsonify(total=len(filas), solicitudes=filas)


@app.get("/api/solicitudes/<folio>")
def consultar(folio):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM solicitudes WHERE folio = %s", (folio.upper(),))
        fila = cur.fetchone()
    if not fila:
        return error(f"No existe la solicitud {folio}", 404)
    return jsonify(serializar(fila))


@app.post("/api/solicitudes")
@requiere_api_key
def registrar():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return error("El cuerpo debe ser JSON")

    # ---- validación
    faltantes = [c for c in ("nombre", "correo", "categoria", "prioridad", "asunto", "descripcion")
                 if not str(datos.get(c) or "").strip()]
    if faltantes:
        return error("Faltan campos obligatorios", campos=faltantes)

    correo = str(datos["correo"]).strip().lower()
    if not CORREO_RE.match(correo):
        return error("Correo electrónico inválido")

    categoria = normalizar(datos["categoria"], CATEGORIAS)
    prioridad = normalizar(datos["prioridad"], PRIORIDADES)
    if not categoria:
        return error("Categoría inválida", opciones_validas=CATEGORIAS)
    if not prioridad:
        return error("Prioridad inválida", opciones_validas=PRIORIDADES)

    origen_id = str(datos.get("origen_id") or "").strip() or None

    with get_conn() as conn, conn.cursor() as cur:
        # ---- idempotencia: si n8n reenvía la misma respuesta del Form, no se duplica
        if origen_id:
            cur.execute("SELECT * FROM solicitudes WHERE origen_id = %s", (origen_id,))
            existente = cur.fetchone()
            if existente:
                return jsonify(mensaje="La solicitud ya estaba registrada",
                               duplicada=True, **serializar(existente)), 200

        cur.execute(
            """INSERT INTO solicitudes
                   (nombre, correo, departamento, categoria, prioridad, asunto, descripcion, origen_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, fecha_registro""",
            (
                str(datos["nombre"]).strip(),
                correo,
                (str(datos.get("departamento") or "").strip() or None),
                categoria,
                prioridad,
                str(datos["asunto"]).strip()[:200],
                str(datos["descripcion"]).strip(),
                origen_id,
            ),
        )
        nuevo = cur.fetchone()

        # ---- generación del folio: PREFIJO-AAAA-000ID  (ej. SOP-2026-00015)
        folio = f"{PREFIJO_FOLIO}-{nuevo['fecha_registro'].year}-{nuevo['id']:05d}"
        cur.execute("UPDATE solicitudes SET folio = %s WHERE id = %s RETURNING *", (folio, nuevo["id"]))
        fila = cur.fetchone()

    return jsonify(mensaje="Solicitud registrada correctamente", duplicada=False,
                   **serializar(fila)), 201


@app.patch("/api/solicitudes/<folio>/estado")
@requiere_api_key
def cambiar_estado(folio):
    datos = request.get_json(silent=True) or {}
    estado = normalizar(datos.get("estado"), ESTADOS)
    if not estado:
        return error("Estado inválido", opciones_validas=ESTADOS)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE solicitudes SET estado = %s, fecha_actualizacion = NOW()
               WHERE folio = %s RETURNING *""",
            (estado, folio.upper()),
        )
        fila = cur.fetchone()
    if not fila:
        return error(f"No existe la solicitud {folio}", 404)
    return jsonify(mensaje="Estado actualizado", **serializar(fila))


@app.get("/api/estadisticas")
def estadisticas():
    def agrupar(cur, campo, orden):
        cur.execute(f"SELECT {campo} AS clave, COUNT(*) AS total FROM solicitudes GROUP BY {campo}")
        conteo = {f["clave"]: f["total"] for f in cur.fetchall()}
        return {k: conteo.get(k, 0) for k in orden}

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM solicitudes")
        total = cur.fetchone()["total"]
        return jsonify(
            total_solicitudes=total,
            por_categoria=agrupar(cur, "categoria", CATEGORIAS),
            por_prioridad=agrupar(cur, "prioridad", PRIORIDADES),
            por_estado=agrupar(cur, "estado", ESTADOS),
        )


@app.errorhandler(404)
def no_encontrado(_):
    return error("Ruta no encontrada", 404)


@app.errorhandler(Exception)
def error_general(e):
    if isinstance(e, HTTPException):  # 405, 415, etc. conservan su código
        return error(e.description, e.code)
    app.logger.exception(e)
    return error("Error interno del servidor", 500, detalle=e.__class__.__name__)


# Crear tabla al arrancar (Render ejecuta gunicorn, que importa este módulo)
try:
    if DATABASE_URL:
        init_db()
except Exception as e:  # noqa: BLE001
    print(f"[init_db] No se pudo inicializar la base de datos: {e}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
