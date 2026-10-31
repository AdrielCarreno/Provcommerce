from typing import Annotated
import logging
from uuid import UUID
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from .config import settings
from .sources import ApifySource, SourceError

app = FastAPI(title='Provcommerce API', version='0.2.0')
log = logging.getLogger('provcommerce.search')

async def current_user(authorization: Annotated[str | None, Header()] = None):
    config = settings()
    if not config.supabase_url or not config.supabase_anon_key: raise HTTPException(503, 'La autenticación no está configurada en el servidor.')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401, 'Se requiere una sesión válida.')
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f'{config.supabase_url.rstrip("/")}/auth/v1/user', headers={'Authorization': authorization, 'apikey': config.supabase_anon_key})
            if response.status_code in (401, 403): raise HTTPException(401, 'La sesión no es válida o ha caducado.')
            response.raise_for_status()
            user = response.json()
            if not user.get('id'): raise HTTPException(401, 'La sesión no es válida.')
            return {'id': user['id'], 'authorization': authorization}
    except httpx.HTTPError as exc: raise HTTPException(503, 'No se pudo verificar la sesión con Supabase.') from exc

class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    @field_validator('query')
    @classmethod
    def strip_query(cls, value):
        value = value.strip()
        if len(value) < 2: raise ValueError('La búsqueda debe tener al menos dos caracteres.')
        return value

async def db(method, table, user, *, params=None, payload=None, prefer=None):
    config = settings()
    if not config.supabase_service_role_key: raise HTTPException(503, 'Falta la clave de servicio de Supabase en el backend.')
    headers = {'Authorization': f'Bearer {config.supabase_service_role_key}', 'apikey': config.supabase_service_role_key}
    params = dict(params or {})
    if method in ('GET', 'PATCH', 'DELETE'): params['user_id'] = f'eq.{user["id"]}'
    if prefer: headers['Prefer'] = prefer
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f'{config.supabase_url.rstrip("/")}/rest/v1/{table}', headers=headers, params=params, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409: raise HTTPException(409, 'Ya existe una búsqueda activa para esta consulta.') from exc
        log.warning('Supabase operation failed: HTTP %s', exc.response.status_code)
        raise HTTPException(503, 'No se pudo acceder al almacenamiento de búsquedas.') from exc
    except (httpx.HTTPError, ValueError) as exc:
        log.warning('Supabase operation failed: %s', type(exc).__name__)
        raise HTTPException(503, 'No se pudo acceder al almacenamiento de búsquedas.') from exc

@app.get('/health')
async def health(): return {'status':'ok'}

@app.post('/searches', status_code=202)
async def create_search(body: SearchRequest, user: dict = Depends(current_user)):
    config = settings()
    if not config.apify_token or not config.apify_actor_id: raise HTTPException(503, 'Configura APIFY_TOKEN y APIFY_ACTOR_ID antes de buscar.')
    rows = await db('POST', 'search_runs', user, payload={'user_id':user['id'], 'query':body.query, 'status':'pending'}, prefer='return=representation')
    run = rows[0]
    try:
        actor_run = await ApifySource(config).start(body.query)
        await db('PATCH', 'search_runs', user, params={'id':f'eq.{run["id"]}'}, payload={'actor_run_id':actor_run, 'status':'processing'})
        run.update(actor_run_id=actor_run, status='processing')
        log.info('Search %s started', run['id'])
    except (httpx.HTTPError, SourceError, KeyError, ValueError):
        # An uncertain response can still mean the paid run started.
        log.warning('Search %s has an uncertain start; manual reconciliation required', run['id'])
        raise HTTPException(502, 'Inicio incierto. No repitas la búsqueda; revisa las ejecuciones en Apify.')
    return run

@app.get('/searches/{search_id}')
async def get_search(search_id: UUID, user: dict = Depends(current_user)):
    search_id = str(search_id)
    rows = await db('GET', 'search_runs', user, params={'id':f'eq.{search_id}', 'select':'*'})
    if not rows: raise HTTPException(404, 'Búsqueda no encontrada.')
    run = rows[0]
    run['results'] = await db('GET', 'search_results', user, params={'search_id':f'eq.{search_id}', 'select':'*'}) if run['status']=='completed' else []
    return run
