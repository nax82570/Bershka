"""Carga prendas de ejemplo sin duplicarlas. Opcional."""
import os
from dotenv import load_dotenv
from pymongo import MongoClient
load_dotenv()
uri = os.getenv('MONGO_URI')
if not uri:
    raise SystemExit('Configura MONGO_URI en .env')
col = MongoClient(uri)[os.getenv('MONGO_DB', 'bershka_ropa')].productos
muestras = [
    ('Playera oversized', 'Playeras', 'M', 299, 12, 'Playera casual de corte amplio.'),
    ('Jeans rectos', 'Jeans', '30', 699, 8, 'Pantalón de mezclilla de corte recto.'),
    ('Sudadera urbana', 'Sudaderas', 'L', 799, 3, 'Sudadera cómoda para todos los días.'),
    ('Vestido midi', 'Vestidos', 'S', 649, 6, 'Vestido de estilo contemporáneo.'),
    ('Chamarra ligera', 'Chamarras', 'M', 1099, 0, 'Chamarra versátil de entretiempo.'),
]
for nombre, categoria, talla, precio, stock, descripcion in muestras:
    col.update_one({'nombre': nombre}, {'$setOnInsert': dict(nombre=nombre, categoria=categoria, talla=talla, precio=precio, stock=stock, descripcion=descripcion, imagen='')}, upsert=True)
print('Productos de ejemplo disponibles:', col.count_documents({}))
