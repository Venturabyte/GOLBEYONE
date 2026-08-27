from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import urlparse, parse_qs


PUERTO = int(os.environ.get("PORT", 5500))
ARCHIVO_PEDIDOS = "pedidos.json"


# =========================================================
# NOTIFICACIONES DE WINDOWS
# =========================================================

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
            "⚠️ winotify no está instalado."
        )

        print(
            "Instala con: pip install winotify"
        )

    except Exception as error:

        # -------------------------------------------------
        # IMPORTANTE:
        # Si la notificación falla, el pedido NO falla.
        # -------------------------------------------------

        print(
            "⚠️ Error en notificación:",
            error
        )


# =========================================================
# CARGAR PEDIDOS
# =========================================================

def cargar_pedidos():

    if not os.path.exists(
        ARCHIVO_PEDIDOS
    ):
        return []

    try:

        with open(
            ARCHIVO_PEDIDOS,
            "r",
            encoding="utf-8"
        ) as archivo:

            datos = json.load(
                archivo
            )

        if isinstance(
            datos,
            list
        ):
            return datos

        return []

    except (
        json.JSONDecodeError,
        OSError
    ):

        return []


# =========================================================
# GUARDAR PEDIDOS
# =========================================================

def guardar_pedidos(
    pedidos
):

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


# =========================================================
# NORMALIZAR INFORMACIÓN DE PAGO
# =========================================================

