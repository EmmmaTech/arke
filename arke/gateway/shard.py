import aiohttp
import asyncio
import datetime
import random
import typing as t
import zlib

from ..http.client import HTTPClient
from ..internal.json import JSONArray, JSONObject, dump_json, load_json

__all__ = ("Shard",)

ZLIB_SUFFIX = b'\x00\x00\xff\xff'

def _decompress_msg(msg: bytes, decompressor: zlib._Decompress):
    if len(msg) < 4 or msg[-4:] != ZLIB_SUFFIX:
        return ""
    
    deflated = decompressor.decompress(msg)
    return deflated.decode()

class Shard:
    def __init__(self, http: HTTPClient, *, timeout: float = 30.0):
        self._http: HTTPClient = http
        self._ws: t.Optional[aiohttp.ClientWebSocketResponse] = None
        self._decompressor: zlib._Decompress = zlib.decompressobj()
        self._last_heartbeat_ack: t.Optional[datetime.datetime] = None 
        self._heartbeat_task: t.Optional[asyncio.Task[None]] = None
        self._connection_task: t.Optional[asyncio.Task[None]] = None

        self.timeout: float = timeout
        self.heartbeat_interval: float = 0.0
        self.sequence: t.Optional[int] = None

    async def send(self, payload: JSONArray | JSONObject):
        raw_payload = dump_json(payload)
        await self._ws.send_str(raw_payload)

    async def receive(self):
        try:
            msg = await self._ws.receive(self.timeout)
        except asyncio.CancelledError:
            return

        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            return await self.disconnect()

        # TODO: cast the message into a properly typed ws msg class
        if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
            if msg.type == aiohttp.WSMsgType.BINARY:
                contents = t.cast(bytes, msg.data)
                contents = _decompress_msg(contents, self._decompressor)
            else:
                contents = t.cast(str, msg.data)

            json = load_json(contents)
            self.sequence = json.get("s")

            return json

    async def _connect(self):
        self._ws = await self._http.connect_gateway(encoding="json", compress="zlib-stream")

        hello = await self.receive()
        if hello and isinstance(hello, dict):
            self.heartbeat_interval = hello["heartbeat_interval"] / 1000

        await self.identify()
        self._heartbeat_task = await asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self, *, code: int = 1000):
        if not self._ws:
            return

        if self._connection_task:
            self._connection_task.cancel()
            await self._connection_task

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await self._heartbeat_task

        await self._ws.close(code=code)

    async def _heartbeat_loop(self):
        timeout = self.heartbeat_interval * random.random()

        while not self._ws.closed:
            await asyncio.sleep(timeout)

            payload = {"op": 1, "d": self.sequence}
            await self.send(payload)

            # I'm aware this is redundant, but I want to avoid
            # having a bool variable just for the first heartbeat
            timeout = self.heartbeat_interval

    async def identify(self):
        payload = {
            "op": 2,
            "d": {
                "token": self._http._default_headers["Authorization"],  # TODO: consider having auth as a separate parameter?
                "properties": {
                    "os": "Python",
                    "browser": "Arke",
                    "device": "Computer",
                },
            },
        }

        return self.send(payload)