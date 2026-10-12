# Environment Variables

Secrets and machine-specific settings live in `.env` at the repository root
(start from `.env.example`). It is git-ignored — never commit it.

## How `.env` is loaded

`config/loader.py` reads `.env` whenever settings are loaded, so every entry
point — `main.py`, the scripts, the dashboard, the scheduler — sees the same
values. Rules:

- One `KEY=value` per line; blank lines and `#` comments are ignored.
- An unquoted value may end with a `  # comment`, which is dropped. Quote values
  that contain ` #` (e.g. passwords): `EMAIL_PASSWORD="abc # def"`.
- **Real environment variables win** — `.env` only fills in what is not already
  set, so `export UPSTOX_ACCESS_TOKEN=…` overrides the file.
- `settings.yaml` refers to variables as `"${NAME}"`.

Placeholder values copied from `.env.example` (such as
`your_newsapi_key_here`) are treated as unset where it matters (news provider
selection).

## Upstox

| Variable | Required | Used for |
|---|---|---|
| `UPSTOX_API_KEY` | For login | OAuth client id |
| `UPSTOX_API_SECRET` | For login | OAuth client secret |
| `UPSTOX_REDIRECT_URI` | For login | Must equal the app's registered redirect URL (`http://localhost:3561/callback`) |
| `UPSTOX_ACCESS_TOKEN` | Optional | A token to use when `data/upstox_token.json` is missing or expired. Its age is unknown, so it is assumed valid until 03:30 IST |
| `UPSTOX_EXTENDED_TOKEN` | Optional | Long-lived read-only token (written by `upstox_login.py`) |
| `UPSTOX_SANDBOX_TOKEN` | Optional | Sandbox token for `order.py --sandbox` / `test_upstox.py --sandbox` |

Without any valid token the dashboard runs in demo mode.

## Notifications

| Variable | Used for |
|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | All Telegram messages ([Notifications](../operations/notifications.md)) |
| `SMTP_HOST`, `SMTP_PORT`, `EMAIL_USER`, `EMAIL_PASSWORD`, `EMAIL_TO` | E-mail from the live bot when `notifications.email.enabled` |

## MarketPulse

| Variable | Default | Used for |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://loony:loony@localhost:5432/loony_trading` | SQLAlchemy and Alembic |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `loony`, `loony`, `loony_trading` | Docker Compose's database service |
| `REDIS_URL` | `redis://localhost:6379/0` | Reserved; not used by current code |
| `NEWS_API_KEY` | — | NewsAPI.org; without it the demo news provider is used |
| `LLM_PROVIDER` | `demo` | `anthropic` to use Claude for news classification and Copilot answers |
| `ANTHROPIC_API_KEY` | — | Required with `LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Claude model id; `claude-opus-5-5` is the current, cheaper Opus |

## Other

| Variable | Used for |
|---|---|
| `BINANCE_API_KEY`, `BINANCE_API_SECRET` | Crypto add-on / `--market crypto` backtests |
| `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_BASE_URL` | Placeholders in `settings.yaml`; unused |
| `PYTHON` | Interpreter used by `loony.sh` (default `python3`) |
| `ANTHROPIC_LOG` | `debug`/`info` for Anthropic SDK logging |

## Example

```env
UPSTOX_API_KEY=abcd1234
UPSTOX_API_SECRET=s3cr3t
UPSTOX_REDIRECT_URI=http://localhost:3561/callback

TELEGRAM_BOT_TOKEN=7123456789:AAH...
TELEGRAM_CHAT_ID=123456789

DATABASE_URL=postgresql+psycopg2://loony:loony@localhost:5432/loony_trading
NEWS_API_KEY=0123456789abcdef
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-5-5
```
