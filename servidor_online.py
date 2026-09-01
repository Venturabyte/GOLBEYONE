from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlparse, parse_qs

# ============================================================
# CONFIGURACIÓN
# ============================================================

PUERTO = int(os.environ.get("PORT", 5500))

# Si Render tiene DATABASE_URL, usamos PostgreSQL.
# Si no existe, seguimos usando pedidos.json localmente.
DATABASE_URL = os.environ.get("DATABASE_URL")

# Token para proteger el panel administrativo en producción.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

ARCHIVO_PEDIDOS = "pedidos.json"


# ============================================================
# POSTGRESQL
# ============================================================

def obtener_conexion():
    if not DATABASE_URL:
        return None

    import psycopg
    return psycopg.connect(DATABASE_URL)


def inicializar_base_datos():
    if not DATABASE_URL:
        return

    try:
        with obtener_conexion() as conexion:
            conexion.execute("""
                CREATE TABLE IF NOT EXISTS pedidos (
                    id TEXT PRIMARY KEY,
                    pedido JSONB NOT NULL,
                    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            conexion.commit()

        print("🗄️ PostgreSQL: base de datos preparada.")

    except Exception as error:
        print("❌ Error preparando PostgreSQL:", error)
        raise


# ============================================================
# PEDIDOS - LOCAL / POSTGRESQL
# ============================================================

def cargar_pedidos():
    # --------------------------------------------------------
    # PRODUCCIÓN → PostgreSQL
    # --------------------------------------------------------
    if DATABASE_URL:
        try:
            with obtener_conexion() as conexion:
                filas = conexion.execute("""
                    SELECT pedido
                    FROM pedidos
                    ORDER BY creado_en DESC
                """).fetchall()

            pedidos = [fila[0] for fila in filas]

            for pedido in pedidos:
                normalizar_pedido(pedido)

            return pedidos

        except Exception as error:
            print("❌ Error leyendo PostgreSQL:", error)
            return []

    # --------------------------------------------------------
    # LOCAL → pedidos.json
    # --------------------------------------------------------
    if not os.path.exists(ARCHIVO_PEDIDOS):
        return []

    try:
        with open(
            ARCHIVO_PEDIDOS,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(archivo)

        if isinstance(datos, list):
            return datos

        return []

    except (json.JSONDecodeError, OSError):
        return []


def guardar_pedidos(pedidos):
    # --------------------------------------------------------
    # PRODUCCIÓN → PostgreSQL
    # --------------------------------------------------------
    if DATABASE_URL:
        try:
            import psycopg
            from psycopg.types.json import Jsonb

            with obtener_conexion() as conexion:

                for pedido in pedidos:
                    pedido_id = str(pedido.get("id", "")).strip()

                    if not pedido_id:
                        continue

                    conexion.execute("""
                        INSERT INTO pedidos (id, pedido)
                        VALUES (%s, %s)
                        ON CONFLICT (id)
                        DO UPDATE SET
                            pedido = EXCLUDED.pedido
                    """, (
                        pedido_id,
                        Jsonb(pedido)
                    ))

                conexion.commit()

            return

        except Exception as error:
            print("❌ Error guardando PostgreSQL:", error)
            raise

    # --------------------------------------------------------
    # LOCAL → pedidos.json
    # --------------------------------------------------------
    with open(
        ARCHIVO_PEDIDOS,
        "w",
        encoding="utf-8"
    ) as archivo:

        json.dump(
            pedidos,
            archivo,
            ensure_ascii=False,
            indent=4
        )


# ============================================================
# FUNCIONES DE PEDIDOS
# ============================================================

def obtener_pago(pedido):

    pago_actual = pedido.get("pago")

    if isinstance(pago_actual, dict):
        return {
            "estado": pago_actual.get(
                "estado",
                "Pendiente"
            ),
            "metodo": pago_actual.get(
                "metodo",
                "Pendiente"
            ),
            "referencia": pago_actual.get(
                "referencia",
                ""
            )
        }

    return {
        "estado": pedido.get(
            "estadoPago",
            "Pendiente"
        ),
        "metodo": pedido.get(
            "metodoPago",
            "Pendiente"
        ),
        "referencia": pedido.get(
            "referenciaPago",
            ""
        )
    }


def normalizar_pedido(pedido):

    if not pedido.get("estado"):
        pedido["estado"] = "Nuevo"

    pago = obtener_pago(pedido)

    pedido["pago"] = {
        "estado": pago.get(
            "estado",
            "Pendiente"
        ),
        "metodo": pago.get(
            "metodo",
            "Pendiente"
        ),
        "referencia": pago.get(
            "referencia",
            ""
        )
    }

    pedido["estadoPago"] = pedido["pago"]["estado"]
    pedido["metodoPago"] = pedido["pago"]["metodo"]
    pedido["referenciaPago"] = pedido["pago"]["referencia"]

    return pedido


# ============================================================
# AUTENTICACIÓN ADMIN
# ============================================================

def admin_autorizado(handler):

    # En local no exigimos token.
    if not DATABASE_URL:
        return True

    # En producción sí.
    if not ADMIN_TOKEN:
        print(
            "⚠️ ADMIN_TOKEN no configurado."
        )
        return False

    token_recibido = handler.headers.get(
        "X-Admin-Token",
        ""
    )

    return token_recibido == ADMIN_TOKEN


# ============================================================
# SERVIDOR
# ============================================================

class ServidorGBO(SimpleHTTPRequestHandler):

    # --------------------------------------------------------
    # RESPUESTA JSON
    # --------------------------------------------------------

    def enviar_json(self, datos, codigo=200):

        respuesta = json.dumps(
            datos,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(codigo)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, DELETE, PATCH, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Admin-Token"
        )

        self.send_header(
            "Content-Length",
            str(len(respuesta))
        )

        self.end_headers()

        self.wfile.write(respuesta)

    # --------------------------------------------------------
    # OPTIONS
    # --------------------------------------------------------

    def do_OPTIONS(self):

        self.send_response(204)

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, DELETE, PATCH, OPTIONS"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Admin-Token"
        )

        self.end_headers()

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        ruta = urlparse(self.path).path

        if ruta == "/api/pedidos":

            if not admin_autorizado(self):

                self.enviar_json({
                    "ok": False,
                    "error": "Acceso administrativo no autorizado"
                }, 401)

                return

            pedidos = cargar_pedidos()

            cambios = False

            for pedido in pedidos:

                antes = json.dumps(
                    pedido,
                    ensure_ascii=False,
                    sort_keys=True
                )

                normalizar_pedido(pedido)

                despues = json.dumps(
                    pedido,
                    ensure_ascii=False,
                    sort_keys=True
                )

                if antes != despues:
                    cambios = True

            if cambios and not DATABASE_URL:
                guardar_pedidos(pedidos)

            self.enviar_json(pedidos)

            return

        super().do_GET()

    # --------------------------------------------------------
    # POST → NUEVO PEDIDO
    # --------------------------------------------------------

    def do_POST(self):

        ruta = urlparse(self.path).path

        if ruta != "/api/pedidos":

            self.send_error(404)

            return

        try:

            longitud = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            if longitud <= 0:

                self.enviar_json({
                    "ok": False,
                    "error": "No se recibieron datos"
                }, 400)

                return

            datos = self.rfile.read(longitud)

            nuevo_pedido = json.loads(
                datos.decode("utf-8")
            )

            if not isinstance(
                nuevo_pedido,
                dict
            ):

                self.enviar_json({
                    "ok": False,
                    "error": "El pedido no es válido"
                }, 400)

                return

            # ------------------------------------------------
            # ID
            # ------------------------------------------------

            pedido_id = str(
                nuevo_pedido.get(
                    "id",
                    ""
                )
            ).strip()

            if not pedido_id:

                self.enviar_json({
                    "ok": False,
                    "error": "El pedido no tiene ID"
                }, 400)

                return

            # ------------------------------------------------
            # NORMALIZACIÓN
            # ------------------------------------------------

            if not nuevo_pedido.get("estado"):

                nuevo_pedido["estado"] = "Nuevo"

            pago = obtener_pago(
                nuevo_pedido
            )

            nuevo_pedido["pago"] = {
                "estado": pago.get(
                    "estado",
                    "Pendiente"
                ),
                "metodo": pago.get(
                    "metodo",
                    "Pendiente"
                ),
                "referencia": pago.get(
                    "referencia",
                    ""
                )
            }

            nuevo_pedido["estadoPago"] = (
                nuevo_pedido["pago"]["estado"]
            )

            nuevo_pedido["metodoPago"] = (
                nuevo_pedido["pago"]["metodo"]
            )

            nuevo_pedido["referenciaPago"] = (
                nuevo_pedido["pago"]["referencia"]
            )

            # ------------------------------------------------
            # POSTGRESQL
            # ------------------------------------------------

            if DATABASE_URL:

                import psycopg
                from psycopg.types.json import Jsonb

                with obtener_conexion() as conexion:

                    existe = conexion.execute(
                        """
                        SELECT 1
                        FROM pedidos
                        WHERE id = %s
                        """,
                        (pedido_id,)
                    ).fetchone()

                    if existe:

                        self.enviar_json({
                            "ok": False,
                            "error": "El ID del pedido ya existe"
                        }, 409)

                        return

                    conexion.execute(
                        """
                        INSERT INTO pedidos
                        (id, pedido)
                        VALUES (%s, %s)
                        """,
                        (
                            pedido_id,
                            Jsonb(nuevo_pedido)
                        )
                    )

                    conexion.commit()

            # ------------------------------------------------
            # LOCAL
            # ------------------------------------------------

            else:

                pedidos = cargar_pedidos()

                pedidos.append(
                    nuevo_pedido
                )

                guardar_pedidos(
                    pedidos
                )

            # ------------------------------------------------
            # LOG
            # ------------------------------------------------

            print(
                "========================================"
            )

            print(
                "🛍️ NUEVO PEDIDO RECIBIDO"
            )

            print(
                "ID:",
                pedido_id
            )

            print(
                "CLIENTE:",
                nuevo_pedido.get(
                    "cliente",
                    "Sin nombre"
                )
            )

            print(
                "TOTAL:",
                nuevo_pedido.get(
                    "total",
                    0
                )
            )

            print(
                "========================================"
            )

            self.enviar_json({

                "ok": True,

                "mensaje":
                    "Pedido guardado correctamente",

                "pedido":
                    nuevo_pedido

            })

        except json.JSONDecodeError:

            self.enviar_json({

                "ok": False,

                "error":
                    "Los datos recibidos no son JSON válido"

            }, 400)

        except Exception as error:

            print(
                "❌ Error POST:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    "Error interno del servidor"

            }, 500)

    # --------------------------------------------------------
    # PATCH → ACTUALIZAR PEDIDO
    # --------------------------------------------------------

    def do_PATCH(self):

        ruta = urlparse(self.path).path

        if ruta != "/api/pedidos":

            self.send_error(404)

            return

        if not admin_autorizado(self):

            self.enviar_json({

                "ok": False,

                "error":
                    "Acceso administrativo no autorizado"

            }, 401)

            return

        try:

            longitud = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            if longitud <= 0:

                self.enviar_json({

                    "ok": False,

                    "error":
                        "No se recibieron datos"

                }, 400)

                return

            datos = self.rfile.read(
                longitud
            )

            solicitud = json.loads(
                datos.decode("utf-8")
            )

            if not isinstance(
                solicitud,
                dict
            ):

                self.enviar_json({

                    "ok": False,

                    "error":
                        "Solicitud no válida"

                }, 400)

                return

            pedido_id = solicitud.get(
                "id"
            )

            if (
                pedido_id is None
                or str(pedido_id).strip() == ""
            ):

                self.enviar_json({

                    "ok": False,

                    "error":
                        "No se recibió el ID del pedido"

                }, 400)

                return

            pedido_id = str(
                pedido_id
            )

            # =================================================
            # POSTGRESQL
            # =================================================

            if DATABASE_URL:

                with obtener_conexion() as conexion:

                    fila = conexion.execute(
                        """
                        SELECT pedido
                        FROM pedidos
                        WHERE id = %s
                        """,
                        (pedido_id,)
                    ).fetchone()

                    if not fila:

                        self.enviar_json({

                            "ok": False,

                            "error":
                                "Pedido no encontrado"

                        }, 404)

                        return

                    pedido = fila[0]

                    self.actualizar_pedido(
                        pedido,
                        solicitud
                    )

                    from psycopg.types.json import Jsonb

                    conexion.execute(
                        """
                        UPDATE pedidos
                        SET pedido = %s
                        WHERE id = %s
                        """,
                        (
                            Jsonb(pedido),
                            pedido_id
                        )
                    )

                    conexion.commit()

                    pedido_actualizado = pedido

            # =================================================
            # LOCAL
            # =================================================

            else:

                pedidos = cargar_pedidos()

                encontrado = False
                pedido_actualizado = None

                for pedido in pedidos:

                    if str(
                        pedido.get("id")
                    ) != pedido_id:

                        continue

                    encontrado = True

                    self.actualizar_pedido(
                        pedido,
                        solicitud
                    )

                    pedido_actualizado = (
                        pedido
                    )

                    break

                if not encontrado:

                    self.enviar_json({

                        "ok": False,

                        "error":
                            "Pedido no encontrado"

                    }, 404)

                    return

                guardar_pedidos(
                    pedidos
                )

            self.enviar_json({

                "ok": True,

                "mensaje":
                    "Pedido actualizado correctamente",

                "pedido":
                    pedido_actualizado

            })

        except json.JSONDecodeError:

            self.enviar_json({

                "ok": False,

                "error":
                    "Los datos recibidos no son JSON válido"

            }, 400)

        except Exception as error:

            print(
                "❌ Error PATCH:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    "Error interno del servidor"

            }, 500)

    # --------------------------------------------------------
    # ACTUALIZAR PEDIDO
    # --------------------------------------------------------

    def actualizar_pedido(
        self,
        pedido,
        solicitud
    ):

        if "estado" in solicitud:

            nuevo_estado = solicitud.get(
                "estado"
            )

            estados_validos = [
                "Nuevo",
                "Confirmado",
                "Preparando",
                "Enviado",
                "Entregado"
            ]

            if nuevo_estado not in estados_validos:

                raise ValueError(
                    "Estado de pedido no válido"
                )

            pedido["estado"] = (
                nuevo_estado
            )

            print(
                f"Estado actualizado: "
                f"{pedido.get('id')} → "
                f"{nuevo_estado}"
            )

        if "pago" in solicitud:

            pago_enviado = solicitud.get(
                "pago"
            )

            if not isinstance(
                pago_enviado,
                dict
            ):

                raise ValueError(
                    "La información del pago no es válida"
                )

            pago_actual = obtener_pago(
                pedido
            )

            if "estado" in pago_enviado:

                pago_actual["estado"] = (
                    pago_enviado["estado"]
                )

            if "metodo" in pago_enviado:

                pago_actual["metodo"] = (
                    pago_enviado["metodo"]
                )

            if "referencia" in pago_enviado:

                pago_actual["referencia"] = (
                    pago_enviado["referencia"]
                )

            pedido["pago"] = {

                "estado":
                    pago_actual.get(
                        "estado",
                        "Pendiente"
                    ),

                "metodo":
                    pago_actual.get(
                        "metodo",
                        "Pendiente"
                    ),

                "referencia":
                    pago_actual.get(
                        "referencia",
                        ""
                    )
            }

            # Compatibilidad con el sistema anterior.

            pedido["estadoPago"] = (
                pedido["pago"]["estado"]
            )

            pedido["metodoPago"] = (
                pedido["pago"]["metodo"]
            )

            pedido["referenciaPago"] = (
                pedido["pago"]["referencia"]
            )

            print(
                f"Pago actualizado: "
                f"{pedido.get('id')} → "
                f"{pedido['pago']}"
            )

    # --------------------------------------------------------
    # DELETE → ELIMINAR PEDIDO
    # --------------------------------------------------------

    def do_DELETE(self):

        ruta = urlparse(
            self.path
        ).path

        if ruta != "/api/pedidos":

            self.send_error(404)

            return

        if not admin_autorizado(self):

            self.enviar_json({

                "ok": False,

                "error":
                    "Acceso administrativo no autorizado"

            }, 401)

            return

        try:

            consulta = parse_qs(
                urlparse(
                    self.path
                ).query
            )

            pedido_id = None

            if "id" in consulta:

                pedido_id = (
                    consulta["id"][0]
                )

            # =================================================
            # POSTGRESQL
            # =================================================

            if DATABASE_URL:

                if not pedido_id:

                    self.enviar_json({

                        "ok": False,

                        "error":
                            "No se recibió el ID del pedido"

                    }, 400)

                    return

                with obtener_conexion() as conexion:

                    resultado = conexion.execute(
                        """
                        DELETE FROM pedidos
                        WHERE id = %s
                        """,
                        (str(pedido_id),)
                    )

                    if resultado.rowcount == 0:

                        self.enviar_json({

                            "ok": False,

                            "error":
                                "Pedido no encontrado"

                        }, 404)

                        return

                    conexion.commit()

            # =================================================
            # LOCAL
            # =================================================

            else:

                if not pedido_id:

                    longitud = int(
                        self.headers.get(
                            "Content-Length",
                            0
                        )
                    )

                    if longitud > 0:

                        datos = self.rfile.read(
                            longitud
                        )

                        solicitud = json.loads(
                            datos.decode("utf-8")
                        )

                        pedido_id = (
                            solicitud.get("id")
                        )

                if (
                    pedido_id is None
                    or str(pedido_id).strip() == ""
                ):

                    self.enviar_json({

                        "ok": False,

                        "error":
                            "No se recibió el ID del pedido"

                    }, 400)

                    return

                pedidos = cargar_pedidos()

                pedidos_nuevos = []

                encontrado = False

                for pedido in pedidos:

                    id_actual = pedido.get(
                        "id"
                    )

                    if (
                        str(id_actual)
                        == str(pedido_id)
                    ):

                        encontrado = True

                    else:

                        pedidos_nuevos.append(
                            pedido
                        )

                if not encontrado:

                    self.enviar_json({

                        "ok": False,

                        "error":
                            "Pedido no encontrado"

                    }, 404)

                    return

                guardar_pedidos(
                    pedidos_nuevos
                )

            print(
                f"🗑️ Pedido eliminado: "
                f"{pedido_id}"
            )

            self.enviar_json({

                "ok": True,

                "mensaje":
                    "Pedido eliminado correctamente",

                "id":
                    pedido_id

            })

        except json.JSONDecodeError:

            self.enviar_json({

                "ok": False,

                "error":
                    "Los datos recibidos no son JSON válido"

            }, 400)

        except Exception as error:

            print(
                "❌ Error DELETE:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    "Error interno del servidor"

            }, 500)


# ============================================================
# ARRANQUE
# ============================================================

if __name__ == "__main__":

    inicializar_base_datos()

    servidor = ThreadingHTTPServer(
        ("0.0.0.0", PUERTO),
        ServidorGBO
    )

    print("----------------------------------------")
    print("      GOLBEYONE - SERVIDOR")
    print("----------------------------------------")
    print(
        f"Servidor iniciado en puerto {PUERTO}"
    )

    if DATABASE_URL:

        print(
            "🗄️ Base de datos: PostgreSQL"
        )

        print(
            "🔐 Panel administrativo: PROTEGIDO"
        )

    else:

        print(
            "💾 Base de datos: pedidos.json LOCAL"
        )

        print(
            "🔧 Modo desarrollo local"
        )

    print("----------------------------------------")

    try:

        servidor.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nServidor detenido."
        )

    finally:

        servidor.server_close()