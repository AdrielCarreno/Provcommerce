"""HTTP integration against simulated Supabase and Apify; no external calls."""
import asyncio
import json
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import app
import app.main as api
import app.worker as worker


def test_full_search_worker_and_isolation(monkeypatch):
    user_a, user_b, search_id = map(str, (uuid4(), uuid4(), uuid4()))
    config = Settings(supabase_url='https://supabase.test', supabase_anon_key='anon-test', supabase_service_role_key='service-test', apify_token='apify-test', apify_actor_id='vendor/actor')
    monkeypatch.setattr(api, 'settings', lambda: config)
    monkeypatch.setattr(worker, 'settings', lambda: config)
    state = {'run': None, 'results': [], 'starts': 0}
    def server(request):
        path = request.url.path
        if path == '/auth/v1/user':
            token = request.headers.get('authorization')
            if token == 'Bearer user-a': return httpx.Response(200, json={'id': user_a})
            if token == 'Bearer user-b': return httpx.Response(200, json={'id': user_b})
            return httpx.Response(401)
        if path.startswith('/rest/v1/'):
            assert request.headers['authorization'] == 'Bearer service-test'
            table = path.rsplit('/', 1)[-1]
            body = json.loads(request.content) if request.content else None
            if table == 'search_runs' and request.method == 'POST':
                if state['run'] and state['run']['status'] in ('pending', 'processing'): return httpx.Response(409, json={'code': '23505'})
                state['run'] = {'id': search_id, **body, 'actor_run_id': None, 'worker_failures': 0}
                return httpx.Response(201, json=[state['run']])
            if table == 'search_runs' and request.method == 'PATCH':
                assert request.url.params['user_id'] == f'eq.{user_a}'
                state['run'].update(body)
                return httpx.Response(204)
            if table == 'search_runs' and request.method == 'GET':
                if 'user_id' in request.url.params: return httpx.Response(200, json=[state['run']] if request.url.params['user_id'] == f'eq.{user_a}' else [])
                return httpx.Response(200, json=[state['run']])
            if table == 'search_results' and request.method == 'POST':
                state['results'] = body
                return httpx.Response(201)
            if table == 'search_results' and request.method == 'GET':
                assert request.url.params['user_id'] == f'eq.{user_a}'
                return httpx.Response(200, json=state['results'])
        if request.url.host == 'api.apify.com':
            assert request.headers['authorization'] == 'Bearer apify-test'
            if path.endswith('/runs'):
                state['starts'] += 1
                assert request.url.params['timeout'] == '120'
                return httpx.Response(201, json={'data': {'id': 'run-test'}})
            if '/actor-runs/' in path: return httpx.Response(200, json={'data': {'status':'SUCCEEDED','defaultDatasetId':'dataset-test'}})
            if '/datasets/' in path: return httpx.Response(200, json=[{'name':'Prueba','url':'https://example.test/product','price':'1.50'}, {'name':'Duplicado','url':'https://example.test/product'}])
        raise AssertionError(f'unexpected request {request.method} {request.url}')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(server), **kwargs))
    with TestClient(app) as client:
        response = client.post('/searches', headers={'Authorization':'Bearer user-a'}, json={'query':'café'})
        assert response.status_code == 202 and response.json()['status'] == 'processing'
        assert client.post('/searches', headers={'Authorization':'Bearer user-a'}, json={'query':'otro'}).status_code == 409
        assert state['starts'] == 1
        assert client.get(f'/searches/{search_id}', headers={'Authorization':'Bearer user-b'}).status_code == 404
        asyncio.run(worker.tick())
        result = client.get(f'/searches/{search_id}', headers={'Authorization':'Bearer user-a'}).json()
        assert result['status'] == 'completed' and len(result['results']) == 1
        assert result['results'][0]['price'] == '1.50' and result['results'][0]['user_id'] == user_a


def test_uncertain_start_is_not_retried(monkeypatch):
    config = Settings(supabase_url='https://supabase.test', supabase_anon_key='anon', supabase_service_role_key='service', apify_token='token', apify_actor_id='owner/actor')
    monkeypatch.setattr(api, 'settings', lambda: config)
    user, run = str(uuid4()), str(uuid4())
    calls = []
    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user': return httpx.Response(200,json={'id': user})
        if request.url.path == '/rest/v1/search_runs': return httpx.Response(201,json=[{'id':run,'user_id':user,'status':'pending'}])
        raise httpx.ReadTimeout('uncertain', request=request)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(server), **kwargs))
    with TestClient(app) as client:
        response = client.post('/searches', headers={'Authorization':'Bearer user'}, json={'query':'bolsa'})
    assert response.status_code == 502 and 'No repitas' in response.json()['detail']
    assert len([request for request in calls if request.url.host == 'api.apify.com']) == 1
    assert not any(request.method == 'PATCH' for request in calls)
