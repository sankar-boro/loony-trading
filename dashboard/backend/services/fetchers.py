import httpx
from ..config import _WATCHLIST_SYMS
from ..utils import get_token

# Reusable Upstox data fetchers (if needed across routers)