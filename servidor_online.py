from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlparse, parse_qs

# ============================================================
# CONFIGURACIÓN
# ============================================================

PUERTO = int(os.environ.get("PORT", 5500))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()

ARCHIVO_PEDIDOS = "pedidos.json"

USAR_POSTGRES = bool(DATABASE_URL)


# ============================================================
# POSTGRESQL
# ============================================================

def conexion_postgres():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada.")

    import psycopg

    return psycopg.connect(DATABASE_URL)


def inicializar_base_datos():
    if not USAR_POSTGRES:
        print("🗂️ Modo local: usando pedidos.json")
        return

    print("🗄️ Conectando con PostgreSQL...")

    with conexion_postgres() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id TEXT PRIMARY KEY,
                pedido JSONB NOT NULL,
                creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()

    print("✅ PostgreSQL conectado correctamente.")


# ============================================================
# PEDIDOS - CARGAR
# ============================================================

def cargar_pedidos():
    # --------------------------------------------------------
    # PRODUCCIÓN: PostgreSQL
    # --------------------------------------------------------

    if USAR_POSTGRES:
        with conexion_postgres() as conn:
            filas = conn.execute("""
                SELECT pedido
                FROM pedidos
                ORDER BY creado_en DESC
            """).fetchall()

        pedidos = []

        for fila in filas:
            pedido = fila[0]

            if isinstance(pedido, dict):
                pedidos.append(pedido)

        return pedidos

    # --------------------------------------------------------
    # LOCAL: pedidos.json
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


# ============================================================
# PEDIDOS - GUARDAR
# ============================================================

def guardar_pedidos(pedidos):
    # --------------------------------------------------------
    # PRODUCCIÓN: PostgreSQL
    # --------------------------------------------------------

    if USAR_POSTGRES:
        from psycopg.types.json import Jsonb

        with conexion_postgres() as conn:

            for pedido in pedidos:

                pedido_id = str(
                    pedido.get("id", "")
                ).strip()

                if not pedido_id:
                    continue

                conn.execute("""
                    INSERT INTO pedidos (
                        id,
                        pedido
                    )
                    VALUES (
                        %s,
                        %s
                    )
                    ON CONFLICT (id)
                    DO UPDATE SET
                        pedido = EXCLUDED.pedido
                """, (
                    pedido_id,
                    Jsonb(pedido)
                ))

            conn.commit()

        return

    # --------------------------------------------------------
    # LOCAL: pedidos.json
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
# ACTUALIZAR / ELIMINAR DIRECTAMENTE EN POSTGRES
# ============================================================

def actualizar_pedido_postgres(pedido):
    from psycopg.types.json import Jsonb

    pedido_id = str(
        pedido.get("id", "")
    ).strip()

    if not pedido_id:
        raise ValueError("El pedido no tiene ID.")

    with conexion_postgres() as conn:

        conn.execute("""
            UPDATE pedidos
            SET pedido = %s
            WHERE id = %s
        """, (
            Jsonb(pedido),
            pedido_id
        ))

        conn.commit()


def eliminar_pedido_postgres(pedido_id):

    with conexion_postgres() as conn:

        resultado = conn.execute("""
            DELETE FROM pedidos
            WHERE id = %s
            RETURNING id
        """, (
            str(pedido_id),
        ))

        eliminado = resultado.fetchone()

        conn.commit()

    return eliminado is not None


# ============================================================
# PAGOS
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


# ============================================================
# NORMALIZAR PEDIDO
# ============================================================

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

    return pedido


# ============================================================
# NOTIFICACIÓN LOCAL
# ============================================================

def notificar_nuevo_pedido(pedido):

    try:

        from winotify import Notification, audio

        pedido_id = str(
            pedido.get(
                "id",
                "SIN-ID"
            )
        )

        cliente = str(
            pedido.get(
                "cliente",
                pedido.get(
                    "nombre",
                    "Cliente"
                )
            )
        )

        total = pedido.get(
            "total",
            0
        )

        toast = Notification(
            app_id="GOLBEYONE",

            title="🛍️ Nuevo pedido",

            msg=(
                f"Pedido: {pedido_id}\n"
                f"Cliente: {cliente}\n"
                f"Total: RD$ {total}"
            ),

            duration="short"
        )

        toast.set_audio(
            audio.Default,
            loop=False
        )

        toast.show()

        print(
            "🔔 Notificación enviada: "
            + pedido_id
        )

    except ImportError:

        print(
            "ℹ️ winotify no está instalado. "
            "Notificación de escritorio omitida."
        )

    except Exception as error:

        print(
            "⚠️ Error en notificación:",
            error
        )


