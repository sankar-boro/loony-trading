"""
Upstox WebSocket Market Feed

Upstox streams real-time market data over WebSocket using Protocol Buffers.
This module handles:
  - WebSocket connection with token auth
  - Subscription management (LTPC / Full Quote / Option Greeks modes)
  - Protobuf decoding (uses upstox-python-sdk decoder when available,
    falls back to raw struct parsing)
  - Automatic reconnection with exponential backoff
  - Event emission in the same format as MarketDataEngine
"""
from __future__ import annotations
import asyncio
import json
import struct
import time
from typing import Callable, Dict, List, Optional, Set

from .auth import UpstoxAuth
from utils.logger import get_logger

logger = get_logger("upstox.feed")

_WS_URL = "wss://api.upstox.com/v2/feed/market-data-feed"
_RECONNECT_BASE = 2      # seconds
_RECONNECT_MAX  = 60

# Feed modes
MODE_LTPC       = "ltpc"       # LTP + Close + Change — lowest bandwidth
MODE_FULL       = "full"       # Full quote with depth
MODE_OPTION     = "option"     # Full + option greeks

# Protobuf type IDs (from Upstox MarketDataFeed.proto)
_PTYPE_LTPC  = 1
_PTYPE_QUOTE = 5
_PTYPE_FULL  = 6


class MarketEvent:
    """Normalised market data event emitted to subscribers."""
    __slots__ = ("symbol", "ltp", "open", "high", "low", "close",
                 "volume", "oi", "bid", "ask", "ts", "instrument_key")

    def __init__(self, instrument_key: str):
        self.instrument_key = instrument_key
        self.symbol = instrument_key
        self.ltp = 0.0
        self.open = self.high = self.low = self.close = 0.0
        self.volume = self.oi = 0
        self.bid = self.ask = 0.0
        self.ts = int(time.time() * 1000)

    def to_candle_event(self) -> dict:
        return {
            "symbol":    self.symbol,
            "timeframe": "tick",
            "ts":        self.ts,
            "open":      self.open or self.ltp,
            "high":      self.high or self.ltp,
            "low":       self.low or self.ltp,
            "close":     self.ltp,
            "volume":    self.volume,
        }


_PROTOBUF_OK: bool | None = None


def _check_protobuf_decoder() -> bool:
    """Return True if the Upstox SDK protobuf decoder is importable; warn otherwise."""
    global _PROTOBUF_OK
    if _PROTOBUF_OK is not None:
        return _PROTOBUF_OK
    try:
        from upstox_client.feeder.uplink_limited import MarketDataFeedResponse_pb2  # noqa: F401
        _PROTOBUF_OK = True
        logger.debug("Upstox protobuf SDK decoder available")
    except Exception as exc:
        _PROTOBUF_OK = False
        logger.warning(
            "Upstox protobuf SDK not available (%s); falling back to manual decoder. "
            "Install with: pip install upstox-python-sdk", exc,
        )
    return _PROTOBUF_OK


