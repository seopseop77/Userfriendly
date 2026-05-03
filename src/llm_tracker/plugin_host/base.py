"""BasePlugin: the interface every plugin must implement."""

from .hooks import Abort, Block, Pass, Transform


class BasePlugin:
    name: str = "unnamed"

    async def on_init(self) -> None:
        pass

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str) -> Pass | Abort:
        return Pass()

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        return Pass()

    async def on_response_complete(self, exchange_id: str) -> None:
        pass

    async def on_persisted(self, exchange_id: str) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass
