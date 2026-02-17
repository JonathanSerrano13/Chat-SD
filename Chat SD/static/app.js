// ========== INICIALIZACIÓN Y VARIABLES GLOBALES ==========
const socket = io(); // Conexión WebSocket para mensajes en tiempo real
let salaActual = null; // Almacena la sala seleccionada actualmente

// Elementos del DOM
const listaSalas = document.getElementById("roomList");
const mensajesEl = document.getElementById("messages");
const form = document.getElementById("messageForm");
const input = document.getElementById("messageInput");
const messageFooter = document.getElementById("messageFooter");
const emojiToggle = document.getElementById("emojiToggle");
const emojiPicker = document.getElementById("emojiPicker");

// ========== MANEJO DE EMOJIS ==========
/**
 * Inserta un emoji en el campo de texto en la posición del cursor
 * @param {string} emoji - El emoji a insertar
 */
function insertarEmoji(emoji) {
    if (!input) return;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    const antes = input.value.slice(0, start);
    const despues = input.value.slice(end);
    input.value = `${antes}${emoji}${despues}`;
    const cursor = start + emoji.length;
    input.setSelectionRange(cursor, cursor);
    input.focus();
}

// Mostrar/ocultar selector de emojis
if (emojiToggle && emojiPicker) {
    emojiToggle.addEventListener("click", () => {
        emojiPicker.classList.toggle("d-none");
    });

    emojiPicker.addEventListener("emoji-click", (event) => {
        insertarEmoji(event.detail.unicode);
    });
}

// ========== MANEJO DE CARGA DE ARCHIVOS ==========
const fileInput = document.getElementById("fileInput");
if (fileInput) {
    fileInput.addEventListener("change", (e) => {
        if (!salaActual) {
            alert("Selecciona una sala primero.");
            fileInput.value = "";
            return;
        }
        
        if (!e.target.files[0]) return;
        
        const formData = new FormData();
        formData.append("room_id", salaActual.room_id);
        formData.append("file", e.target.files[0]);
        
        // Enviar archivo al servidor
        fetch("/upload-media", { method: "POST", body: formData })
            .then((res) => res.json())
            .then((data) => {
                if (data.error) {
                    alert("Error: " + data.error);
                }
            })
            .catch((err) => console.error("Error:", err));
        
        fileInput.value = "";
    });
}

// ========== UTILIDADES ==========
/** Limpia todos los mensajes del chat */
function limpiarMensajes() {
    mensajesEl.innerHTML = "";
}

/**
 * Convierte diferentes formatos de fecha a objeto Date
 * @param {Date|string} valor - Valor de fecha
 * @returns {Date|null}
 */
function normalizarFecha(valor) {
    if (!valor) return null;
    if (typeof valor === "string") {
        if (valor.includes("T")) return new Date(valor);
        if (valor.includes(" ")) return new Date(valor.replace(" ", "T") + "Z");
    }
    return new Date(valor);
}

/**
 * Formatea una fecha al formato local
 * @param {Date|string} valor
 * @returns {string}
 */
function formatearFecha(valor) {
    const fecha = normalizarFecha(valor);
    if (!fecha || Number.isNaN(fecha.getTime())) return "";
    return fecha.toLocaleString();
}

/**
 * Añade un mensaje de texto al chat
 * @param {string} emisor - Nombre del usuario que envía
 * @param {string} cuerpo - Contenido del mensaje
 * @param {string} timestamp - Fecha de envío
 */
function agregarMensaje(emisor, cuerpo, timestamp) {
    const div = document.createElement("div");
    div.className = "message";
    const hora = formatearFecha(timestamp);
    const sello = hora ? `<span class="timestamp">${hora}</span>` : "";
    div.innerHTML = `<span class="sender">${emisor}:</span> ${cuerpo} ${sello}`;
    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
}

/**
 * Muestra un aviso del sistema (alguien entró/salió)
 * @param {string} cuerpo - Texto del aviso
 * @param {string} timestamp - Fecha
 */
function mostrarAviso(cuerpo, timestamp) {
    const div = document.createElement("div");
    div.className = "message notice";
    const hora = formatearFecha(timestamp);
    const sello = hora ? `<span class="timestamp">${hora}</span>` : "";
    div.innerHTML = `<span class="notice-text">${cuerpo}</span> ${sello}`;
    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
}

// ========== HISTORIAL DE MENSAJES ==========
/**
 * Carga el historial de mensajes de una sala
 * @param {string} tipoSala - "room"
 * @param {number} idSala - ID de la sala
 */