# ============================================================
# SERVIDOR
# ============================================================

class ServidorGBO(
    SimpleHTTPRequestHandler
):

    # --------------------------------------------------------
    # RESPUESTA JSON
    # --------------------------------------------------------

    def enviar_json(
        self,
        datos,
        codigo=200
    ):

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
    # AUTORIZACIÓN ADMIN
    # --------------------------------------------------------

    def admin_autorizado(self):

        if not USAR_POSTGRES:
            return True

        if not ADMIN_TOKEN:
            return False

        token_recibido = (
            self.headers.get(
                "X-Admin-Token",
                ""
            ).strip()
        )

        return token_recibido == ADMIN_TOKEN

    # --------------------------------------------------------
    # VERIFICAR ADMIN
    # --------------------------------------------------------

    def exigir_admin(self):

        if self.admin_autorizado():
            return True

        self.enviar_json(
            {
                "ok": False,
                "error": "Acceso administrativo requerido"
            },
            401
        )

        return False

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

        ruta = urlparse(
            self.path
        ).path

        if ruta == "/api/pedidos":

            # En producción, solo admin
            if USAR_POSTGRES:

                if not self.exigir_admin():
                    return

            pedidos = cargar_pedidos()

            cambios = False

            for pedido in pedidos:

                antes = json.dumps(
                    pedido,
                    ensure_ascii=False,
                    sort_keys=True
                )

                normalizar_pedido(
                    pedido
                )

                despues = json.dumps(
                    pedido,
                    ensure_ascii=False,
                    sort_keys=True
                )

                if antes != despues:
                    cambios = True

            if cambios:

                if USAR_POSTGRES:

                    for pedido in pedidos:
                        actualizar_pedido_postgres(
                            pedido
                        )

                else:

                    guardar_pedidos(
                        pedidos
                    )

            self.enviar_json(
                pedidos
            )

            return

        super().do_GET()

    # --------------------------------------------------------
    # POST - NUEVO PEDIDO
    # --------------------------------------------------------

    def do_POST(self):

        ruta = urlparse(
            self.path
        ).path

        if ruta != "/api/pedidos":

            self.send_error(
                404
            )

            return

        try:

            longitud = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            if longitud <= 0:

                self.enviar_json(
                    {
                        "ok": False,
                        "error": "No se recibieron datos"
                    },
                    400
                )

                return

            datos = self.rfile.read(
                longitud
            )

            nuevo_pedido = json.loads(
                datos.decode("utf-8")
            )

            if not isinstance(
                nuevo_pedido,
                dict
            ):

                self.enviar_json(
                    {
                        "ok": False,
                        "error": "El pedido no es válido"
                    },
                    400
                )

                return

            # ID obligatorio
            pedido_id = str(
                nuevo_pedido.get(
                    "id",
                    ""
                )
            ).strip()

            if not pedido_id:

                self.enviar_json(
                    {
                        "ok": False,
                        "error": "El pedido no tiene ID"
                    },
                    400
                )

                return

            # Estado
            if not nuevo_pedido.get(
                "estado"
            ):

                nuevo_pedido[
                    "estado"
                ] = "Nuevo"

            # Pago
            pago = obtener_pago(
                nuevo_pedido
            )

            nuevo_pedido[
                "pago"
            ] = {

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

            # Compatibilidad con sistema anterior
            nuevo_pedido[
                "estadoPago"
            ] = nuevo_pedido[
                "pago"
            ][
                "estado"
            ]

            nuevo_pedido[
                "metodoPago"
            ] = nuevo_pedido[
                "pago"
            ][
                "metodo"
            ]

            nuevo_pedido[
                "referenciaPago"
            ] = nuevo_pedido[
                "pago"
            ][
                "referencia"
            ]

            # ------------------------------------------------
            # POSTGRES
            # ------------------------------------------------

            if USAR_POSTGRES:

                from psycopg.types.json import Jsonb

                with conexion_postgres() as conn:

                    conn.execute("""
                        INSERT INTO pedidos (
                            id,
                            pedido
                        )
                        VALUES (
                            %s,
                            %s
                        )
                    """, (
                        pedido_id,
                        Jsonb(nuevo_pedido)
                    ))

                    conn.commit()

            # ------------------------------------------------
            # LOCAL
            # ------------------------------------------------

            else:

                pedidos = cargar_pedidos()

                # Evitar IDs duplicados
                pedidos = [
                    pedido
                    for pedido in pedidos
                    if str(
                        pedido.get("id", "")
                    ) != pedido_id
                ]

                pedidos.append(
                    nuevo_pedido
                )

                guardar_pedidos(
                    pedidos
                )

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
                "========================================"
            )

            notificar_nuevo_pedido(
                nuevo_pedido
            )

            self.enviar_json(
                {
                    "ok": True,
                    "mensaje":
                        "Pedido guardado correctamente",
                    "pedido":
                        nuevo_pedido
                }
            )

        except json.JSONDecodeError:

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        "Los datos recibidos no son JSON válido"
                },
                400
            )

        except Exception as error:

            print(
                "Error POST:",
                error
            )

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        str(error)
                },
                500
            )

    # --------------------------------------------------------
    # PATCH - ACTUALIZAR PEDIDO
    # --------------------------------------------------------

    def do_PATCH(self):

        ruta = urlparse(
            self.path
        ).path

        if ruta != "/api/pedidos":

            self.send_error(
                404
            )

            return

        # Solo administrador
        if not self.exigir_admin():
            return

        try:

            longitud = int(
                self.headers.get(
                    "Content-Length",
                    0
                )
            )

            if longitud <= 0:

                self.enviar_json(
                    {
                        "ok": False,
                        "error":
                            "No se recibieron datos"
                    },
                    400
                )

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

                self.enviar_json(
                    {
                        "ok": False,
                        "error":
                            "Solicitud no válida"
                    },
                    400
                )

                return

            pedido_id = solicitud.get(
                "id"
            )

            if (
                pedido_id is None
                or str(pedido_id).strip() == ""
            ):

                self.enviar_json(
                    {
                        "ok": False,
                        "error":
                            "No se recibió el ID del pedido"
                    },
                    400
                )

                return

            pedidos = cargar_pedidos()

            encontrado = False
            pedido_actualizado = None

            for pedido in pedidos:

                id_actual = pedido.get(
                    "id"
                )

                if (
                    str(id_actual)
                    != str(pedido_id)
                ):
                    continue

                encontrado = True

                # --------------------------------------------
                # ESTADO
                # --------------------------------------------

                if "estado" in solicitud:

                    nuevo_estado = (
                        solicitud.get(
                            "estado"
                        )
                    )

                    estados_validos = [
                        "Nuevo",
                        "Confirmado",
                        "Preparando",
                        "Enviado",
                        "Entregado"
                    ]

                    if nuevo_estado not in estados_validos:

                        self.enviar_json(
                            {
                                "ok": False,
                                "error":
                                    "Estado de pedido no válido"
                            },
                            400
                        )

                        return

                    pedido[
                        "estado"
                    ] = nuevo_estado

                    print(
                        f"Estado actualizado: "
                        f"{pedido_id} → "
                        f"{nuevo_estado}"
                    )

                # --------------------------------------------
                # PAGO
                # --------------------------------------------

                if "pago" in solicitud:

                    pago_enviado = (
                        solicitud.get(
                            "pago"
                        )
                    )

                    if not isinstance(
                        pago_enviado,
                        dict
                    ):

                        self.enviar_json(
                            {
                                "ok": False,
                                "error":
                                    "La información del pago no es válida"
                            },
                            400
                        )

                        return

                    pago_actual = obtener_pago(
                        pedido
                    )

                    if "estado" in pago_enviado:

                        pago_actual[
                            "estado"
                        ] = pago_enviado.get(
                            "estado"
                        )

                    if "metodo" in pago_enviado:

                        pago_actual[
                            "metodo"
                        ] = pago_enviado.get(
                            "metodo"
                        )

                    if "referencia" in pago_enviado:

                        pago_actual[
                            "referencia"
                        ] = pago_enviado.get(
                            "referencia"
                        )

                    pedido[
                        "pago"
                    ] = {

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

                    # Compatibilidad
                    pedido[
                        "estadoPago"
                    ] = pedido[
                        "pago"
                    ][
                        "estado"
                    ]

                    pedido[
                        "metodoPago"
                    ] = pedido[
                        "pago"
                    ][
                        "metodo"
                    ]

                    pedido[
                        "referenciaPago"
                    ] = pedido[
                        "pago"
                    ][
                        "referencia"
                    ]

                    print(
                        f"Pago actualizado: "
                        f"{pedido_id} → "
                        f"{pedido['pago']}"
                    )

                pedido_actualizado = pedido

                break

            if not encontrado:

                self.enviar_json(
                    {
                        "ok": False,
                        "error":
                            "Pedido no encontrado"
                    },
                    404
                )

                return

            # Guardar actualización
            if USAR_POSTGRES:

                actualizar_pedido_postgres(
                    pedido_actualizado
                )

            else:

                guardar_pedidos(
                    pedidos
                )

            self.enviar_json(
                {
                    "ok": True,
                    "mensaje":
                        "Pedido actualizado correctamente",
                    "pedido":
                        pedido_actualizado
                }
            )

        except json.JSONDecodeError:

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        "Los datos recibidos no son JSON válido"
                },
                400
            )

        except Exception as error:

            print(
                "Error PATCH:",
                error
            )

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        str(error)
                },
                500
            )

    # --------------------------------------------------------
    # DELETE - ELIMINAR PEDIDO
    # --------------------------------------------------------

    def do_DELETE(self):

        ruta = urlparse(
            self.path
        ).path

        if ruta != "/api/pedidos":

            self.send_error(
                404
            )

            return

        # Solo administrador
        if not self.exigir_admin():
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
                    consulta[
                        "id"
                    ][0]
                )

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

                    pedido_id = solicitud.get(
                        "id"
                    )

            if (
                pedido_id is None
                or str(pedido_id).strip() == ""
            ):

                self.enviar_json(
                    {
                        "ok": False,
                        "error":
                            "No se recibió el ID del pedido"
                    },
                    400
                )

                return

            # ------------------------------------------------
            # POSTGRES
            # ------------------------------------------------

            if USAR_POSTGRES:

                eliminado = (
                    eliminar_pedido_postgres(
                        pedido_id
                    )
                )

                if not eliminado:

                    self.enviar_json(
                        {
                            "ok": False,
                            "error":
                                "Pedido no encontrado"
                        },
                        404
                    )

                    return

            # ------------------------------------------------
            # LOCAL
            # ------------------------------------------------

            else:

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

                    self.enviar_json(
                        {
                            "ok": False,
                            "error":
                                "Pedido no encontrado"
                        },
                        404
                    )

                    return

                guardar_pedidos(
                    pedidos_nuevos
                )

            print(
                f"Pedido eliminado: "
                f"{pedido_id}"
            )

            self.enviar_json(
                {
                    "ok": True,
                    "mensaje":
                        "Pedido eliminado correctamente",
                    "id":
                        pedido_id
                }
            )

        except json.JSONDecodeError:

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        "Los datos recibidos no son JSON válido"
                },
                400
            )

        except Exception as error:

            print(
                "Error DELETE:",
                error
            )

            self.enviar_json(
                {
                    "ok": False,
                    "error":
                        str(error)
                },
                500
            )


# ============================================================
# INICIO
# ============================================================

if __name__ == "__main__":

    inicializar_base_datos()

    servidor = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PUERTO
        ),
        ServidorGBO
    )

    print("----------------------------------------")
    print("   GOLBEYONE - SERVIDOR DE PEDIDOS")
    print("----------------------------------------")

    print(
        f"Servidor iniciado en el puerto {PUERTO}"
    )

    if USAR_POSTGRES:

        print(
            "🗄️ Base de datos: PostgreSQL"
        )

        if ADMIN_TOKEN:

            print(
                "🔐 Protección admin: ACTIVA"
            )

        else:

            print(
                "⚠️ ADMIN_TOKEN no configurado"
            )

    else:

        print(
            "🗂️ Base de datos: pedidos.json"
        )

    print(
        "API: /api/pedidos"
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