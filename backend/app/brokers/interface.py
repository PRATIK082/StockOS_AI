"""Broker adapter interface for StockOS.

Defines the contract that all execution brokers (Paper, Zerodha, AngelOne)
must implement.  The interface is deliberately side-effect-free at the
type‑hint level – actual I/O (HTTP, socket, serial) happens in the
concrete implementations.

Key design notes:
-  All monetary values are expressed in Indian rupees (₹).
-  Order quantities respect lot sizes and exchange minimums.
-  The ``connection_status`` dict is used by the UI to show “connect/disconnect”
  buttons and permanent warning banners.
-  ``place_order`` returns a :class:`BrokerOrderResult` that carries both the
  broker‑generated order ID and a local audit record – the caller (order
  submission endpoint) persisting this result to the immutable audit table.
-  ``square_off`` / ``kill_switch`` are **hard** closes – they do not
  “modify” an order to cancelled; they send a new opposite‑side order or
  force‑exit all positions.
-  Implementations must **never** log secrets, tokens, API keys, PINs or TOTP
  values.  Credentials are loaded once (at process start or first connect) from
  encrypted local storage or OS environment variables.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# ------------------------------------------------------------------------- #
# Shared types used across all broker adapters
# ------------------------------------------------------------------------- #

class BrokerOrderStatus(str):
    """Order lifecycle status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    model_config = {"arbitrary_types_allowed": True}


class BrokerSide(str):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"

    model_config = {"arbitrary_types_allowed": True}


