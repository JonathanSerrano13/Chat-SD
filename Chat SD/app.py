"""
APLICACIÓN DE CHAT POR SALAS CON FLASK Y WEBSOCKETS
- Autenticación de usuarios
- Salas creadas con códigos numéricos de 6 dígitos
- Mensajes en tiempo real con Socket.IO
- Carga de archivos (audio, video, imágenes) en Base de Datos
"""

import os
import hashlib
import secrets
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, Response
from flask_socketio import SocketIO, join_room, emit

from db import cerrar_db, consultar_db, obtener_db

# ========== CONFIGURACIÓN ==========
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB max para upload
socketio = SocketIO(app, async_mode="eventlet")
app.teardown_appcontext(cerrar_db)

# Extensiones de archivo permitidas
ALLOWED_EXTENSIONS = {"mp3", "mp4", "jpg", "png"}

# ========== DECORADORES ==========
def requiere_login(fn):
    """Decorador que redirige al login si no está autenticado"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# ========== FUNCIONES DE SEGURIDAD ==========
def hashear_contrasena(contrasena):
    """
    Hashea una contraseña con salt usando SHA256
    @param contrasena: Contraseña en texto plano
    @return: String con formato "salt$hash"
    """
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + contrasena).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"

def verificar_contrasena(contrasena, almacenada):
    """
    Verifica si una contraseña coincide con su hash almacenado
    @param contrasena: Contraseña en texto plano
    @param almacenada: Hash almacenado en formato "salt$hash"
    @return: True si coincide, False si no
    """
    try:
        salt, digest = almacenada.split("$", 1)
    except ValueError:
        return False
    check = hashlib.sha256((salt + contrasena).encode("utf-8")).hexdigest()
    return check == digest

# ========== FUNCIONES DE SALAS Y USUARIOS ==========
def nombre_sala(tipo_sala, id_sala):
    """Genera un nombre único para la sala (para Socket.IO)"""
    return f"{tipo_sala}_{id_sala}"

def nombre_sala_usuario(id_usuario):
    """Genera un nombre único para la sala personal del usuario"""
    return f"user_{id_usuario}"

CODIGO_ALFABETO = "0123456789"

def generar_codigo_sala():
    """
    Genera un código numérico único de 6 dígitos para la sala
    @return: String de 6 números
    """
    while True:
        codigo = "".join(secrets.choice(CODIGO_ALFABETO) for _ in range(6))
        existe = consultar_db(
            "SELECT id_sala FROM Salas WHERE codigo = %s",
            (codigo,),
            one=True,
        )
        if not existe:
            return codigo

def usuario_en_sala(id_usuario, id_sala):
    """Verifica si un usuario es miembro de una sala"""
    fila = consultar_db(
        """
        SELECT id FROM Miembros_Sala
        WHERE id_sala = %s AND id_usuario = %s
        """,
        (id_sala, id_usuario),
        one=True,
    )
    return fila is not None

def archivo_permitido(filename):
    """Verifica si un archivo tiene una extensión permitida"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def insertar_aviso_sala(id_sala, mensaje, fecha):
    """Inserta un mensaje de sistema en la sala (join, leave, etc)"""
    db = obtener_db()
    cur = db.cursor()
    cur.execute(
        "INSERT INTO Mensajes_Sala (id_sala, id_emisor, contenido, fecha_envio, es_sistema) VALUES (%s, NULL, %s, %s, 1)",
        (id_sala, mensaje, fecha),
    )
    db.commit()
    cur.close()

