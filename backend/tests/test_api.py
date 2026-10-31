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

def test_search_run_completed_and_failed(monkeypatch):
    import app.main as api
    records=[]
    async def fake_db(method, table, user, **kw):
        records.append((method,table,kw))
        if method=='GET' and table=='search_runs': return [{'id':'search1','status':'processing','actor_run_id':'run1'}]
        if method=='GET': return [{'title':'Producto de prueba','url':'https://example.com/p','source':'Apify'}]
        return None
    async def success(self, run_id):
        return 'SUCCEEDED', normalize([{'title':'Producto de prueba','url':'https://example.com/p'}])
    monkeypatch.setattr(api, 'db', fake_db)
    monkeypatch.setattr(ApifySource, 'status', success)
    app.dependency_overrides[current_user]=lambda:{'id':'user1','authorization':'Bearer test'}
    try:
        response=client.get('/searches/search1')
        assert response.status_code==200 and response.json()['status']=='completed'
        assert response.json()['results'][0]['title']=='Producto de prueba'
        assert any(table=='search_results' and method=='POST' for method,table,_ in records)
        async def failure(self, run_id): return 'FAILED', []
        monkeypatch.setattr(ApifySource, 'status', failure)
        response=client.get('/searches/search1')
        assert response.json()['status']=='failed'
    finally: app.dependency_overrides.clear()