class UpstoxFeed:
    """
    Async WebSocket client for Upstox real-time market data feed.

    Usage:
        feed = UpstoxFeed(auth, registry)
        feed.subscribe(my_callback)
        await feed.start(["RELIANCE", "TCS", "NIFTY50"], mode=MODE_FULL)
    """

    def __init__(self, auth: UpstoxAuth, registry=None,
                 mode: str = MODE_LTPC):
        self.auth = auth
        self.registry = registry
        self.mode = mode
        self._subscribers: List[Callable] = []
        self._subscribed_keys: Set[str] = set()
        self._running = False
        self._ws = None
        self._reconnect_delay = _RECONNECT_BASE
        self._last_prices: Dict[str, float] = {}
        # instrument_key → the symbol the caller subscribed with, so ticks come
        # back labelled the way the bot keys its positions ("RELIANCE",
        # "NIFTY50"), not as raw keys or the master's own names ("NIFTY 50").
        self._key_symbol: Dict[str, str] = {}
        _check_protobuf_decoder()

    def subscribe(self, callback: Callable) -> None:
        self._subscribers.append(callback)

    # ── Start / Stop ──────────────────────────────────────────────────────────

    async def start(self, symbols: List[str], mode: str | None = None) -> None:
        self.mode = mode or self.mode
        keys = self._resolve_keys(symbols)
        self._subscribed_keys = set(keys)
        self._running = True
        logger.info(f"Starting Upstox feed for {len(keys)} instruments (mode={self.mode})")
        while self._running:
            try:
                await self._connect_and_stream()
            except Exception as e:
                logger.error(f"Feed connection error: {e}")
            if not self._running:
                break
            logger.info(f"Reconnecting in {self._reconnect_delay}s...")
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, _RECONNECT_MAX)

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        logger.info("Upstox feed stopped")

    async def add_symbols(self, symbols: List[str]) -> None:
        keys = self._resolve_keys(symbols)
        new_keys = set(keys) - self._subscribed_keys
        if not new_keys or not self._ws:
            return
        self._subscribed_keys |= new_keys
        await self._send_subscription(list(new_keys))
        logger.info(f"Subscribed to {len(new_keys)} new instruments")

    # ── WebSocket core ────────────────────────────────────────────────────────

    async def _connect_and_stream(self) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed: pip install websockets")
            return

        headers = {
            "Authorization": f"Bearer {self.auth.access_token}",
            "Upgrade": "websocket",
        }
        async with websockets.connect(_WS_URL, extra_headers=headers,
                                       ping_interval=30, ping_timeout=10) as ws:
            self._ws = ws
            self._reconnect_delay = _RECONNECT_BASE  # reset on success
            logger.info("Upstox WebSocket connected")

            # Subscribe to instruments
            await self._send_subscription(list(self._subscribed_keys))

            async for message in ws:
                if not self._running:
                    break
                if isinstance(message, bytes):
                    await self._handle_binary(message)
                else:
                    self._handle_text(message)

    async def _send_subscription(self, keys: List[str]) -> None:
        if not self._ws or not keys:
            return
        msg = {
            "guid":   f"sub-{int(time.time())}",
            "method": "sub",
            "data": {
                "mode":           self.mode,
                "instrumentKeys": keys,
            },
        }
        await self._ws.send(json.dumps(msg))
        logger.debug(f"Subscribed to {len(keys)} keys")

    async def _unsubscribe(self, keys: List[str]) -> None:
        if not self._ws or not keys:
            return
        msg = {
            "guid":   f"unsub-{int(time.time())}",
            "method": "unsub",
            "data": {"instrumentKeys": keys},
        }
        await self._ws.send(json.dumps(msg))

    # ── Message decoding ──────────────────────────────────────────────────────

    def _validate_tick(self, event: MarketEvent) -> bool:
        """Drop ticks with no usable price.

        Large jumps are deliberately *not* filtered here: a jump filter that
        never accepts a new level would freeze a symbol for the rest of the
        session after a genuine gap (e.g. a split). The bot applies its own
        recoverable check — UpstoxTradingBot._is_sane_tick in main.py."""
        if event.ltp <= 0:
            logger.debug("Dropping tick %s: LTP=%.2f", event.symbol, event.ltp)
            return False
        return True

    async def _handle_binary(self, data: bytes) -> None:
        events = self._decode_protobuf(data)
        for event in events:
            event.symbol = self._symbol_for(event.instrument_key)
            if not self._validate_tick(event):
                continue
            self._last_prices[event.symbol] = event.ltp
            candle = event.to_candle_event()
            for cb in self._subscribers:
                try:
                    await cb(candle) if asyncio.iscoroutinefunction(cb) else cb(candle)
                except Exception as e:
                    logger.warning(f"Subscriber error: {e}")

    def _handle_text(self, message: str) -> None:
        try:
            data = json.loads(message)
            logger.debug(f"WS text msg: {data}")
        except Exception:
            pass

    def _decode_protobuf(self, data: bytes) -> List[MarketEvent]:
        """
        Decode Upstox protobuf binary feed.
        Tries the official SDK decoder first; falls back to manual parsing.
        """
        try:
            return self._decode_with_sdk(data)
        except Exception:
            return self._decode_manual(data)

    def _decode_with_sdk(self, data: bytes) -> List[MarketEvent]:
        from upstox_client.feeder.uplink_limited import MarketDataFeedResponse_pb2 as pb
        feed = pb.FeedResponse()
        feed.ParseFromString(data)
        events = []
        for instrument_key, payload in feed.feeds.items():
            evt = MarketEvent(instrument_key)
            if self.registry:
                rec = self.registry.get_metadata(instrument_key)
                evt.symbol = rec.get("tradingsymbol", instrument_key) if rec else instrument_key

            ff = payload.ff
            if ff.HasField("marketFF"):
                mff = ff.marketFF
                ltpc = mff.ltpc
                evt.ltp   = ltpc.ltp
                evt.close = ltpc.cp
                ohlc = mff.marketOHLC.ohlc
                if ohlc:
                    for o in ohlc:
                        if o.interval == "I1":
                            evt.open   = o.open
                            evt.high   = o.high
                            evt.low    = o.low
                            evt.close  = o.close
                            evt.volume = o.vol
                evt.ts = int(ltpc.ltt / 1_000_000)  # nanoseconds → ms

            elif ff.HasField("indexFF"):
                iff = ff.indexFF
                evt.ltp   = iff.ltpc.ltp
                evt.close = iff.ltpc.cp

            events.append(evt)
        return events

    def _decode_manual(self, data: bytes) -> List[MarketEvent]:
        """
        Lightweight manual protobuf parser for LTPC-mode messages.
        Handles wire types 0 (varint), 1 (64-bit), 5 (32-bit), 2 (length-delim).
        Good enough for LTP extraction without importing the full SDK.
        """
        events = []
        try:
            pos = 0
            current_key = None
            current_ltp = 0.0

            while pos < len(data):
                if pos >= len(data):
                    break
                tag_byte, pos = self._read_varint(data, pos)
                field_number = tag_byte >> 3
                wire_type = tag_byte & 0x07

                if wire_type == 0:       # varint
                    val, pos = self._read_varint(data, pos)
                elif wire_type == 1:     # 64-bit
                    val = struct.unpack_from("<d", data, pos)[0]
                    pos += 8
                elif wire_type == 2:     # length-delimited
                    length, pos = self._read_varint(data, pos)
                    val = data[pos:pos + length]
                    pos += length
                elif wire_type == 5:     # 32-bit
                    val = struct.unpack_from("<f", data, pos)[0]
                    pos += 4
                else:
                    break

                # field 1 in FeedResponse.feeds is the map key (instrument_key string)
                if wire_type == 2 and isinstance(val, bytes):
                    try:
                        candidate = val.decode("utf-8")
                        if "|" in candidate:
                            if current_key and current_ltp > 0:
                                evt = MarketEvent(current_key)
                                evt.ltp = current_ltp
                                events.append(evt)
                            current_key = candidate
                            current_ltp = 0.0
                    except UnicodeDecodeError:
                        pass
                elif wire_type in (1, 5) and isinstance(val, float) and val > 1:
                    # Heuristic: first plausible float after a key is likely LTP
                    if current_ltp == 0.0:
                        current_ltp = float(val)

            if current_key and current_ltp > 0:
                evt = MarketEvent(current_key)
                evt.ltp = current_ltp
                events.append(evt)
        except Exception as e:
            logger.debug(f"Manual protobuf decode error: {e}")
        return events

    @staticmethod
    def _read_varint(data: bytes, pos: int):
        result = 0
        shift = 0
        while pos < len(data):
            b = data[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        return result, pos

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _symbol_for(self, instrument_key: str) -> str:
        if instrument_key in self._key_symbol:
            return self._key_symbol[instrument_key]
        rec = self.registry.get_metadata(instrument_key) if self.registry else None
        return (rec or {}).get("tradingsymbol") or instrument_key

    def _resolve_keys(self, symbols: List[str]) -> List[str]:
        keys = []
        for sym in symbols:
            if "|" in sym:
                keys.append(sym)
            elif self.registry:
                key = self.registry.get_key(sym)
                if key:
                    keys.append(key)
                    self._key_symbol[key] = sym
                else:
                    logger.warning(f"Unknown symbol: {sym}")
            else:
                logger.warning(f"No registry — cannot resolve: {sym}")
        return keys

    def get_ltp(self, symbol: str) -> float:
        return self._last_prices.get(symbol, 0.0)