# ========== RUTAS HTTP ==========
@app.route("/")
def index():
    """Redirecciona al chat si está logueado, sino al login"""
    if "user_id" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    """Registro de nuevos usuarios"""
    if request.method == "POST":
        usuario = request.form.get("username", "").strip()
        contrasena = request.form.get("password", "").strip()

        if not usuario or not contrasena:
            flash("Completa usuario y contrasena.")
            return redirect(url_for("register"))

        existente = consultar_db(
            "SELECT id_usuario FROM Usuarios WHERE usuario = %s",
            (usuario,),
            one=True,
        )
        if existente:
            flash("El usuario ya existe.")
            return redirect(url_for("register"))

        db = obtener_db()
        cur = db.cursor()
        cur.execute(
            "INSERT INTO Usuarios (usuario, contrasena) VALUES (%s, %s)",
            (usuario, hashear_contrasena(contrasena)),
        )
        db.commit()
        cur.close()
        flash("Cuenta creada. Inicia sesion.")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """Login de usuarios ya registrados"""
    if request.method == "POST":
        usuario = request.form.get("username", "").strip()
        contrasena = request.form.get("password", "").strip()

        user = consultar_db(
            "SELECT id_usuario, contrasena FROM Usuarios WHERE usuario = %s",
            (usuario,),
            one=True,
        )
        if not user or not verificar_contrasena(contrasena, user["contrasena"]):
            flash("Credenciales invalidas.")
            return redirect(url_for("login"))

        # Guardar datos en la sesión
        session["user_id"] = user["id_usuario"]
        session["username"] = usuario
        return redirect(url_for("chat"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    """Cierra la sesión del usuario"""
    session.clear()
    return redirect(url_for("login"))

@app.route("/chat")
@requiere_login
def chat():
    """Página principal del chat, muestra todas las salas del usuario"""
    id_usuario = session["user_id"]

    # Obtener salas a las que pertenece el usuario
    salas = consultar_db(
        """
        SELECT s.id_sala AS id, s.nombre_sala AS nombre, s.codigo, s.id_creador
        FROM Salas s
        JOIN Miembros_Sala m ON m.id_sala = s.id_sala
        WHERE m.id_usuario = %s
        ORDER BY s.nombre_sala, s.codigo
        """,
        (id_usuario,),
    )

    return render_template(
        "chat.html",
        username=session["username"],
        user_id=id_usuario,
        rooms=salas,
    )

# ========== GESTIÓN DE SALAS ==========
@app.route("/rooms/create", methods=["POST"])
@requiere_login
def room_create():
    """Crea una nueva sala"""
    id_usuario = session["user_id"]
    nombre = request.form.get("name", "").strip()
    if not nombre:
        nombre = "Sala sin nombre"

    # Generar código único de 6 dígitos
    codigo = generar_codigo_sala()

    db = obtener_db()
    cur = db.cursor()
    # Insertar sala en la BD
    cur.execute(
        "INSERT INTO Salas (codigo, nombre_sala, id_creador, fecha_creacion) VALUES (%s, %s, %s, %s)",
        (codigo, nombre, id_usuario, datetime.utcnow()),
    )
    id_sala = cur.lastrowid
    # Agregar el creador como miembro
    cur.execute(
        "INSERT INTO Miembros_Sala (id_sala, id_usuario, fecha_union) VALUES (%s, %s, %s)",
        (id_sala, id_usuario, datetime.utcnow()),
    )
    db.commit()
    cur.close()

    # Notificar a todos en la sala sobre la creación
    fecha = datetime.utcnow()
    aviso = f"{session.get('username', 'Anon')} se unio a la sala."
    insertar_aviso_sala(id_sala, aviso, fecha)
    socketio.emit(
        "room_notice",
        {
            "room_type": "room",
            "room_id": id_sala,
            "body": aviso,
            "timestamp": fecha.isoformat() + "Z",
        },
        to=nombre_sala("room", id_sala),
    )

    flash("Sala creada.")
    return redirect(url_for("chat"))

@app.route("/rooms/join", methods=["POST"])
@requiere_login
def room_join():
    """Une al usuario a una sala usando el código de 6 dígitos"""
    id_usuario = session["user_id"]
    codigo = request.form.get("code", "").strip().upper()

    # Validar formato del código
    if len(codigo) != 6 or not codigo.isdigit():
        flash("Codigo invalido.")
        return redirect(url_for("chat"))

    # Buscar la sala por código
    sala = consultar_db(
        "SELECT id_sala, codigo, nombre_sala FROM Salas WHERE codigo = %s",
        (codigo,),
        one=True,
    )
    if not sala:
        flash("Sala no encontrada.")
        return redirect(url_for("chat"))

    # Verificar si ya es miembro
    existente = consultar_db(
        "SELECT id FROM Miembros_Sala WHERE id_sala = %s AND id_usuario = %s",
        (sala["id_sala"], id_usuario),
        one=True,
    )
    if existente:
        flash("Ya estas en esa sala.")
        return redirect(url_for("chat"))

    db = obtener_db()
    cur = db.cursor()
    # Insertar como nuevo miembro
    cur.execute(
        "INSERT INTO Miembros_Sala (id_sala, id_usuario, fecha_union) VALUES (%s, %s, %s)",
        (sala["id_sala"], id_usuario, datetime.utcnow()),
    )
    db.commit()
    cur.close()

    flash("Te uniste a la sala.")
    # Notificar a otros miembros
    fecha = datetime.utcnow()
    aviso = f"{session.get('username', 'Anon')} se unio a la sala."
    insertar_aviso_sala(sala["id_sala"], aviso, fecha)
    socketio.emit(
        "room_notice",
        {
            "room_type": "room",
            "room_id": sala["id_sala"],
            "body": aviso,
            "timestamp": fecha.isoformat() + "Z",
        },
        to=nombre_sala("room", sala["id_sala"]),
    )
    socketio.emit(
        "actualizar_ui",
        {"motivo": "nueva_sala"},
        to=nombre_sala_usuario(id_usuario),
    )
    return redirect(url_for("chat"))

@app.route("/rooms/delete", methods=["POST"])
@requiere_login
def room_delete():
    """Elimina una sala (solo el creador puede hacerlo)"""
    id_usuario = session["user_id"]
    room_id = request.form.get("room_id", "").strip()

    if not room_id.isdigit():
        flash("Sala invalida.")
        return redirect(url_for("chat"))

    room_id = int(room_id)
    # Verificar que la sala existe y obtener al creador
    sala = consultar_db(
        "SELECT id_sala, id_creador FROM Salas WHERE id_sala = %s",
        (room_id,),
        one=True,
    )
    if not sala:
        flash("Sala no encontrada.")
        return redirect(url_for("chat"))

    # Verificar permisos
    if sala["id_creador"] != id_usuario:
        flash("Solo el creador puede borrar la sala.")
        return redirect(url_for("chat"))

    db = obtener_db()
    cur = db.cursor()
    # Eliminar la sala (esto elimina automáticamente sus mensajes y miembros por CASCADE)
    cur.execute("DELETE FROM Salas WHERE id_sala = %s", (room_id,))
    db.commit()
    cur.close()

    socketio.emit(
        "actualizar_ui",
        {"motivo": "sala_eliminada"},
        to=nombre_sala("room", room_id),
    )
    flash("Sala eliminada.")
    return redirect(url_for("chat"))

@app.route("/rooms/leave", methods=["POST"])
@requiere_login
def room_leave():
    """Sale de una sala (elimina la membresía del usuario)"""
    id_usuario = session["user_id"]
    room_id = request.form.get("room_id", "").strip()

    if not room_id.isdigit():
        flash("Sala invalida.")
        return redirect(url_for("chat"))

    room_id = int(room_id)
    # Verificar que el usuario es miembro
    miembro = consultar_db(
        "SELECT id FROM Miembros_Sala WHERE id_sala = %s AND id_usuario = %s",
        (room_id, id_usuario),
        one=True,
    )
    if not miembro:
        flash("No perteneces a esa sala.")
        return redirect(url_for("chat"))

    db = obtener_db()
    cur = db.cursor()
    # Eliminar la membresía
    cur.execute(
        "DELETE FROM Miembros_Sala WHERE id_sala = %s AND id_usuario = %s",
        (room_id, id_usuario),
    )
    db.commit()
    cur.close()

    # Notificar a otros miembros
    fecha = datetime.utcnow()
    aviso = f"{session.get('username', 'Anon')} salio de la sala."
    insertar_aviso_sala(room_id, aviso, fecha)
    socketio.emit(
        "room_notice",
        {
            "room_type": "room",
            "room_id": room_id,
            "body": aviso,
            "timestamp": fecha.isoformat() + "Z",
        },
        to=nombre_sala("room", room_id),
    )
    flash("Saliste de la sala.")
    return redirect(url_for("chat"))

# ========== APIs REST ==========
@app.route("/api/messages")
@requiere_login
def api_messages():
    """
    API para obtener el historial de mensajes de una sala.
    Retorna JSON con los últimos 50 mensajes.
    """
    id_usuario = session["user_id"]
    room_type = request.args.get("room_type", "")
    room_id = request.args.get("room_id", "")

    if not room_id.isdigit() or room_type != "room":
        return jsonify([])

    room_id = int(room_id)
    # Verificar que el usuario tiene acceso a la sala
    if not usuario_en_sala(id_usuario, room_id):
        return jsonify([])

    # Obtener últimos 50 mensajes (ordenados por ID)
    rows = consultar_db(
        """
        SELECT m.id_mensaje, m.contenido, m.fecha_envio, m.es_sistema, m.tipo_archivo, u.usuario AS sender
        FROM Mensajes_Sala m
        LEFT JOIN Usuarios u ON u.id_usuario = m.id_emisor
        WHERE m.id_sala = %s
        ORDER BY m.id_mensaje DESC
        LIMIT 50
        """,
        (room_id,),
    )

    return jsonify(list(reversed([dict(r) for r in rows])))

@app.route("/upload-media", methods=["POST"])
@requiere_login
def upload_media():
    """
    API para subir archivos multimedia (mp3, mp4, jpg, png).
    Almacena el archivo en la BD como LONGBLOB.
    """
    id_usuario = session["user_id"]
    room_id = request.form.get("room_id", "").strip()
    
    if not room_id.isdigit():
        return jsonify({"error": "Sala invalida."}), 400
    
    room_id = int(room_id)
    if not usuario_en_sala(id_usuario, room_id):
        return jsonify({"error": "No eres miembro de esa sala."}), 403
    
    if "file" not in request.files:
        return jsonify({"error": "No se subio archivo."}), 400
    
    file = request.files["file"]
    if not file or not archivo_permitido(file.filename):
        return jsonify({"error": "Archivo no permitido."}), 400
    
    # Leer el contenido del archivo en memoria
    archivo_contenido = file.read()
    
    # Detectar tipo
    ext = file.filename.rsplit(".", 1)[1].lower()
    if ext == "mp3":
        file_type = "audio"
    elif ext == "mp4":
        file_type = "video"
    elif ext in {"jpg", "png"}:
        file_type = "image"
    else:
        file_type = "file"
    
    db = obtener_db()
    cur = db.cursor()
    
    # Guardar en BD con el archivo como BLOB
    cur.execute(
        "INSERT INTO Mensajes_Sala (id_sala, id_emisor, contenido, fecha_envio, es_sistema, tipo_archivo, archivo_datos) VALUES (%s, %s, %s, %s, 0, %s, %s)",
        (room_id, id_usuario, file.filename, datetime.utcnow(), file_type, archivo_contenido),
    )
    db.commit()
    id_mensaje = cur.lastrowid
    cur.close()
    
    socketio.server.emit(
        "media_message",
        {
            "room_type": "room",
            "room_id": room_id,
            "id_mensaje": id_mensaje,
            "type": file_type,
            "sender": session.get("username", "anon"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
        room=nombre_sala("room", room_id),
        namespace="/"
    )
    
    return jsonify({"success": True, "id_mensaje": id_mensaje})

@app.route("/get-media/<int:id_mensaje>")
def get_media(id_mensaje):
    """
    API para descargar un archivo multimedia.
    El archivo se envía con el MIME type correcto.
    """
    mensaje = consultar_db(
        "SELECT archivo_datos, tipo_archivo, contenido FROM Mensajes_Sala WHERE id_mensaje = %s",
        (id_mensaje,),
        one=True,
    )
    
    if not mensaje or not mensaje["archivo_datos"]:
        return "Not found", 404
    
    # Detectar el MIME type según el tipo de archivo
    mime_types = {
        "audio": "audio/mpeg",
        "video": "video/mp4",
        "image": "image/jpeg" if mensaje["contenido"].lower().endswith(".jpeg") or mensaje["contenido"].lower().endswith(".jpg") else "image/png",
    }
    mime_type = mime_types.get(mensaje["tipo_archivo"], "application/octet-stream")
    
    from flask import Response
    return Response(mensaje["archivo_datos"], mimetype=mime_type)

# ========== SOCKET IO (WEBSOCKETS PARA TIEMPO REAL) ==========
@socketio.on("connect")
def manejar_conexion():
    """Se ejecuta cuando un usuario se conecta al WebSocket"""
    id_usuario = session.get("user_id")
    if not id_usuario:
        return
    
    # Unirse a la "sala" personal del usuario para notificaciones
    join_room(nombre_sala_usuario(id_usuario))

    # Unirse a todas las salas a las que pertenece
    salas = consultar_db(
        "SELECT id_sala FROM Miembros_Sala WHERE id_usuario = %s",
        (id_usuario,),
    )
    for sala in salas:
        join_room(nombre_sala("room", sala["id_sala"]))

@socketio.on("send_message")
def manejar_envio_mensaje(data):
    """
    Handler para mensajes de texto en tiempo real.
    Guarda en BD y emite a otros usuarios de la sala.
    """
    id_usuario = session.get("user_id")
    if not id_usuario:
        return

    room_type = data.get("room_type")
    room_id = data.get("room_id")
    body = (data.get("body") or "").strip()

    # Validaciones
    if room_type != "room" or not str(room_id).isdigit() or not body:
        return

    room_id = int(room_id)
    # Verificar que el usuario es miembro
    if not usuario_en_sala(id_usuario, room_id):
        return

    # Guardar en BD
    db = obtener_db()
    cur = db.cursor()
    fecha = datetime.utcnow()
    cur.execute(
        "INSERT INTO Mensajes_Sala (id_sala, id_emisor, contenido, fecha_envio, es_sistema) VALUES (%s, %s, %s, %s, 0)",
        (room_id, id_usuario, body, fecha),
    )
    db.commit()
    cur.close()

    # Emitir a todos en la sala
    emit(
        "message",
        {
            "room_type": room_type,
            "room_id": room_id,
            "body": body,
            "sender": session.get("username", "anon"),
            "timestamp": fecha.isoformat() + "Z",
        },
        to=nombre_sala(room_type, room_id),
    )

# ========== PUNTO DE ENTRADA ==========
if __name__ == "__main__":
    # Inicia el servidor Flask con SocketIO en puerto 5000
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)