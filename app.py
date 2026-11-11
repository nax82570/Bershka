import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from bson import ObjectId
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from pymongo import MongoClient, ReturnDocument
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('FLASK_DEBUG') != '1')
uri = os.getenv('MONGO_URI', '').strip()
if not uri:
    raise RuntimeError('Falta MONGO_URI. Configura tu archivo .env o las variables de Render.')
client = MongoClient(uri, serverSelectionTimeoutMS=10000)
db = client[os.getenv('MONGO_DB', 'bershka_ropa')]
productos = db.productos
usuarios = db.usuarios
reservas = db.reservas
compras = db.compras
usuarios.create_index('correo', unique=True)
reservas.create_index([('estado', 1), ('vence_en', 1)])


def ahora():
    return datetime.now(timezone.utc)


def oid(valor):
    try:
        return ObjectId(valor)
    except Exception:
        abort(404)


def login_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not session.get('uid'):
            flash('Inicia sesión para continuar.', 'warning')
            return redirect(url_for('login', next=request.path))
        return fn(*args, **kwargs)
    return inner


def admin_required(fn):
    @wraps(fn)
    @login_required
    def inner(*args, **kwargs):
        u = usuarios.find_one({'_id': oid(session['uid'])})
        if not u or not u.get('admin'):
            abort(403)
        return fn(*args, **kwargs)
    return inner


def liberar_vencidas():
    # No depende de un proceso en segundo plano: se ejecuta antes de consultar stock.
    # Cada transición es atómica; solo la primera devuelve las unidades.
    vencidas = list(reservas.find({'estado': 'temporal', 'vence_en': {'$lte': ahora()}}))
    for r in vencidas:
        cambio = reservas.find_one_and_update(
            {'_id': r['_id'], 'estado': 'temporal'},
            {'$set': {'estado': 'vencida', 'actualizado_en': ahora()}},
            return_document=ReturnDocument.BEFORE,
        )
        if cambio:
            for item in cambio['items']:
                productos.update_one({'_id': item['producto_id']}, {'$inc': {'stock': item['cantidad']}})


def producto_publico(p):
    return dict(id=str(p['_id']), nombre=p.get('nombre', ''), categoria=p.get('categoria', ''),
                talla=p.get('talla', ''), precio=p.get('precio', 0), stock=p.get('stock', 0),
                descripcion=p.get('descripcion', ''), imagen=p.get('imagen', ''),
                agotado=p.get('stock', 0) <= 0, pocas=p.get('stock', 0) in (1, 2, 3))


def carrito_actual():
    raw = session.get('carrito', {})
    ids = [ObjectId(k) for k in raw if ObjectId.is_valid(k)]
    encontrados = {str(p['_id']): p for p in productos.find({'_id': {'$in': ids}})}
    items = []
    for key, cantidad in raw.items():
        if key in encontrados and isinstance(cantidad, int) and cantidad > 0:
            p = encontrados[key]
            items.append({'id': key, 'nombre': p['nombre'], 'talla': p.get('talla', ''),
                          'precio': p['precio'], 'cantidad': cantidad,
                          'subtotal': round(p['precio'] * cantidad, 2), 'stock': p.get('stock', 0)})
    return items


def reserva_activa():
    if not session.get('uid'):
        return None
    return reservas.find_one({'usuario_id': oid(session['uid']), 'estado': 'temporal', 'vence_en': {'$gt': ahora()}})


@app.before_request
def antes():
    # Evita alterar datos durante las peticiones a recursos estáticos.
    if request.endpoint != 'static':
        liberar_vencidas()


@app.context_processor
def contexto():
    return {'usuario_actual': session.get('nombre'), 'es_admin': session.get('admin', False)}


