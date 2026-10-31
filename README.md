# Provcommerce

Primera versión de un espacio B2B para investigar productos y proveedores. La landing contiene una vista previa ilustrativa; las búsquedas solo muestran información devuelta por la fuente configurada, sin inventar precios, reputaciones ni proveedores. Ofertas y tendencias son módulos iniciales sin datos. No incluye pagos.

## Requisitos

Node.js 20 o superior, Python 3.10 o superior, un proyecto Supabase y, para búsquedas reales, un token de Apify y un Actor compatible. El Actor debe aceptar el campo de consulta configurado y devolver objetos con `title` o `name`, y opcionalmente `url` y `description`. Cada Actor tiene su propio contrato: compruébalo antes de configurarlo.

## Configuración

1. En Supabase, ejecuta `supabase/migrations/20261031000000_initial.sql` mediante el editor SQL o el flujo de migraciones de Supabase. Activa email/password en Auth y configura las URL de redirección. Si la confirmación de correo está habilitada, confirma la cuenta antes de iniciar sesión.
2. Copia `frontend/.env.example` a `frontend/.env.local` y configura la URL del proyecto y la clave **anon/publishable**. Son valores públicos diseñados para el navegador; nunca uses la clave service role.
3. Copia `backend/.env.example` a `backend/.env` y configura la misma URL y clave anon. Para búsquedas reales configura `APIFY_TOKEN`, `APIFY_ACTOR_ID` y, si corresponde, `APIFY_INPUT_QUERY_FIELD`. El token permanece en el servidor. Sin Actor y token, la búsqueda informa que la fuente no está configurada y no realiza scraping.
4. Instala y ejecuta ambos servicios:

```sh
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

En otra terminal:

```sh
cd frontend
npm install
npm run dev
```

Abre `http://localhost:3000`. El frontend reenvía `/api` al backend a través de `BACKEND_URL`; configura esa URL para tu despliegue. Protege la comunicación entre servicios en producción.

## Pruebas

```sh
cd backend && . .venv/bin/activate && pytest -q
cd frontend && npm run lint && npm run build
```

La API verifica el token del usuario con Supabase Auth antes de consultar fuentes. Los productos guardados pertenecen al usuario y están protegidos por políticas RLS. `app/sources.py` define el contrato de fuentes y el adaptador Apify; otros adaptadores pueden implementar `Source`. `app/ai.py` define el contrato para futuros proveedores de IA; no se realizan llamadas a modelos todavía. El adaptador Apify usa un mapeo genérico, por lo que puede requerir adaptación para el esquema de un Actor concreto. No hay persistencia de historial de búsquedas ni análisis automático de ofertas o tendencias en esta etapa.

## Búsquedas asíncronas con Apify

Aplica también `supabase/migrations/20261031000001_searches.sql` en el mismo proyecto. La API verifica cada token con Supabase Auth y usa una clave de servicio solo en el backend para persistir ejecuciones; las consultas del backend filtran por usuario y las políticas RLS permiten a cada usuario leer solo sus propios datos. Configura `SUPABASE_SERVICE_ROLE_KEY` únicamente en `backend/.env`: esta clave evita RLS y nunca debe exponerse al navegador. La clave anon del frontend es pública; no coloques el token de Apify en el navegador.

En `backend/.env`, configura `APIFY_TOKEN`, `APIFY_ACTOR_ID` con el identificador del Actor de Alibaba elegido (por ejemplo, `usuario/actor`; no hay uno predeterminado) y `APIFY_INPUT_QUERY_FIELD` con el nombre exacto del campo de consulta que acepta ese Actor. Revisa el coste y el contrato de entrada y salida del Actor antes de utilizarlo. Una búsqueda inicia una ejecución real y puede consumir créditos. Las pruebas usan `httpx.MockTransport` y no ejecutan Actors.

El backend registra ejecuciones en `search_runs`: `pending`, `processing`, `completed` o `failed`. El dashboard consulta periódicamente el estado; al completar, los resultados se guardan en `search_results`. La consulta del estado es la que importa los resultados: si se cierra el dashboard, una consulta posterior a `GET /searches/{id}` reanuda la importación. El dashboard deja de consultar tras seis minutos; el ID y estado permanecen en Supabase. No hay cola de trabajos ni recuperación automática de ejecuciones interrumpidas antes de guardar el ID del Actor. No se debe repetir una búsqueda automáticamente ante errores inciertos, ya que podría generar costes duplicados.

El adaptador reconoce nombres habituales (`title`/`name`/`productName`, `url`/`productUrl`, proveedor, precio numérico, moneda ISO y cantidad mínima). Los campos que falten o no puedan interpretarse quedan vacíos; los productos sin URL HTTP(S) se omiten. La deduplicación usa la URL de origen por búsqueda. Los formatos y entradas de los Actors de Alibaba varían: valida y ajusta el adaptador al Actor real antes de confiar en sus resultados. Actualmente se importan hasta 1.000 elementos por ejecución y no se interpretan rangos de precios ni monedas implícitas.
