from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    supabase_url: str = ''
    supabase_anon_key: str = ''
    supabase_service_role_key: str = ''
    apify_token: str = ''
    apify_actor_id: str = ''
    apify_input_query_field: str = 'query'
    ai_provider: str = 'disabled'

@lru_cache
def settings():
    return Settings()
