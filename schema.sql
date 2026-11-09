-- =============================================================
--  Sistema de Gestión de Solicitudes de Soporte Técnico
--  Esquema de base de datos (PostgreSQL / Neon)
-- =============================================================

CREATE TABLE IF NOT EXISTS solicitudes (
    id              SERIAL PRIMARY KEY,
    folio           VARCHAR(20)  UNIQUE,
    nombre          VARCHAR(120) NOT NULL,
    correo          VARCHAR(150) NOT NULL,
    departamento    VARCHAR(100),
    categoria       VARCHAR(50)  NOT NULL,
    prioridad       VARCHAR(20)  NOT NULL,
    asunto          VARCHAR(200) NOT NULL,
    descripcion     TEXT         NOT NULL,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'Recibida',
    origen_id       VARCHAR(100) UNIQUE,          -- marca temporal del Form (evita duplicados)
    fecha_registro  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    fecha_actualizacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_categoria CHECK (categoria IN
        ('Hardware','Software','Red e Internet','Cuentas y accesos','Impresoras','Otro')),
    CONSTRAINT chk_prioridad CHECK (prioridad IN ('Baja','Media','Alta','Urgente')),
    CONSTRAINT chk_estado    CHECK (estado    IN ('Recibida','En proceso','Resuelta','Cerrada'))
);

CREATE INDEX IF NOT EXISTS idx_solicitudes_categoria ON solicitudes (categoria);
CREATE INDEX IF NOT EXISTS idx_solicitudes_prioridad ON solicitudes (prioridad);
CREATE INDEX IF NOT EXISTS idx_solicitudes_estado    ON solicitudes (estado);
