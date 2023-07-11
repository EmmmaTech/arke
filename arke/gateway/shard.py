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
        should_reconnect: bool = True,
    ):
        self._auth: Auth = auth
        self._http: HTTPClient = http
        self._ws: t.Optional[aiohttp.ClientWebSocketResponse] = None
        self._decompressor: t.Optional[zlib._Decompress] = None
        self._resume_url: t.Optional[str] = None

        self._heartbeat_task: t.Optional[asyncio.Task[None]] = None
        self._heartbeat_ack_received: t.Optional[asyncio.Future[None]] = None
        self._connection_task: t.Optional[asyncio.Task[None]] = None

        self.op_dispatcher: RawDispatcher[int] = RawDispatcher(int)
        self.event_dispatcher: RawDispatcher[str] = RawDispatcher(str)

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

        raw_payload = dump_json(payload)
        await self._ws.send_str(raw_payload)

        _log.debug('Sent payload "%s" to the Gateway.', raw_payload)

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

        _log.debug("Received payload '%r' from the Gateway.", json)

        return json

    # gateway connection

    async def connect(self):
        self._decompressor = zlib.decompressobj()

        if self.session_id is not None and self._resume_url is not None:
            self._ws = await self._http.connect_gateway(url=self._resume_url)
            _log.info("Reconnected to the Gateway with session %s.", self.session_id)
        else:
            _log.info("Connected to the Gateway.")
            self._ws = await self._http.connect_gateway(encoding="json", compress="zlib-stream")

        self.event_dispatcher.dispatch("connect", None)
        self._connection_task = asyncio.create_task(self._connection_loop())

    async def disconnect(self, *, keep_session: bool = False):
        assert self._ws is not None, "We have not connected yet!"

        if self._connection_task:
            self._connection_task.cancel()
            await self._connection_task
            self._connection_task = None

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await self._heartbeat_task
            self._heartbeat_task = None

        if self._heartbeat_ack_received:
            self._heartbeat_ack_received.cancel()
            self._heartbeat_ack_received = None

        if keep_session:
            _log.info("Disconnected from the Gateway. The session has not been deleted.")
            await self._ws.close(code=999)
        else:
            _log.info("Disconnected from the Gateway. The session has been deleted.")
            await self._ws.close()

            self._resume_url = None
            self.session_id = None
            self.sequence = None

        self._ws = None
        self.event_dispatcher.dispatch("disconnect", None)

    async def _connection_loop(self):
        assert self._ws is not None, "We have not connected yet! Please connect via the connect method."

        async for msg in self._ws:
            if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                processed = self._process_raw_msg(msg)
                self.op_dispatcher.dispatch(processed["op"], processed)

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
        if close_code == 4000:
            _log.error("Unknown Error (4000): Reconnecting.")
            await self.disconnect(keep_session=True)
            await self.connect()
        elif close_code == 4001:
            # normally we can reconnect for this opcode, but it's better to stop because of the internal problem
            _log.error("Unknown Opcode (4001): This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
            await self.disconnect()
            if self.should_reconnect:
                await self.connect()
        elif close_code == 4002:
            _log.error("Decode Error (4002): This is an internal error with arke.gateway. Please open an issue on the GitHub repo.")
            await self.disconnect()
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
            await self.disconnect()
            if self.should_reconnect:
                await self.connect()
        elif close_code == 4007:
            _log.error("Invalid Sequence (4007): Invalid sequence number was sent to the Gateway when resuming. Reconnecting.")
            await self.disconnect()
            await self.connect()
        elif close_code == 4008:
            # TODO: handle when ratelimiting is handled
            pass
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

        _log.debug("Received DISPATCH event from the Gateway with name %s and data %r.", name, data)

        self.event_dispatcher.dispatch(name, data)

        if name == "READY":
            self._resume_url = data["resume_gateway_url"]
            self.session_id = data["session_id"]

    async def _handle_reconnect(self, event: dict[t.Any, t.Any]):
        _log.debug("Received RECONNECT event from the Gateway. We will reconnect and keep our session.")

        await self.disconnect(keep_session=True)
        await self.connect()

    async def _handle_invalid_session(self, event: dt.InvalidSessionEvent):
        resume = event["d"]
        
        _log.debug("Received INVALID_SESSION event from the Gateway.")

        if self.should_reconnect:
            _log.debug(
                "We will reconnect and " "keep" if resume else "delete" " our session."
            )

            await self.disconnect(keep_session=resume)
            await self.connect()
        else:
            await self.disconnect()

    async def _handle_hello(self, event: dt.HelloEvent):
        _log.debug("Received HELLO event from the Gateway.")

        self.heartbeat_interval = event["d"]["heartbeat_interval"] / 1000
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        if self.session_id is not None:
            _log.debug("Gateway session %s will be resumed.", self.session_id)
            await self.resume()
        else:
            _log.debug("Gateway session will begin.")
            await self.identify()

    async def _handle_heartbeat_ack(self, event: dt.HeartbeatACKEvent):
        if not self._heartbeat_ack_received:
            return
        
        _log.debug("Received HEARTBEAT_ACK event from the Gateway.")

        self._heartbeat_ack_received.set_result(None)

    # payloads

    async def identify(self):
        payload = {
            "op": 2,
            "d": {
                "token": self._auth.header,
                "intents": self.intents,
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
