"""Apify adapter. Actor input and output vary by Actor; see README."""
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit, urlunsplit
import httpx
from pydantic import BaseModel
from .config import Settings

class Result(BaseModel):
    title: str
    url: str | None = None
    description: str | None = None
    source: str = 'Apify'
    supplier: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    minimum_order: str | None = None

class SourceError(Exception):
    pass

def clean_url(value):
    if not isinstance(value, str): return None
    try:
        p = urlsplit(value.strip())
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password: return None
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ''))
    except ValueError: return None

def normalize(items):
    results, seen = [], set()
    for item in items:
        if not isinstance(item, dict): continue
        title = item.get('title') or item.get('name') or item.get('productName')
        if not isinstance(title, str) or not title.strip(): continue
        url = clean_url(item.get('url') or item.get('productUrl') or item.get('product_url'))
        # Without a source URL, identity cannot be reliably established: omit it.
        if not url or url in seen: continue
        seen.add(url)
        supplier = item.get('supplier') or item.get('supplierName') or item.get('companyName')
        if isinstance(supplier, dict): supplier = supplier.get('name')
        price = item.get('price')
        if isinstance(price, dict): price = price.get('amount')
        try:
            price = Decimal(str(price)) if price is not None and not isinstance(price, bool) else None
            if price is not None and (not price.is_finite() or price < 0): price = None
        except InvalidOperation: price = None
        currency = item.get('currency') or item.get('currencyCode')
        currency = currency.upper() if isinstance(currency, str) and re.fullmatch(r'[A-Za-z]{3}', currency) else None
        minimum = item.get('minimumOrderQuantity') or item.get('minOrderQuantity') or item.get('moq')
        results.append(Result(title=title.strip()[:500], url=url, description=item.get('description') if isinstance(item.get('description'), str) else None, supplier=supplier if isinstance(supplier, str) else None, price=price, currency=currency, minimum_order=str(minimum) if isinstance(minimum, (str, int, float)) and not isinstance(minimum, bool) else None))
    return results

class ApifySource:
    def __init__(self, config: Settings): self.config = config
    def _headers(self):
        if not self.config.apify_token or not self.config.apify_actor_id:
            raise SourceError('Configura APIFY_TOKEN y APIFY_ACTOR_ID antes de buscar.')
        return {'Authorization': f'Bearer {self.config.apify_token}'}
    async def start(self, query):
        actor = quote(self.config.apify_actor_id.replace('/', '~'), safe='~')
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f'https://api.apify.com/v2/acts/{actor}/runs', headers=self._headers(), json={self.config.apify_input_query_field: query})
            response.raise_for_status()
            data = response.json()['data']
            return data['id']
    async def status(self, run_id):
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f'https://api.apify.com/v2/actor-runs/{quote(run_id, safe="")}', headers=self._headers())
            response.raise_for_status()
            data = response.json()['data']
            if data['status'] != 'SUCCEEDED': return data['status'], []
            dataset = data.get('defaultDatasetId')
            if not dataset: raise SourceError('La ejecución no proporcionó un dataset.')
            response = await client.get(f'https://api.apify.com/v2/datasets/{quote(dataset, safe="")}/items', headers=self._headers(), params={'limit': 1000, 'clean': 'true'})
            response.raise_for_status()
            items = response.json()
            if not isinstance(items, list): raise SourceError('Formato de dataset inválido.')
            return 'SUCCEEDED', normalize(items)