class OrderType(str):
    """Order type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"  # Stop Loss
    SL_MARKET = "SL-M"  # Stop Loss Market

    model_config = {"arbitrary_types_allowed": True}


class ProductType(str):
    """Product/validity type."""
    CNC = "CNC"   # Cash and Carry
    INTRADAY = "INTRADAY"
    CO = "CO"     # Cover Order
    BO = "BO"     # Bracket Order

    model_config = {"arbitrary_types_allowed": True}


class BrokerOrderResult(BaseModel):
    """Result of a ``place_order`` call."""
    order_id: str  # broker-generated order ID
    status: str = "pending"  #: Pending | Accepted | Filled | Partially_filled | Cancelled | Rejected | Expired
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    # ------------------------------------------------------------------
    # Internal audit fields – the caller MUST persist these to the
    # immutable audit table.  They are *not* logged to console or sent
    # external.
    # ------------------------------------------------------------------
    local_order_id: Optional[str] = None  # client-generated correlate
    side: Optional[str] = None  # BrokerSide.BUY | SELL
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    product: Optional[str] = None  # ProductType.CNC | INTRADAY | CO | BO
    order_type: Optional[str] = None  # OrderType.MARKET | LIMIT | SL | SL_MARKET
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None  # limit price, if applicable
    stop_loss: Optional[Decimal] = None
    target: Optional[Decimal] = None
    filled_quantity: Optional[Decimal] = None
    filled_price: Optional[Decimal] = None
    avg_price: Optional[Decimal] = None
    pnl: Optional[Decimal] = None  # realised P&L if order is fully filled
    error_message: Optional[str] = None


# ------------------------------------------------------------------------- #
# Request/Response DTOs used by the API layer
# ------------------------------------------------------------------------- #


class BrokerConnectRequest(BaseModel):
    """Credentials for connecting to a broker."""
    api_key: str = Field(..., description="Never stored long‑term; used only for the initial handshake")
    api_secret: str = Field(..., description="Never stored long‑term")
    redirect_uri: Optional[str] = None  # for OAuth flow
    password: Optional[str] = None  # for Angel One login


class BrokerConnectResponse(BaseModel):
    """Response from ``connect``."""
    authenticated: bool
    access_token: Optional[str] = None  # never returned in plain text to UI
    expires_at: Optional[datetime] = None
    message: str


class BrokerFunds(BaseModel):
    """Funds / buying power response."""
    cash: Decimal = Field(Decimal("0.00"))
    margin_available: Decimal = Field(Decimal("0.00"))
    equity: Decimal = Field(Decimal("0.00"))


class BrokerQuote(BaseModel):
    """Latest quote for a symbol."""
    symbol: str
    exchange: str
    last_price: Decimal
    bid: Decimal
    ask: Decimal
    volume: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    timestamp: datetime


class BrokerPosition(BaseModel):
    """Single position held by the broker."""
    symbol: str
    exchange: str
    product: str  # ProductType.CNC | INTRADAY | CO | BO
    quantity: Decimal  # positive = long, negative = short
    average_price: Decimal
    market_value: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal


class BrokerOrders(BaseModel):
    """List of orders."""
    orders: List[BrokerOrderResult]
    has_more: bool = False
    next_cursor: Optional[str] = None


# ------------------------------------------------------------------------- #
# Abstract base class – all concrete brokers must inherit from this
# ------------------------------------------------------------------------- #


class BrokerBase(ABC):
    """Abstract base class for all StockOS broker adapters."""

    name: str = "base-broker"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @abstractmethod
    async def connect(self, credentials: BrokerConnectRequest) -> BrokerConnectResponse:
        """Authenticate with the broker.

        Must **not** store the raw ``api_key`` / ``api_secret`` beyond the
        duration of this call.  Any tokens obtained MUST be cached securely
        (e.g. OS keyring or encrypted file) and the plaintext cleared from
        memory immediately after use.
        ------------------------------------------------------------------
        Returns ``authenticated=True`` only when the handshake succeeds.
        The ``access_token`` field is informational – the UI must **not**
        display it.  Store only the token reference, not the secret.
        ------------------------------------------------------------------
        Raises ``AuthenticationError`` (subclass of ``BrokerError``) on
        failure.
        ------------------------------------------------------------------
        Implementations MUST clear ``credentials.api_key`` and
        ``credentials.api_secret`` from ``os.environ`` or the process memory
        as soon as the token is obtained.
        ------------------------------------------------------------------
        """
        raise NotImplementedError

    @abstractmethod
    async def connection_status(self) -> Dict[str, Any]:
        """Return the current connection state.

        Returns a dict with at least:
        - ``online``: ``bool``
        - ``broker_name``: ``str``  (e.g. "paper", "zerodha", "angelone")
        - ``last_checked``: ``datetime``
        - ``error``: ``Optional[str]``  (if not online)
        """
        raise NotImplementedError

    @abstractmethod
    async def funds(self) -> BrokerFunds:
        """Return current cash / margin / equity.

        If the broker is not connected, return zeros / minimal info.
        """
        raise NotImplementedError

    @abstractmethod
    async def quote(self, symbol: str) -> BrokerQuote:
        """Return the latest quote for *symbol*.

        *symbol* is the canonical ``EXCHANGE:TICKER`` form, e.g. ``NSE:TCS``.
        """
        raise NotImplementedError

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: BrokerSide,
        product: ProductType,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
    ) -> BrokerOrderResult:
        """Submit an order to the broker.

        The returned ``BrokerOrderResult`` **must** carry a
        ``local_order_id`` (client‑side correlate) and all audit fields so
        the API endpoint can write an immutable audit record.

        Raises ``OrderError`` (subclass of ``BrokerError``) on failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def modify_order(
        self,
        order_id: str,
        quantity: Optional[Decimal] = None,
        price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        target: Optional[Decimal] = None,
    ) -> BrokerOrderResult:
        """Modify an existing order.

        Raises ``OrderError`` on failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_id: str) -> BrokerOrderResult:
        """Cancel an existing order.

        Raises ``OrderError`` on failure.
        """
        raise NotImplementedError

    @abstractmethod
    async def orders(self, cursor: Optional[str] = None) -> BrokerOrders:
        """List orders with optional pagination cursor."""
        raise NotImplementedError

    @abstractmethod
    async def positions(self) -> List[BrokerPosition]:
        """Return all open positions."""
        raise NotImplementedError

    @abstractmethod
    async def square_off(self) -> Dict[str, Any]:
        """Close all open positions.

        Returns a dict with at least:
        - ``closed``: ``bool``
        - ``closed_order_ids``: ``List[str]``
        - ``total_pnl``: ``Decimal``
        - ``error``: ``Optional[str]``
        """
        raise NotImplementedError

    @abstractmethod
    async def kill_switch(self) -> Dict[str, Any]:
        """Emergency stop – close all positions and reject new entries.

        Returns a dict with at least:
        - ``active``: ``bool``  (was the kill switch already engaged?)
        - ``closed_order_ids``: ``List[str]``
        - ``total_pnl``: ``Decimal``
        - ``error``: ``Optional[str]``
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helper – error classes
    # ------------------------------------------------------------------
    class BrokerError(Exception):
        """Base broker exception."""
        pass

    class AuthenticationError(BrokerError):
        """Raised when login/handshake fails."""
        pass

    class OrderError(BrokerError):
        """Raised when an order cannot be placed/modified/cancelled."""
        pass

    class InsufficientMarginError(BrokerError):
        """Raised when the account does not have enough margin."""
        pass

    class SymbolNotFoundError(BrokerError):
        """Raised when the requested symbol is not listed on the exchange."""
        pass