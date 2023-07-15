import aiohttp
import asyncio
import discord_typings as dt
import logging
import platform
import random
import typing as t
import zlib

from ..http.auth import Auth
from ..http.client import HTTPClient
from ..internal.json import JSONArray, JSONObject, dump_json, load_json
from ..internal.ratelimit import TimePer
from ..utils.dispatcher import RawDispatcher
from . import errors

__all__ = ("Shard",)

_log = logging.getLogger(__name__)

ZLIB_SUFFIX = b'\x00\x00\xff\xff'

class Shard:
    def __init__(
        self, 
        auth: Auth, 
        http: HTTPClient, 
        *, 
        intents: int,
        identify_ratelimit: t.Optional[TimePer] = None,
        shard_id: int = 0,
        shard_count: int = 1,
        should_reconnect: bool = True,
    ):
        self._auth: Auth = auth
        self._http: HTTPClient = http
        self._ws: t.Optional[aiohttp.ClientWebSocketResponse] = None
        self._decompressor: t.Optional[zlib._Decompress] = None
        self._resume_url: t.Optional[str] = None
        self._ratelimiter: TimePer = TimePer(120, 60)
        self._identify_ratelimit: t.Optional[TimePer] = identify_ratelimit

        self._heartbeat_task: t.Optional[asyncio.Task[None]] = None
        self._heartbeat_ack_received: t.Optional[asyncio.Future[None]] = None
        self._connection_task: t.Optional[asyncio.Task[None]] = None

        self.op_dispatcher: RawDispatcher[int] = RawDispatcher(int)
        self.event_dispatcher: RawDispatcher[str] = RawDispatcher(str)

        self.shard_id: t.Final[int] = shard_id
        self.shard_count: t.Final[int] = shard_count
        self.should_reconnect: bool = should_reconnect
        self.intents: int = intents
        self.heartbeat_interval: float = 0.0
        self.sequence: t.Optional[int] = None
        self.session_id: t.Optional[str] = None

        self._load_listeners()

    def _load_listeners(self):
        self.op_dispatcher.add_listener(self._handle_dispatch, 0)
        self.op_dispatcher.add_listener(self._handle_reconnect, 7)
        self.op_dispatcher.add_listener(self._handle_invalid_session, 9)
        self.op_dispatcher.add_listener(self._handle_hello, 10)
        self.op_dispatcher.add_listener(self._handle_heartbeat_ack, 11)

    # gateway message handling

    async def send(self, payload: JSONArray | JSONObject):
        assert self._ws is not None, "We have not connected yet! Please connect via the connect method."

        async with self._ratelimiter:
            raw_payload = dump_json(payload)
            await self._ws.send_str(raw_payload)

            _log.debug('ID:%i Sent payload "%s" to the Gateway.', self.shard_id, raw_payload)

    def _process_raw_msg(self, msg: aiohttp.WSMessage):
        assert self._decompressor is not None, "The decompressor object has not been set!"

        if msg.type == aiohttp.WSMsgType.BINARY:
            contents = t.cast(bytes, msg.data)

            if len(contents) < 4 or contents[-4:] != ZLIB_SUFFIX:
                raise ValueError("Invalid zlib encoded message sent by the Gateway!")
            
            contents = self._decompressor.decompress(contents).decode()
        else:
            contents = t.cast(str, msg.data)

        json = load_json(contents)
        json = t.cast(dt.GatewayEvent, json)
        self.sequence = json.get("s")

        _log.debug("ID:%i Received payload '%r' from the Gateway.", self.shard_id, json)

        return json

    # gateway connection

    async def connect(self):
        self._decompressor = zlib.decompressobj()

        if self.session_id is not None and self._resume_url is not None:
            self._ws = await self._http.connect_gateway(url=self._resume_url)
            _log.info("ID:%i Reconnected to the Gateway with session %s.", self.shard_id, self.session_id)
        else:
            self._ws = await self._http.connect_gateway(encoding="json", compress="zlib-stream")
            _log.info("ID:%i Connected to the Gateway.", self.shard_id)

        await self.event_dispatcher.dispatch("connect", None)
        self._connection_task = asyncio.create_task(self._connection_loop())

    async def disconnect(self, *, keep_session: bool = False):
        assert self._ws is not None, "We have not connected yet!"

        if self._connection_task:
            self._connection_task.cancel()
            self._connection_task = None

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._heartbeat_ack_received:
            self._heartbeat_ack_received.cancel()
            self._heartbeat_ack_received = None

        if keep_session:
            _log.info("ID:%i Disconnected from the Gateway. The session has not been deleted.", self.shard_id)
            await self._ws.close(code=999)
        else:
            _log.info("ID:%i Disconnected from the Gateway. The session has been deleted.", self.shard_id)
            await self._ws.close()

            self._resume_url = None
            self.session_id = None
            self.sequence = None

        self._ws = None
        await self.event_dispatcher.dispatch("disconnect", None)

    async def _connection_loop(self):
        assert self._ws is not None, "We have not connected yet! Please connect via the connect method."

        async for msg in self._ws:
            processed = self._process_raw_msg(msg)
            await self.op_dispatcher.dispatch(int(processed["op"]), processed)

        _log.debug("ID:%i The Gateway has closed the connection on us. We have gotten close code %s.", self.shard_id, self._ws.close_code)

        code = self._ws.close_code
        if not code:
            return

        await self._handle_close_code(code)

    async def _heartbeat_loop(self):
        assert self._ws is not None, "We have not connected yet! Please connect via the connect method."

        loop = asyncio.get_running_loop()

        timeout = self.heartbeat_interval * random.random()
        await asyncio.sleep(timeout)

        while not self._ws.closed:
            payload = {"op": 1, "d": self.sequence}
            await self.send(payload)

            self._heartbeat_ack_received = loop.create_future()
            await self._heartbeat_ack_received

            await asyncio.sleep(self.heartbeat_interval)

    async def _handle_close_code(self, close_code: int):
        if close_code < 2000:
            _log.error("Possible Network Error (1xxx): Reconnecting.")
            await self.disconnect()
            await self.connect()
        elif close_code == 4000:
            _log.error("Unknown Error (4000): Reconnecting.")
            await self.disconnect(keep_session=True)
            await self.connect()
        elif close_code == 4001:
            # normally we can reconnect for this opcode, but it's better to stop because of the internal problem
            _log.error("Unknown Opcode (4001): This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
            await self.disconnect(keep_session=self.should_reconnect)
            if self.should_reconnect:
                await self.connect()
        elif close_code == 4002:
            _log.error("Decode Error (4002): This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
            await self.disconnect(keep_session=self.should_reconnect)
            if self.should_reconnect:
                await self.connect()
        elif close_code == 4003:
            _log.error("Not Authenticated (4003): A payload was sent to the gateway before identification. Reconnecting.")
            await self.disconnect()
            await self.connect()
        elif close_code == 4004:
            await self.disconnect()
            raise errors.AuthenticationError("4004: Invalid authentication was provided to the Gateway.")
        elif close_code == 4005:
            _log.error("Already Authenticated (4005): This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
            await self.disconnect(keep_session=self.should_reconnect)
            if self.should_reconnect:
                await self.connect()
        elif close_code == 4007:
            _log.error("Invalid Sequence (4007): Invalid sequence number was sent to the Gateway when resuming. Reconnecting.")
            await self.disconnect()
            await self.connect()
        elif close_code == 4008:
            _log.error("Ratelimited (4008): We have been ratelimited! Waiting for %f seconds, then reconnecting.", self._ratelimiter.per)
            await asyncio.sleep(self._ratelimiter.per)
            await self.disconnect(keep_session=True)
            await self.connect()
        elif close_code == 4009:
            _log.error("Session Timed Out (4009): The gateway session with Discord has timed out. Reconnecting.")
            await self.disconnect()
            await self.connect()
        elif close_code == 4010:
            await self.disconnect()
            raise errors.ShardingError("4010: An invalid shard was sent to Discord. This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
        elif close_code == 4011:
            await self.disconnect()
            raise errors.ShardingError("4011: Discord requires this bot to enable sharding. Please set the shard count.")
        elif close_code == 4012:
            await self.disconnect()
            raise errors.GatewayException("4012: This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
        elif close_code == 4013:
            await self.disconnect()
            raise errors.IntentError("4013: Invalid intents have been sent to Discord. Please double check your intents bit flag.")
        elif close_code == 4014:
            await self.disconnect()
            raise errors.IntentError("4014: The bot has requested for intents that it does not have access to. Please enable the needed intents via the Discord Developer Portal.")
        else:
            await self.disconnect()
            raise errors.GatewayException(f"Invalid close code: {close_code}.")

    # events

    async def _handle_dispatch(self, event: dt.DispatchEvent):
        name = event["t"]
        data = event["d"]

        _log.debug("ID:%i Received DISPATCH event from the Gateway with name %s.", self.shard_id, name)

        await self.event_dispatcher.dispatch(name, data)

        if name == "READY":
            self._resume_url = data["resume_gateway_url"]
            self.session_id = data["session_id"]

    async def _handle_reconnect(self, event: dt.ReconnectEvent):
        _log.debug("ID:%i Received RECONNECT event from the Gateway. We will reconnect and keep our session.", self.shard_id)

        await self.disconnect(keep_session=True)
        await self.connect()

    async def _handle_invalid_session(self, event: dt.InvalidSessionEvent):
        resume = event["d"]
        
        _log.debug("ID:%i Received INVALID_SESSION event from the Gateway.", self.shard_id)

        if self.should_reconnect:
            _log.debug(
                "ID:%i We will reconnect and " + ("keep" if resume else "delete") + " our session.",
                self.shard_id
            )

            await self.disconnect(keep_session=resume)
            await self.connect()
        else:
            await self.disconnect()

    async def _handle_hello(self, event: dt.HelloEvent):
        _log.debug("ID:%i Received HELLO event from the Gateway.", self.shard_id)

        self.heartbeat_interval = event["d"]["heartbeat_interval"] / 1000
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        if self.session_id is not None:
            _log.debug("ID:%i Gateway session %s will be resumed.", self.shard_id, self.session_id)
            await self.resume()
        else:
            if self._identify_ratelimit is not None:
                _log.debug("Shard %i will wait for the identify ratelimit.", self.shard_id)
                await self._identify_ratelimit.acquire()

            _log.debug("ID:%i Gateway session will begin.", self.shard_id)
            await self.identify()

    async def _handle_heartbeat_ack(self, event: dt.HeartbeatACKEvent):
        if not self._heartbeat_ack_received:
            return
        
        _log.debug("ID:%i Received HEARTBEAT_ACK event from the Gateway.", self.shard_id)

        self._heartbeat_ack_received.set_result(None)

    # payloads

    async def identify(self):
        payload = {
            "op": 2,
            "d": {
                "token": self._auth.header,
                "intents": self.intents,
                "shard": [self.shard_id, self.shard_count],
                "properties": {
                    "os": platform.system() or "Unknown",
                    "browser": "arke",
                    "device": "arke",
                },
            },
        }

        return await self.send(payload)
    
    async def resume(self):
        if self.session_id is None and self.sequence is None:
            raise RuntimeError("There is no session with the Gateway to resume.")

        payload = {
            "op": 6,
            "d": {
                "token": self._auth.header,
                "session_id": self.session_id,
                "seq": self.sequence,
            },
        }

        return await self.send(payload)