@app.route('/')
def index():
    q = request.args.get('q', '').strip()[:80]
    categoria = request.args.get('categoria', '').strip()[:50]
    filtro = {}
    if q:
        filtro['nombre'] = {'$regex': re.escape(q), '$options': 'i'}
    if categoria:
        filtro['categoria'] = categoria
    lista = [producto_publico(p) for p in productos.find(filtro).sort('_id', -1)]
    categorias = sorted(c for c in productos.distinct('categoria') if c)
    return render_template('index.html', lista=lista, categorias=categorias, q=q, categoria=categoria)


@app.route('/producto/<pid>')
def detalle(pid):
    p = productos.find_one({'_id': oid(pid)})
    if not p:
        abort(404)
    return render_template('detalle.html', p=producto_publico(p))


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()[:80]
        correo = request.form.get('correo', '').strip().lower()[:120]
        clave = request.form.get('clave', '')
        if not nombre or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', correo) or len(clave) < 8:
            flash('Ingresa nombre, correo válido y contraseña de al menos 8 caracteres.', 'danger')
        elif usuarios.find_one({'correo': correo}):
            flash('El correo ya está registrado.', 'danger')
        else:
            from pymongo.errors import DuplicateKeyError
            try:
                usuarios.insert_one({'nombre': nombre, 'correo': correo,
                                     'clave_hash': generate_password_hash(clave), 'admin': False})
                flash('Cuenta creada. Inicia sesión.', 'success')
                return redirect(url_for('login'))
            except DuplicateKeyError:
                flash('El correo ya está registrado.', 'danger')
    return render_template('auth.html', registro=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form.get('correo', '').strip().lower()
        clave = request.form.get('clave', '')
        u = usuarios.find_one({'correo': correo})
        if u and check_password_hash(u.get('clave_hash', ''), clave):
            session.clear()
            session.update(uid=str(u['_id']), nombre=u['nombre'], admin=bool(u.get('admin')))
            flash('Sesión iniciada.', 'success')
            destino = request.args.get('next', '')
            if destino.startswith('/') and not destino.startswith('//'):
                return redirect(destino)
            return redirect(url_for('index'))
        flash('Credenciales incorrectas.', 'danger')
    return render_template('auth.html', registro=False)


@app.post('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('index'))


@app.post('/carrito/agregar/<pid>')
def agregar_carrito(pid):
    p = productos.find_one({'_id': oid(pid)})
    if not p:
        abort(404)
    try:
        cantidad = int(request.form.get('cantidad', '1'))
    except ValueError:
        cantidad = 0
    c = dict(session.get('carrito', {}))
    if cantidad < 1 or cantidad > 50 or c.get(pid, 0) + cantidad > p.get('stock', 0):
        flash('Cantidad no disponible.', 'danger')
    else:
        c[pid] = c.get(pid, 0) + cantidad
        session['carrito'] = c
        flash('Producto agregado al carrito.', 'success')
    return redirect(url_for('carrito'))


@app.post('/carrito/quitar/<pid>')
def quitar_carrito(pid):
    c = dict(session.get('carrito', {}))
    c.pop(pid, None)
    session['carrito'] = c
    return redirect(url_for('carrito'))


@app.route('/carrito')
def carrito():
    items = carrito_actual()
    r = reserva_activa()
    return render_template('carrito.html', items=items, total=round(sum(x['subtotal'] for x in items), 2),
                           reserva=r, vence_ts=int(r['vence_en'].timestamp()) if r else None)


@app.post('/carrito/reservar')
@login_required
def reservar():
    if reserva_activa():
        flash('Ya tienes una reserva temporal activa.', 'warning')
        return redirect(url_for('carrito'))
    items = carrito_actual()
    if not items:
        flash('El carrito está vacío.', 'danger')
        return redirect(url_for('carrito'))
    apartados = []
    try:
        for item in items:
            p = productos.find_one_and_update(
                {'_id': oid(item['id']), 'stock': {'$gte': item['cantidad']}},
                {'$inc': {'stock': -item['cantidad']}}, return_document=ReturnDocument.BEFORE)
            if p is None:
                raise ValueError('Stock insuficiente para ' + item['nombre'])
            apartados.append({'producto_id': p['_id'], 'nombre': p['nombre'],
                              'talla': p.get('talla', ''), 'cantidad': item['cantidad'],
                              'precio': p['precio']})
        r = {'usuario_id': oid(session['uid']), 'items': apartados,
             'total': round(sum(x['precio'] * x['cantidad'] for x in apartados), 2),
             'estado': 'temporal', 'creado_en': ahora(), 'vence_en': ahora() + timedelta(minutes=5)}
        reservas.insert_one(r)
        flash('Reserva creada por 5 minutos.', 'success')
    except Exception as e:
        for x in apartados:
            productos.update_one({'_id': x['producto_id']}, {'$inc': {'stock': x['cantidad']}})
        flash('No se pudo reservar: ' + str(e), 'danger')
    return redirect(url_for('carrito'))


@app.post('/reserva/<rid>/cancelar')
@login_required
def cancelar(rid):
    r = reservas.find_one_and_update({'_id': oid(rid), 'usuario_id': oid(session['uid']), 'estado': 'temporal'},
                                     {'$set': {'estado': 'cancelada', 'actualizado_en': ahora()}},
                                     return_document=ReturnDocument.BEFORE)
    if r:
        for item in r['items']:
            productos.update_one({'_id': item['producto_id']}, {'$inc': {'stock': item['cantidad']}})
        flash('Reserva cancelada. Existencias devueltas.', 'success')
    else:
        flash('La reserva ya no está activa.', 'warning')
    return redirect(url_for('carrito'))


@app.post('/reserva/<rid>/confirmar')
@login_required
def confirmar(rid):
    r = reservas.find_one_and_update({'_id': oid(rid), 'usuario_id': oid(session['uid']),
                                      'estado': 'temporal', 'vence_en': {'$gt': ahora()}},
                                     {'$set': {'estado': 'confirmada', 'actualizado_en': ahora()}},
                                     return_document=ReturnDocument.AFTER)
    if not r:
        flash('La reserva venció o ya fue procesada.', 'danger')
        return redirect(url_for('carrito'))
    compras.insert_one({'reserva_id': r['_id'], 'usuario_id': r['usuario_id'],
                        'items': r['items'], 'total': r['total'], 'creado_en': ahora(), 'simulada': True})
    session['carrito'] = {}
    flash('Compra simulada confirmada. No se realizó ningún cobro.', 'success')
    return redirect(url_for('mis_compras'))


@app.route('/mis-compras')
@login_required
def mis_compras():
    lista = list(compras.find({'usuario_id': oid(session['uid'])}).sort('_id', -1))
    return render_template('compras.html', lista=lista)


@app.route('/mis-reservas')
@login_required
def mis_reservas():
    lista = list(reservas.find({'usuario_id': oid(session['uid'])}).sort('_id', -1))
    return render_template('reservas.html', lista=lista)


def datos_formulario():
    nombre = request.form.get('nombre', '').strip()[:100]
    categoria = request.form.get('categoria', '').strip()[:50]
    talla = request.form.get('talla', '').strip()[:30]
    descripcion = request.form.get('descripcion', '').strip()[:1000]
    imagen = request.form.get('imagen', '').strip()[:500]
    try:
        precio = round(float(request.form.get('precio', '0')), 2)
        stock = int(request.form.get('stock', '0'))
    except ValueError:
        raise ValueError('Precio y existencias deben ser numéricos.')
    if not nombre or not categoria or precio <= 0 or precio > 1000000 or stock < 0 or stock > 100000:
        raise ValueError('Revisa nombre, categoría, precio y existencias.')
    if imagen:
        u = urlparse(imagen)
        if u.scheme not in ('https', 'http') or not u.netloc:
            raise ValueError('La imagen debe tener una URL http(s) válida.')
    return dict(nombre=nombre, categoria=categoria, talla=talla, descripcion=descripcion,
                imagen=imagen, precio=precio, stock=stock)


@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html', lista=[producto_publico(p) for p in productos.find().sort('_id', -1)],
                           n_usuarios=usuarios.count_documents({}), n_compras=compras.count_documents({}))


@app.route('/admin/producto/nuevo', methods=['GET', 'POST'])
@admin_required
def nuevo():
    if request.method == 'POST':
        try:
            productos.insert_one(datos_formulario())
            flash('Producto registrado.', 'success')
            return redirect(url_for('admin'))
        except ValueError as e:
            flash(str(e), 'danger')
    return render_template('form_producto.html', p=None)


@app.route('/admin/producto/<pid>/editar', methods=['GET', 'POST'])
@admin_required
def editar(pid):
    p = productos.find_one({'_id': oid(pid)})
    if not p:
        abort(404)
    if request.method == 'POST':
        try:
            datos = datos_formulario()
            # El stock ingresado es el disponible, sin incluir reservas temporales.
            productos.update_one({'_id': p['_id']}, {'$set': datos})
            flash('Producto actualizado.', 'success')
            return redirect(url_for('admin'))
        except ValueError as e:
            flash(str(e), 'danger')
    return render_template('form_producto.html', p=producto_publico(p))


@app.post('/admin/producto/<pid>/eliminar')
@admin_required
def eliminar(pid):
    if reservas.count_documents({'estado': 'temporal', 'items.producto_id': oid(pid)}) > 0:
        flash('No se puede eliminar un producto con reservas activas.', 'danger')
    else:
        productos.delete_one({'_id': oid(pid)})
        flash('Producto eliminado.', 'success')
    return redirect(url_for('admin'))


@app.route('/api/productos', methods=['GET', 'POST'])
def api_productos():
    if request.method == 'GET':
        return jsonify([producto_publico(p) for p in productos.find()])
    return api_crear()


def api_autorizado():
    if not session.get('uid'):
        return False
    u = usuarios.find_one({'_id': oid(session['uid'])})
    return bool(u and u.get('admin'))


def api_crear():
    if not api_autorizado():
        return jsonify(error='Acceso de administrador requerido'), 403
    d = request.get_json(silent=True) or {}
    try:
        # Reutiliza validación del formulario mediante un MultiDict temporal.
        from werkzeug.datastructures import MultiDict
        with app.test_request_context(data=MultiDict({k: str(v) for k, v in d.items()})):
            datos = datos_formulario()
        resultado = productos.insert_one(datos)
        return jsonify(id=str(resultado.inserted_id), ok=True), 201
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.route('/api/productos/<pid>', methods=['GET', 'PUT', 'DELETE'])
def api_producto(pid):
    p = productos.find_one({'_id': oid(pid)})
    if not p:
        return jsonify(error='Producto no encontrado'), 404
    if request.method == 'GET':
        return jsonify(producto_publico(p))
    if not api_autorizado():
        return jsonify(error='Acceso de administrador requerido'), 403
    if request.method == 'DELETE':
        if reservas.count_documents({'estado': 'temporal', 'items.producto_id': p['_id']}) > 0:
            return jsonify(error='Hay reservas activas'), 409
        productos.delete_one({'_id': p['_id']})
        return jsonify(ok=True)
    d = request.get_json(silent=True) or {}
    try:
        from werkzeug.datastructures import MultiDict
        combinado = {**producto_publico(p), **d}
        with app.test_request_context(data=MultiDict({k: str(v) for k, v in combinado.items()})):
            datos = datos_formulario()
        productos.update_one({'_id': p['_id']}, {'$set': datos})
        return jsonify(ok=True)
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.route('/api/estado')
def estado():
    return jsonify(ok=1, aplicacion='Bershka', mongo='conectado')


@app.errorhandler(404)
def error404(e):
    return render_template('error.html', mensaje='Página no encontrada'), 404


@app.errorhandler(403)
def error403(e):
    return render_template('error.html', mensaje='Acceso no autorizado'), 403


if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG') == '1')