def obtener_pago(
    pedido
):

    pago_actual = pedido.get(
        "pago"
    )

    # -----------------------------------------------------
    # NUEVO FORMATO
    # -----------------------------------------------------

    if isinstance(
        pago_actual,
        dict
    ):

        return {

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

    # -----------------------------------------------------
    # COMPATIBILIDAD CON PEDIDOS ANTIGUOS
    # -----------------------------------------------------

    return {

        "estado":
            pedido.get(
                "estadoPago",
                "Pendiente"
            ),

        "metodo":
            pedido.get(
                "metodoPago",
                "Pendiente"
            ),

        "referencia":
            pedido.get(
                "referenciaPago",
                ""
            )

    }


# =========================================================
# NORMALIZAR PEDIDO
# =========================================================

def normalizar_pedido(
    pedido
):

    if not pedido.get(
        "estado"
    ):

        pedido["estado"] = "Nuevo"

    pago = obtener_pago(
        pedido
    )

    pedido["pago"] = {

        "estado":
            pago.get(
                "estado",
                "Pendiente"
            ),

        "metodo":
            pago.get(
                "metodo",
                "Pendiente"
            ),

        "referencia":
            pago.get(
                "referencia",
                ""
            )

    }

    return pedido


# =========================================================
# SERVIDOR
# =========================================================

class ServidorGBO(
    SimpleHTTPRequestHandler
):

    # =====================================================
    # ENVIAR JSON
    # =====================================================

    def enviar_json(
        self,
        datos,
        codigo=200
    ):

        respuesta = json.dumps(
            datos,
            ensure_ascii=False
        ).encode(
            "utf-8"
        )

        self.send_response(
            codigo
        )

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
            "Content-Type"
        )

        self.send_header(
            "Content-Length",
            str(
                len(respuesta)
            )
        )

        self.end_headers()

        self.wfile.write(
            respuesta
        )

    # =====================================================
    # OPTIONS
    # =====================================================

    def do_OPTIONS(
        self
    ):

        self.send_response(
            204
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
            "Content-Type"
        )

        self.end_headers()

    # =====================================================
    # GET
    # =====================================================

    def do_GET(
        self
    ):

        ruta = urlparse(
            self.path
        ).path

        if ruta == "/api/pedidos":

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

                guardar_pedidos(
                    pedidos
                )

            self.enviar_json(
                pedidos
            )

            return

        super().do_GET()

    # =====================================================
    # POST
    # =====================================================

    def do_POST(
        self
    ):

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

                self.enviar_json({

                    "ok": False,

                    "error":
                        "No se recibieron datos"

                }, 400)

                return

            datos = self.rfile.read(
                longitud
            )

            nuevo_pedido = json.loads(
                datos.decode(
                    "utf-8"
                )
            )

            if not isinstance(
                nuevo_pedido,
                dict
            ):

                self.enviar_json({

                    "ok": False,

                    "error":
                        "El pedido no es válido"

                }, 400)

                return

            # ------------------------------------------------
            # ESTADO INICIAL
            # ------------------------------------------------

            if not nuevo_pedido.get(
                "estado"
            ):

                nuevo_pedido["estado"] = "Nuevo"

            # ------------------------------------------------
            # INFORMACIÓN DE PAGO
            # ------------------------------------------------

            pago = obtener_pago(
                nuevo_pedido
            )

            nuevo_pedido["pago"] = {

                "estado":
                    pago.get(
                        "estado",
                        "Pendiente"
                    ),

                "metodo":
                    pago.get(
                        "metodo",
                        "Pendiente"
                    ),

                "referencia":
                    pago.get(
                        "referencia",
                        ""
                    )

            }

            # ------------------------------------------------
            # COMPATIBILIDAD
            # ------------------------------------------------

            nuevo_pedido["estadoPago"] = \
                nuevo_pedido["pago"]["estado"]

            nuevo_pedido["metodoPago"] = \
                nuevo_pedido["pago"]["metodo"]

            nuevo_pedido["referenciaPago"] = \
                nuevo_pedido["pago"]["referencia"]

            # ------------------------------------------------
            # GUARDAR PEDIDO
            # ------------------------------------------------

            pedidos = cargar_pedidos()

            pedidos.append(
                nuevo_pedido
            )

            guardar_pedidos(
                pedidos
            )

            pedido_id = str(
                nuevo_pedido.get(
                    "id",
                    "SIN-ID"
                )
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

            # ------------------------------------------------
            # 🔔 NOTIFICACIÓN DE ESCRITORIO
            #
            # IMPORTANTE:
            # Se ejecuta DESPUÉS de guardar el pedido.
            # Si falla, el pedido permanece guardado.
            # ------------------------------------------------

            notificar_nuevo_pedido(
                nuevo_pedido
            )

            # ------------------------------------------------
            # RESPUESTA AL CLIENTE
            # ------------------------------------------------

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
                "Error POST:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    str(error)

            }, 500)

    # =====================================================
    # PATCH
    # =====================================================

    def do_PATCH(
        self
    ):

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
                datos.decode(
                    "utf-8"
                )
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
                or str(
                    pedido_id
                ).strip() == ""
            ):

                self.enviar_json({

                    "ok": False,

                    "error":
                        "No se recibió el ID del pedido"

                }, 400)

                return

            pedidos = cargar_pedidos()

            encontrado = False

            pedido_actualizado = None

            # ------------------------------------------------
            # BUSCAR PEDIDO
            # ------------------------------------------------

            for pedido in pedidos:

                id_actual = pedido.get(
                    "id"
                )

                if str(
                    id_actual
                ) != str(
                    pedido_id
                ):

                    continue

                encontrado = True

                # --------------------------------------------
                # ESTADO DEL PEDIDO
                # --------------------------------------------

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

                        self.enviar_json({

                            "ok": False,

                            "error":
                                "Estado de pedido no válido"

                        }, 400)

                        return

                    pedido["estado"] = \
                        nuevo_estado

                    print(
                        f"Estado actualizado: "
                        f"{pedido_id} → "
                        f"{nuevo_estado}"
                    )

                # --------------------------------------------
                # ACTUALIZAR PAGO
                # --------------------------------------------

                if "pago" in solicitud:

                    pago_enviado = \
                        solicitud.get(
                            "pago"
                        )

                    if not isinstance(
                        pago_enviado,
                        dict
                    ):

                        self.enviar_json({

                            "ok": False,

                            "error":
                                "La información del pago no es válida"

                        }, 400)

                        return

                    pago_actual = obtener_pago(
                        pedido
                    )

                    if "estado" in pago_enviado:

                        pago_actual["estado"] = \
                            pago_enviado["estado"]

                    if "metodo" in pago_enviado:

                        pago_actual["metodo"] = \
                            pago_enviado["metodo"]

                    if "referencia" in pago_enviado:

                        pago_actual["referencia"] = \
                            pago_enviado["referencia"]

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

                    pedido["estadoPago"] = \
                        pedido["pago"]["estado"]

                    pedido["metodoPago"] = \
                        pedido["pago"]["metodo"]

                    pedido["referenciaPago"] = \
                        pedido["pago"]["referencia"]

                    print(
                        f"Pago actualizado: "
                        f"{pedido_id} → "
                        f"{pedido['pago']}"
                    )

                pedido_actualizado = pedido

                break

            # ------------------------------------------------
            # NO ENCONTRADO
            # ------------------------------------------------

            if not encontrado:

                self.enviar_json({

                    "ok": False,

                    "error":
                        "Pedido no encontrado"

                }, 404)

                return

            # ------------------------------------------------
            # GUARDAR
            # ------------------------------------------------

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
                "Error PATCH:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    str(error)

            }, 500)

    # =====================================================
    # DELETE
    # =====================================================

    def do_DELETE(
        self
    ):

        ruta = urlparse(
            self.path
        ).path

        if ruta != "/api/pedidos":

            self.send_error(
                404
            )

            return

        try:

            consulta = parse_qs(
                urlparse(
                    self.path
                ).query
            )

            pedido_id = None

            if "id" in consulta:

                pedido_id = \
                    consulta["id"][0]

            # ------------------------------------------------
            # TAMBIÉN ACEPTA JSON
            # ------------------------------------------------

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
                        datos.decode(
                            "utf-8"
                        )
                    )

                    pedido_id = \
                        solicitud.get(
                            "id"
                        )

            if (
                pedido_id is None
                or str(
                    pedido_id
                ).strip() == ""
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

                if str(
                    id_actual
                ) == str(
                    pedido_id
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
                f"Pedido eliminado: "
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
                "Error DELETE:",
                error
            )

            self.enviar_json({

                "ok": False,

                "error":
                    str(error)

            }, 500)


# =========================================================
# INICIAR SERVIDOR
# =========================================================

if __name__ == "__main__":

    servidor = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PUERTO
        ),
        ServidorGBO
    )

    print(
        "----------------------------------------"
    )

    print(
        "   GOLBEYONE - SERVIDOR DE PEDIDOS"
    )

    print(
        "----------------------------------------"
    )

    print(
        f"Servidor iniciado en el puerto {PUERTO}"
    )

    print(
        "Abre: http://localhost:5500"
    )

    print(
        "API:  http://localhost:5500/api/pedidos"
    )

    print(
        "🔔 Notificaciones de escritorio: ACTIVAS"
    )

    print(
        "----------------------------------------"
    )

    try:

        servidor.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nServidor detenido."
        )

    finally:

        servidor.server_close()