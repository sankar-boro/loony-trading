# Notifications

The system can tell you about trades, risk events and alerts on Telegram (and,
from the live bot, by e-mail). There are two senders, used by different
components.

## Setting up Telegram

1. In Telegram, talk to **@BotFather** → `/newbot` → copy the bot token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and find
   `"chat":{"id": …}` — that is your chat id (group ids are negative).
4. Add both to `.env`:

```env
TELEGRAM_BOT_TOKEN=7123456789:AAH...
TELEGRAM_CHAT_ID=123456789
```

5. Test from the dashboard backend: `curl localhost:8000/api/telegram/test` — it
   reports whether the token and chat id are set and reachable, and sends a test
   message.

## The two senders

| | `TelegramAlerter` (`utils/telegram_alerts.py`) | `Notifier` (`utils/notifier.py`) |
|---|---|---|
| Used by | `paper_trade.py`, `live_signals.py`, alert evaluation (scheduler, Alerts page, Intraday Lab), the Home page signal feed, `/api/telegram/test` | The live/paper bot in `main.py` |
| Configured by | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` environment variables | `notifications.telegram` (and `notifications.email`) in `settings.yaml`, which read the same variables |
| Turned on when | Both variables are set | `notifications.telegram.enabled: true` (the default) |
| Sending | Background thread — never blocks | `async`, alongside the trading loop |
| Channels | Telegram | Telegram and SMTP e-mail |

Messages use Telegram's HTML formatting. A failed send is logged and never
interrupts trading.

If you do not use Telegram, set `notifications.telegram.enabled: false`;
otherwise the bot attempts (and logs failures for) every message.

## What you will receive

| Event | Sender | Example |
|---|---|---|
| Paper session start | Alerter | "📊 Paper trade session started …" |
| Entry / exit (paper trader) | Alerter | "🟢 TRADE [donchian_breakout] RELIANCE BUY 25 @ ₹2,801.50" |
| End-of-day summary (paper trader) | Alerter | "DAILY SUMMARY — P&L ₹+3,120 (+0.62 %) · Trades 4 · Win rate 75 % · Max DD 0.40 %" |
| New scanner signals | Alerter | from `live_signals.py` |
| Strong signals on the Home page feed | Alerter | "🔔 Signal Scanner — 2 signal(s)" (confidence ≥ 0.65) |
| Alert rules triggered | Alerter | "🔔 3 alert(s) triggered — Strong bullish: TCS — {…}" |
| Bot entry filled | Notifier | "🟢 buy RELIANCE @ ₹2801.50 · donchian_breakout · conf=82%" |
| Bot position closed | Notifier | "🔴 Closed RELIANCE · stop_loss · PnL: ₹-850.00" |
| Reconciliation mismatch (live) | Notifier | "🛑 RELIANCE: bot thought it held +25, Upstox has +0 …" |
| Untracked broker position (live) | Notifier | "⚠️ Upstox has a position the bot is not tracking …" |

`TelegramAlerter` also offers `risk_alert()`, `circuit_alert()`,
`market_halt_alert()` and `strategy_disabled_alert()` for code that needs them,
and a `min_level` (INFO / WARNING / CRITICAL) filter.

## Avoiding noise

- **Alerts repeat** while their condition stays true — every scheduler run (5
  minutes) can resend the same trigger. Pause alerts you have acted on.
- **The Home page signal feed** can resend strong signals on every 60-second
  poll while the page is open (a known issue).
- Use a dedicated chat for trading messages.

## E-mail

The live bot can also e-mail its notifications:

```yaml
notifications:
  email:
    enabled: true
    smtp_host: "${SMTP_HOST}"     # e.g. smtp.gmail.com
    smtp_port: 587
    user: "${EMAIL_USER}"
    password: "${EMAIL_PASSWORD}" # for Gmail, an App Password
    to: "${EMAIL_TO}"
```

It connects with STARTTLS and sends one message per notification, subject
`[INFO] Trading Alert`.
