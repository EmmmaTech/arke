import dataclasses
import discord_typings as dt
import typing as t

from ..internal.json import JSONObject, JSONArray
from ..utils.dispatcher import Event

__all__ = (
    "ConnectEvent",
    "DisconnectEvent",
    "RawGatewayEvent", 
    "DispatchEvent",
    "ReadyEvent",
)

@dataclasses.dataclass
class ConnectEvent(Event):
    pass

@dataclasses.dataclass
class DisconnectEvent(Event):
    pass

@dataclasses.dataclass
class RawGatewaySend(Event):
    payload: t.Union[JSONArray, JSONObject]

@dataclasses.dataclass
class RawGatewayEvent(Event):
    event: dt.GatewayEvent

@dataclasses.dataclass
class DispatchEvent(Event):
    _: dataclasses.KW_ONLY
    name: str
    data: t.Mapping[str, t.Any]

@dataclasses.dataclass
class ReadyEvent(Event):
    data: dt.ReadyData
