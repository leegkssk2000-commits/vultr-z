import { useCallback, useEffect, useState } from "react";
import "./OrderbookPanel.css";

type OrderbookSymbol = "BTCUSDT" | "ETHUSDT" | "SOLUSDT" | "XRPUSDT" | "LINKUSDT";

type OrderbookLevel = {
  price: string;
  qty: string;
};

type OrderbookState = {
  bids: OrderbookLevel[];
  asks: OrderbookLevel[];
  mid: string;
  status: "connecting" | "live" | "stale" | "offline";
  updatedAt: number | null;
};

type BinanceDepthMessage = {
  stream?: string;
  data?: {
    s?: string;
    bids?: [string, string][];
    asks?: [string, string][];
  };
};

const ORDERBOOK_SYMBOLS: OrderbookSymbol[] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LINKUSDT"];

const initialBooks = ORDERBOOK_SYMBOLS.reduce<Record<OrderbookSymbol, OrderbookState>>((acc, symbol) => {
  acc[symbol] = { bids: [], asks: [], mid: "—", status: "connecting", updatedAt: null };
  return acc;
}, {} as Record<OrderbookSymbol, OrderbookState>);

function formatNumber(value: string, maxFractionDigits = 4) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: maxFractionDigits,
    minimumFractionDigits: number >= 100 ? 1 : 2
  }).format(number);
}

function toRows(levels: [string, string][] | undefined): OrderbookLevel[] {
  return (levels ?? []).slice(0, 5).map(([price, qty]) => ({ price, qty }));
}

function getMid(bids: OrderbookLevel[], asks: OrderbookLevel[]) {
  const bestBid = Number(bids[0]?.price);
  const bestAsk = Number(asks[0]?.price);
  if (!Number.isFinite(bestBid) || !Number.isFinite(bestAsk)) return "—";
  return formatNumber(String((bestBid + bestAsk) / 2), 4);
}

function getSymbol(message: BinanceDepthMessage): OrderbookSymbol | null {
  const direct = message.data?.s;
  if (direct && ORDERBOOK_SYMBOLS.includes(direct as OrderbookSymbol)) return direct as OrderbookSymbol;

  const fromStream = message.stream?.split("@")[0]?.toUpperCase();
  if (fromStream && ORDERBOOK_SYMBOLS.includes(fromStream as OrderbookSymbol)) return fromStream as OrderbookSymbol;

  return null;
}

function OrderbookRows({ symbol, side, rows }: { symbol: OrderbookSymbol; side: "ask" | "bid"; rows: OrderbookLevel[] }) {
  const safeRows = rows.length ? rows : [{ price: "—", qty: "—" }];

  return (
    <div className={`zr-orderbook-table zr-orderbook-table--${side === "ask" ? "asks" : "bids"}`}>
      <div className="zr-orderbook-row zr-orderbook-row--head">
        <span>{side}</span>
        <span>qty</span>
      </div>
      {safeRows.map((level, index) => (
        <div className="zr-orderbook-row" key={`${symbol}-${side}-${index}`}>
          <span>{level.price === "—" ? "—" : formatNumber(level.price, 4)}</span>
          <span>{level.qty === "—" ? "—" : formatNumber(level.qty, 5)}</span>
        </div>
      ))}
    </div>
  );
}

function OrderbookCardContent({ symbol, book }: { symbol: OrderbookSymbol; book: OrderbookState }) {
  return (
    <>
      <div className="zr-orderbook-card__top">
        <div>
          <h3>{symbol}</h3>
          <span>mid {book.mid}</span>
        </div>
        <b data-state={book.status}>{book.status}</b>
      </div>

      <OrderbookRows symbol={symbol} side="ask" rows={book.asks} />
      <OrderbookRows symbol={symbol} side="bid" rows={book.bids} />

      <div className="zr-orderbook-card__foot">
        <span>depth5@1000ms</span>
        <span>{book.updatedAt ? new Date(book.updatedAt).toLocaleTimeString() : "waiting"}</span>
      </div>
    </>
  );
}

