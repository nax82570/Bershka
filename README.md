# Bershka — proyecto académico de tienda de ropa

**Proyecto independiente de demostración, sin afiliación con la marca comercial Bershka.** No procesa pagos reales ni incluye QR.

## Funciones
- Catálogo, búsqueda, categorías, detalle, tallas, precios e imágenes por URL.
- Registro e inicio de sesión; contraseñas con hash y administrador separado.
- CRUD de prendas (alta, consulta, edición y eliminación) desde panel administrador.
- API REST JSON: GET `/api/productos`, GET `/api/productos/<id>`, POST `/api/productos`, PUT y DELETE `/api/productos/<id>` (las escrituras requieren sesión de administrador).
- Carrito de compras, apartar existencias durante **5 minutos**, contador, cancelar, confirmar compra simulada y vencimiento con devolución de stock.
- Avisos de pocas unidades y agotado, historial de reservas y compras.
- MongoDB Atlas, GitHub y Render configurables sin vínculos previos.

## Instalación (PowerShell de VS Code)
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```
Edita **solo `.env`** con tus datos de Atlas y una clave secreta generada con:
```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```
Configura `ADMIN_EMAIL` y `ADMIN_PASSWORD` (mínimo 8 caracteres). **Nunca subas `.env` a GitHub**.

```powershell
.\.venv\Scripts\python.exe setup_admin.py
.\.venv\Scripts\python.exe seed_demo.py
.\.venv\Scripts\python.exe app.py
```
Abre http://127.0.0.1:5000 y prueba `/api/estado`.

## Subir a GitHub
```powershell
git init
git add .
git status
git commit -m "Proyecto inicial Bershka"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```
Antes del commit, confirma que **`.env` no aparece** en `git status`.

## Publicar en Render
Crea un **Web Service** conectado al repositorio, rama `main`, runtime Python:
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- Variables: `MONGO_URI`, `MONGO_DB=bershka_ropa`, `SECRET_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`.

El administrador debe crearse **antes del despliegue** con `setup_admin.py` desde tu equipo, usando la misma base de Atlas. El archivo `render.yaml` es opcional.

## Evidencias sugeridas (6 capturas + 2 enlaces)
1. Catálogo público con prendas y existencias.
2. API JSON (`/api/productos` o Postman).
3. Carrito con producto y total.
4. Reserva de 5 minutos y contador.
5. Panel de administrador con CRUD.
6. Producto agotado / devolución de stock tras cancelar o vencer.

Enlaces: repositorio de GitHub y aplicación publicada en Render.

## Nota técnica
La expiración se procesa en las solicitudes a la aplicación, no con una tarea programada externa. Los descuentos de inventario usan operaciones atómicas; la aplicación es un prototipo escolar, no una pasarela comercial ni un sistema transaccional de producción. Para uso comercial se requerirían transacciones multi-documento, protección CSRF, límites de peticiones y auditoría.
