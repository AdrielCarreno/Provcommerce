from typing import Protocol

class AIProvider(Protocol):
    async def summarize(self, text: str) -> str: ...

class DisabledAI:
    async def summarize(self, text: str) -> str:
        raise NotImplementedError('No hay un proveedor de IA configurado.')
