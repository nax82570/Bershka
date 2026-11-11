"""Ejecutar una sola vez después de configurar .env; permite actualizar contraseña de admin."""
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

load_dotenv()
correo = os.environ.get('ADMIN_EMAIL', '').strip().lower()
clave = os.environ.get('ADMIN_PASSWORD', '')
uri = os.environ.get('MONGO_URI', '')
if not uri or not correo or len(clave) < 8:
    raise SystemExit('Configura MONGO_URI, ADMIN_EMAIL y ADMIN_PASSWORD (mínimo 8 caracteres) en .env.')
db = MongoClient(uri, serverSelectionTimeoutMS=10000)[os.getenv('MONGO_DB', 'bershka_ropa')]
db.usuarios.update_one({'correo': correo}, {'$set': {'nombre': 'Administrador', 'clave_hash': generate_password_hash(clave), 'admin': True}}, upsert=True)
print('Administrador configurado:', correo)
