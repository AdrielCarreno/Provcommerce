import asyncio
import httpx
from fastapi.testclient import TestClient
from app.main import app, current_user
from app.sources import ApifySource, normalize
from app.config import Settings

client = TestClient(app)

def test_normalization_deduplicates_and_never_guesses():
    rows = normalize([{'productName':'Bolsa','productUrl':'https://example.com/p#one','supplierName':'Proveedor','price':'12.50','currency':'usd','moq':100}, {'title':'Duplicado','url':'https://example.com/p#two'}, {'title':'Sin URL'}, {'title':'Inválido','url':'javascript:alert(1)'}, {'title':'Sin precio','url':'https://example.com/2','price':'$12-15'}])
    assert len(rows)==2
    assert str(rows[0].price)=='12.50' and rows[0].currency=='USD' and rows[0].minimum_order=='100'
    assert rows[0].supplier=='Proveedor'
    assert rows[1].price is None and rows[1].currency is None

def test_health_and_validation():
    assert client.get('/health').json()=={'status':'ok'}
    app.dependency_overrides[current_user] = lambda: {'id':'u','authorization':'Bearer test'}
    try: assert client.post('/searches',json={'query':'  '}).status_code==422
    finally: app.dependency_overrides.clear()

def test_apify_async_requests_mocked(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/runs'): return httpx.Response(201,json={'data':{'id':'run123'}})
        if '/actor-runs/' in request.url.path: return httpx.Response(200,json={'data':{'status':'SUCCEEDED','defaultDatasetId':'dataset'}})
        return httpx.Response(200,json=[{'title':'Ejemplo de prueba','url':'https://example.com/1'}])
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    async def run():
        source=ApifySource(Settings(apify_token='test-token',apify_actor_id='vendor/actor',apify_input_query_field='keyword'))
        assert await source.start('cafe')=='run123'
        status,results=await source.status('run123')
        assert status=='SUCCEEDED' and results[0].title=='Ejemplo de prueba'
    asyncio.run(run())
    assert calls[0].content == b'{"keyword":"cafe"}'
    assert calls[0].headers['authorization']=='Bearer test-token'

def test_worker_imports_and_handles_failure(monkeypatch):
    import app.worker as worker
    records=[]
    async def fake_db(method, table, user, **kw):
        records.append((method,table,user,kw))
    async def success(self, run_id):
        return 'SUCCEEDED', normalize([{'title':'Producto de prueba','url':'https://example.com/p'}])
    monkeypatch.setattr(worker, 'db', fake_db)
    monkeypatch.setattr(ApifySource, 'status', success)
    run={'id':'search1','user_id':'user1','actor_run_id':'run1'}
    asyncio.run(worker.process(run))
    assert records[0][1]=='search_results' and records[0][2]['id']=='user1'
    assert records[1][3]['payload']['status']=='completed'
    async def failure(self, run_id): return 'FAILED', []
    monkeypatch.setattr(ApifySource, 'status', failure)
    asyncio.run(worker.process(run))
    assert records[-1][3]['payload']['status']=='failed'

def test_auth_rejects_invalid_session(monkeypatch):
    import app.main as api
    monkeypatch.setattr(api, 'settings', lambda: Settings(supabase_url='https://example.com',supabase_anon_key='anon'))
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(401)), **kwargs))
    assert client.get('/searches/00000000-0000-0000-0000-000000000001',headers={'Authorization':'Bearer invalid'}).status_code==401
    assert client.get('/searches/00000000-0000-0000-0000-000000000001').status_code==401

def test_get_search_cannot_read_another_user(monkeypatch):
    import app.main as api
    async def fake_db(method, table, user, **kwargs):
        assert user['id']=='user1'
        return []
    monkeypatch.setattr(api,'db',fake_db)
    app.dependency_overrides[current_user]=lambda:{'id':'user1','authorization':'Bearer test'}
    try: assert client.get('/searches/00000000-0000-0000-0000-000000000001').status_code==404
    finally: app.dependency_overrides.clear()