async function cargarHistorial(tipoSala, idSala) {
    limpiarMensajes();
    const res = await fetch(`/api/messages?room_type=${tipoSala}&room_id=${idSala}`);
    const data = await res.json();
    data.forEach((m) => {
        if (m.es_sistema) {
            // Mensaje del sistema (join/leave)
            mostrarAviso(m.contenido || m.body, m.fecha_envio);
        } else {
            // Si tiene tipo_archivo, es media
            if (m.tipo_archivo) {
                mostrarMedia(m.sender, m.id_mensaje, m.tipo_archivo, m.fecha_envio);
            } else {
                agregarMensaje(m.sender, m.contenido || m.body, m.fecha_envio);
            }
        }
    });
}

if (listaSalas) {
    // Seleccionar una sala al hacer clic
    listaSalas.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-room-type]");
        if (!btn) return;
        salaActual = {
        room_type: btn.dataset.roomType,
        room_id: btn.dataset.roomId
        };
        // Cargar historial y mostrar el footer del chat
        cargarHistorial(salaActual.room_type, salaActual.room_id);
        if (messageFooter) {
            messageFooter.classList.remove("d-none");
        }
    });
}

// ========== ENVÍO DE MENSAJES ==========
if (form) {
    form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!salaActual) {
        alert("Selecciona un chat primero.");
        return;
        }
        const body = input.value.trim();
        if (!body) return;
        
        // Emitir mensaje a través del socket
        socket.emit("send_message", {
        room_type: salaActual.room_type,
        room_id: salaActual.room_id,
        body
        });
        input.value = "";
    });
}

// ========== ESCUCHADORES DE SOCKET (EVENTOS EN TIEMPO REAL) ==========
/** Recibe mensajes de texto de otros usuarios */
socket.on("message", (msg) => {
    if (!salaActual) return;
    if (msg.room_type === salaActual.room_type && String(msg.room_id) === String(salaActual.room_id)) {
        agregarMensaje(msg.sender, msg.body, msg.timestamp);
    }
});

/** Recibe avisos del sistema (usuario entró/salió) */
socket.on("room_notice", (msg) => {
    if (!salaActual) return;
    if (msg.room_type === salaActual.room_type && String(msg.room_id) === String(salaActual.room_id)) {
        mostrarAviso(msg.body, msg.timestamp);
    }
});

/** Recarga la página cuando hay cambios en las salas */
socket.on("actualizar_ui", () => {
    window.location.reload();
});

/** Recibe archivos compartidos (audio, video, imágenes) */
socket.on("media_message", (msg) => {
    if (!salaActual) return;
    if (msg.room_type === salaActual.room_type && String(msg.room_id) === String(salaActual.room_id)) {
        mostrarMedia(msg.sender, msg.id_mensaje, msg.type, msg.timestamp);
    }
});

// ========== MOSTRAR ARCHIVOS MULTIMEDIA ==========
/**
 * Muestra un archivo multimedia (audio, video, imagen)
 * @param {string} emisor - Nombre del usuario que compartió
 * @param {number} idMensaje - ID del mensaje
 * @param {string} tipo - Tipo: "audio", "video" o "image"
 * @param {string} timestamp - Fecha de envío
 */
function mostrarMedia(emisor, idMensaje, tipo, timestamp) {
    const div = document.createElement("div");
    div.className = "media-message";
    const hora = formatearFecha(timestamp);
    const sello = hora ? ` <span class="timestamp">${hora}</span>` : "";
    const url = `/get-media/${idMensaje}`;
    let html = `<span class="sender">${emisor}:</span> `;
    
    // Crear elemento según el tipo de archivo
    if (tipo === "audio") {
        html += `<audio controls style="width: 100%; max-width: 300px;"><source src="${url}"><p>Tu navegador no soporta HTML5 audio.</p></audio>`;
    } else if (tipo === "video") {
        html += `<video controls style="width: 100%; max-width: 300px;"><source src="${url}"><p>Tu navegador no soporta HTML5 video.</p></video>`;
    } else if (tipo === "image") {
        html += `<img src="${url}" style="max-width: 300px; border-radius: 4px;">`;
    } else {
        html += `<a href="${url}" target="_blank">Descargar</a>`;
    }
    html += sello;
    
    div.innerHTML = html;
    mensajesEl.appendChild(div);
    mensajesEl.scrollTop = mensajesEl.scrollHeight;
}

