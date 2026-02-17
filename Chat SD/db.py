"""
Módulo de conexión a la base de datos MySQL
Proporciona funciones para ejecutar queries y conexiones seguras
"""
import os
import mysql.connector
from flask import g

def obtener_db():
    """
    Obtiene la conexión a la base de datos.
    La conexión se almacena en el contexto de Flask (g) para reutilizarse.
    """
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=os.environ.get("MYSQL_HOST", "localhost"),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", ""),
            database=os.environ.get("MYSQL_DB", "chat"),
            charset="utf8mb4",
            collation="utf8mb4_unicode_ci",
            autocommit=False,
        )
    return g.db

def cerrar_db(e=None):
    """Cierra la conexión a la base de datos al terminar la solicitud"""
    db = g.pop("db", None)
    if db:
        db.close()

def consultar_db(query, args=(), one=False):
    """
    Ejecuta una query a la base de datos
    @param query: Comando SQL con placeholders %s
    @param args: Tuple con parámetros para la query
    @param one: Si es True, retorna solo una fila. Si es False, retorna lista
    @return: Un diccionario (one=True) o lista de diccionarios
    """
    db = obtener_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(query, args)
    filas = cursor.fetchall()
    cursor.close()
    return (filas[0] if filas else None) if one else filas