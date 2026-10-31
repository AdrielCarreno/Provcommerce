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

El backend registra `pending`, `processing`, `completed` y `failed`. El worker independiente consulta Apify e importa resultados aunque se cierre el navegador; el endpoint GET solo lee el estado. Arráncalo en otra terminal desde `backend` con `. .venv/bin/activate && python -m app.worker` y mantenlo activo en despliegue. Importar resultados es idempotente por búsqueda y URL. El worker intenta consultas HTTP hasta tres veces con esperas crecientes y marca la búsqueda fallida después de tres iteraciones con errores; si falla la base de datos al registrar el fallo, reintentará al recuperar la conexión. Una ejecución en curso se recupera tras reiniciar el worker.

Una consulta idéntica del mismo usuario no puede iniciarse mientras esté pendiente o procesándose. El inicio de un Actor nunca se reintenta automáticamente: si falla la conexión en ese instante, el estado queda pendiente y requiere conciliación manual en Apify antes de liberar la reserva. El timeout de Actor se configura con `APIFY_TIMEOUT_SECS` (10–300 segundos); `APIFY_MAX_ITEMS` limita la importación (1–1000), no el trabajo ni el coste del Actor. Configura además en el Actor sus propios límites de resultados y presupuesto; el campo genérico de búsqueda no garantiza esos límites. El worker procesa hasta 100 ejecuciones por ciclo y no sustituye una cola durable con leases.

El mapeo actual es **provisional**: reconoce nombres habituales y omite productos sin URL HTTP(S). No interpreta rangos de precios ni monedas implícitas. Antes de usar datos reales, selecciona un Actor de Alibaba y comprueba su documentación y ejemplos públicos de entrada y salida, su precio, límites, unidades, moneda y derechos de uso; adapta y prueba el mapeo contra ese esquema. No se ha seleccionado ni comprobado un Actor específico.

## Configuración segura de Supabase y migraciones

1. Crea un proyecto de prueba independiente en Supabase; en Auth habilita correo/contraseña y añade la URL local de redirección. Si está activada la confirmación de correo, confirma la cuenta.
2. Copia la URL del proyecto y la clave pública anon/publishable desde los ajustes de API. Ponlas en `frontend/.env.local` como `NEXT_PUBLIC_SUPABASE_URL` y `NEXT_PUBLIC_SUPABASE_ANON_KEY`, y en `backend/.env` como `SUPABASE_URL` y `SUPABASE_ANON_KEY`.
3. Copia la clave `service_role` exclusivamente a `SUPABASE_SERVICE_ROLE_KEY` en `backend/.env`; también la necesita el worker. Nunca la incluyas en variables `NEXT_PUBLIC_`, archivos versionados ni registros. Restringe acceso al proceso y rota la clave si se expone.
4. Usa el historial de migraciones de Supabase CLI y aplica, en orden, los tres archivos de `supabase/migrations` a un proyecto de prueba. Las dos migraciones iniciales son versionadas y no deben ejecutarse otra vez manualmente sobre tablas existentes. La tercera usa `IF NOT EXISTS`; antes de aplicarla, comprueba y resuelve manualmente duplicados activos con `select user_id, lower(btrim(query)), count(*) from public.search_runs where status in ('pending','processing') group by 1,2 having count(*) > 1;`. Haz copia y revisa cambios antes de cualquier despliegue; no se aplicaron aquí.
5. Verifica con dos usuarios de prueba que cada uno solo pueda leer sus propios guardados, búsquedas y resultados y que no pueda escribir directamente en las tablas de búsqueda. La API verifica tokens mediante `/auth/v1/user` de Supabase y filtra cada acceso con service role por el ID validado. Prueba también sesiones caducadas.

## Procedimiento de prueba real de bajo coste

Solo con autorización expresa: usa un proyecto de prueba, el Actor verificado y un token de prueba de acceso limitado; establece presupuesto máximo en Apify, timeout corto y el límite de resultados específico del Actor. Arranca API, frontend y worker; inicia sesión con un usuario de prueba, realiza una sola búsqueda y anota el ID. Comprueba estados, registro de ejecución en Apify, resultados y sus URLs, y persistencia tras cerrar el navegador. Confirma aislamiento con otro usuario, coste efectivo y que no haya ejecuciones duplicadas. Ante un inicio incierto, consulta Apify antes de repetir; concilia manualmente la fila pendiente. No se ha ejecutado este procedimiento aquí.
