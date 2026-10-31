"""Run as a separate long-lived process; safely resumes processing after restarts."""
import asyncio
import logging
import httpx
from .config import settings
from .main import db
from .sources import ApifySource

log = logging.getLogger('provcommerce.worker')

async def process(run):
    user = {'id': run['user_id']}
    status, results = await ApifySource(settings()).status(run['actor_run_id'])
    if status == 'SUCCEEDED':
        if results:
            await db('POST', 'search_results', user, params={'on_conflict':'search_id,url'}, payload=[dict(r.model_dump(mode='json'), search_id=run['id'], user_id=user['id']) for r in results], prefer='resolution=ignore-duplicates,return=minimal')
        await db('PATCH','search_runs',user,params={'id':f'eq.{run["id"]}','status':'eq.processing'},payload={'status':'completed'})
    elif status in ('READY', 'RUNNING', 'ABORTING', 'TIMING-OUT'):
        # Refresh ordering so a large queue does not starve newer runs.
        await db('PATCH','search_runs',user,params={'id':f'eq.{run["id"]}','status':'eq.processing'},payload={'worker_failures':0})
    elif status in ('FAILED','ABORTED','TIMED-OUT'):
        await db('PATCH','search_runs',user,params={'id':f'eq.{run["id"]}','status':'eq.processing'},payload={'status':'failed','error':'La ejecución de Apify terminó sin éxito.'})
    else:
        raise ValueError('Estado de Apify desconocido')

async def tick():
    config = settings()
    if not config.supabase_url or not config.supabase_service_role_key: raise RuntimeError('Falta configuración de Supabase en el worker.')
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f'{config.supabase_url.rstrip("/")}/rest/v1/search_runs', headers={'apikey':config.supabase_service_role_key,'Authorization':f'Bearer {config.supabase_service_role_key}'}, params={'status':'eq.processing','worker_failures':'lt.3','actor_run_id':'not.is.null','select':'id,user_id,actor_run_id,worker_failures','limit':'100','order':'updated_at.asc'})
        response.raise_for_status()
        runs = response.json()
    for run in runs:
        try: await process(run)
        except Exception as exc:
            # Retry on the next tick; never log credentials or remote response bodies.
            log.warning('Search %s could not be processed: %s', run['id'], type(exc).__name__)
            failures = run['worker_failures'] + 1
            update = {'worker_failures': failures}
            if failures >= 3: update['error'] = 'No se pudo consultar la ejecución; revisa Apify antes de reintentar.'
            try:
                await db('PATCH', 'search_runs', {'id':run['user_id']}, params={'id':f'eq.{run["id"]}', 'status':'eq.processing'}, payload=update)
            except Exception as update_error:
                log.warning('Could not record worker failure: %s', type(update_error).__name__)

async def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try: await tick()
        except Exception as exc: log.warning('Worker iteration failed: %s', type(exc).__name__)
        await asyncio.sleep(max(5, settings().worker_poll_seconds))

if __name__ == '__main__': asyncio.run(main())
