"""BasePlugin: the interface every plugin must implement.

Per-exchange hooks receive a `HookContext` (ADR-0012). Plugins that
don't need contextual data may ignore the parameter; the framework
constructs and passes it unconditionally so the contract is uniform.

`on_init` and `on_shutdown` are lifecycle hooks tied to the host's
own lifecycle (not a specific exchange) and do not receive `ctx`.
"""

from .egress import EgressClient
from .hook_context import HookContext
from .hooks import Abort, Block, Pass, Transform


class BasePlugin:
    name: str = "unnamed"

    # Populated by the host at plugin load time (ADR-0015). Background
    # tasks should hold this reference; in-hook code may equivalently
    # use `ctx.egress` (same instance). `None` only when the host did
    # not wire an httpx client (test harness, or a host built without
    # `http_client=`).
    egress: EgressClient | None = None

    async def on_init(self) -> None:
        pass

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        return Pass()

    async def before_forward(self, exchange_id: str, ctx: HookContext) -> Pass | Block | Transform:
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str, ctx: HookContext) -> Pass | Abort:
        return Pass()

    async def on_response_chunk(
        self, exchange_id: str, chunk: bytes, ctx: HookContext
    ) -> Pass | Abort:
        return Pass()

    async def on_response_complete(self, exchange_id: str, ctx: HookContext) -> None:
        pass

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass
