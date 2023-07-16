# SPDX-License-Identifier: MIT

import asyncio
import logging
import typing as t

import discord_typings as dt

from ..http.auth import Auth
from ..http.client import HTTPClient
from ..http.errors import HTTPException
from ..http.route import Route
from ..internal.ratelimit import TimePer
from ..utils.dispatcher import RawDispatcher
from .errors import GatewayException
from .shard import Shard

__all__ = ("Manager",)

_log = logging.getLogger(__name__)


class Manager:
    def __init__(
        self,
        auth: Auth,
        http: HTTPClient,
        *,
        intents: int,
        shards: t.Optional[list[int]] = None,
        should_reconnect: bool = True,
    ):
        self._auth: Auth = auth
        self._http: HTTPClient = http
        self._max_concurrency: t.Optional[int] = None
        self._identify_ratelimits: dict[int, TimePer] = {}
        self._pending_shard_count: t.Optional[int] = None

        self.intents: int = intents
        self.shards: list[int] = shards or []
        self.should_reconnect: bool = should_reconnect
        self.op_dispatcher: RawDispatcher[int] = RawDispatcher(int)
        self.event_dispatcher: RawDispatcher[str] = RawDispatcher(str)

        self.current_shards: list[Shard] = []
        self.pending_shards: list[Shard] = []

    def _create_shard(self, current_id: int, *, lazy_connect: bool = True):
        assert (
            self._max_concurrency is not None
        ), "max_concurrency has not been set, please start via the start method."

        ratelimit_key = current_id % self._max_concurrency

        if (ratelimit := self._identify_ratelimits.get(ratelimit_key)) is None:
            ratelimit = TimePer(self._max_concurrency, 5)
            self._identify_ratelimits[ratelimit_key] = ratelimit

        shard = Shard(
            self._auth,
            self._http,
            intents=self.intents,
            identify_ratelimit=ratelimit,
            shard_id=current_id,
            shard_count=len(self.shards),
            should_reconnect=self.should_reconnect,
        )

        shard.event_dispatcher.add_event_handler(self._on_shard_event_receive)
        shard.op_dispatcher.add_event_handler(self._on_shard_op_receive)

        if lazy_connect:
            asyncio.create_task(shard.connect())

        return shard

    async def _on_shard_op_receive(self, event: dt.GatewayEvent, op: int):
        _log.debug("Relaying opcode %i to global op dispatcher.", op)
        await self.op_dispatcher.dispatch(op, event)

    async def _on_shard_event_receive(self, event: dt.GatewayEvent, name: str):
        _log.debug("Relaying event %s to global event dispatcher.", name)
        await self.event_dispatcher.dispatch(name, event)

    async def start(self):
        connection_info: dt.GetGatewayBotData
        try:
            connection_info = await self._http.request(Route("GET", "/gateway/bot"))
        except HTTPException:
            _log.exception(
                "Failed to retrieve Gateway connection information, check your connection."
            )
            return

        session_start = connection_info["session_start_limit"]
        self._max_concurrency = session_start["max_concurrency"]
        remaining = session_start["remaining"]
        total = session_start["total"]

        if not self.shards:
            self.shards = list(range(connection_info["shards"]))

        if remaining == 0:
            raise GatewayException("We have run out of remaining sessions for today.")

        _log.debug(
            "Shard manager is starting, %i sessions left out of %i for today.",
            remaining,
            total,
        )
        _log.debug("Shard manager will start %i shards.", len(self.shards))

        self.current_shards = [self._create_shard(id) for id in self.shards]

    async def close(self):
        for shard in self.current_shards:
            await shard.disconnect()
        for shard in self.pending_shards:
            await shard.disconnect()

        self.current_shards.clear()
        self.pending_shards.clear()

    async def rescale(self, count: int):
        if self._pending_shard_count is not None:
            raise RuntimeError("Shards are currently rescaling.")
        if self._max_concurrency is None:
            raise RuntimeError("You need to start the manager via Manager.start.")

        self._pending_shard_count = count
        self.pending_shards.clear()

        shard_ids = list(range(count))
        shard_connects = []

        for id in shard_ids:
            shard = self._create_shard(id, lazy_connect=False)

            shard_connects.append(shard.connect())
            self.pending_shards.append(shard)

        try:
            await asyncio.gather(*shard_connects)
        finally:
            _log.debug("Shard rescaling was cancelled! Cleaning up.")

            await asyncio.gather(*[s.disconnect() for s in self.pending_shards])

            self._pending_shard_count = None
            self.pending_shards.clear()

        _log.debug("New shards have been created. We will close and replace old shards.")

        await asyncio.gather(*[s.disconnect() for s in self.current_shards])

        self.current_shards.clear()
        self.current_shards = self.pending_shards

        self._pending_shard_count = None
        self.pending_shards = []