export function OrderbookPanel() {
  const [books, setBooks] = useState<Record<OrderbookSymbol, OrderbookState>>(initialBooks);

  const markAll = useCallback((status: OrderbookState["status"]) => {
    setBooks((current) => {
      const next = { ...current };
      for (const symbol of ORDERBOOK_SYMBOLS) next[symbol] = { ...next[symbol], status };
      return next;
    });
  }, []);

  useEffect(() => {
    let socket: WebSocket | null = null;

    const connect = () => {
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;

      const streams = ORDERBOOK_SYMBOLS.map((symbol) => `${symbol.toLowerCase()}@depth5@1000ms`).join("/");
      socket = new WebSocket(`wss://stream.binance.com:9443/stream?streams=${streams}`);
      markAll("connecting");

      socket.onopen = () => markAll("live");

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as BinanceDepthMessage;
          const symbol = getSymbol(message);
          if (!symbol) return;

          const bids = toRows(message.data?.bids);
          const asks = toRows(message.data?.asks);

          setBooks((current) => ({
            ...current,
            [symbol]: {
              bids,
              asks,
              mid: getMid(bids, asks),
              status: "live",
              updatedAt: Date.now()
            }
          }));
        } catch {
          markAll("stale");
        }
      };

      socket.onerror = () => markAll("stale");

      socket.onclose = () => {
        socket = null;
        markAll(typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "stale");
      };
    };

    const reconnectOrRefresh = () => {
      if (!socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING) connect();
      else markAll(document.visibilityState === "hidden" ? "stale" : "live");
    };

    const handleBlur = () => markAll("stale");

    connect();
    document.addEventListener("visibilitychange", reconnectOrRefresh);
    window.addEventListener("pageshow", reconnectOrRefresh);
    window.addEventListener("focus", reconnectOrRefresh);
    window.addEventListener("online", reconnectOrRefresh);
    window.addEventListener("blur", handleBlur);

    return () => {
      document.removeEventListener("visibilitychange", reconnectOrRefresh);
      window.removeEventListener("pageshow", reconnectOrRefresh);
      window.removeEventListener("focus", reconnectOrRefresh);
      window.removeEventListener("online", reconnectOrRefresh);
      window.removeEventListener("blur", handleBlur);
      socket?.close();
    };
  }, [markAll]);

  return (
    <section className="zr-orderbook-panel" data-z-orderbook-panel="1" aria-label="Source owned live orderbook panel">
      <div className="zr-orderbook-panel__header">
        <div>
          <div className="zr-orderbook-panel__eyebrow">source-owned orderbook</div>
          <h2>Live orderbook anchor</h2>
        </div>
        <span className="zr-orderbook-panel__badge">React component · no runtime injection</span>
      </div>

      <div className="zr-orderbook-grid">
        <article className="zr-orderbook-card" data-z-orderbook-card="BTCUSDT">
          <OrderbookCardContent symbol="BTCUSDT" book={books.BTCUSDT} />
        </article>
        <article className="zr-orderbook-card" data-z-orderbook-card="ETHUSDT">
          <OrderbookCardContent symbol="ETHUSDT" book={books.ETHUSDT} />
        </article>
        <article className="zr-orderbook-card" data-z-orderbook-card="SOLUSDT">
          <OrderbookCardContent symbol="SOLUSDT" book={books.SOLUSDT} />
        </article>
        <article className="zr-orderbook-card" data-z-orderbook-card="XRPUSDT">
          <OrderbookCardContent symbol="XRPUSDT" book={books.XRPUSDT} />
        </article>
        <article className="zr-orderbook-card" data-z-orderbook-card="LINKUSDT">
          <OrderbookCardContent symbol="LINKUSDT" book={books.LINKUSDT} />
        </article>
      </div>
    </section>
  );
}
