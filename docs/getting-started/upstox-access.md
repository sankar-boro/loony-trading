# Connecting to Upstox

Every real price, candle and order goes through the Upstox API. This chapter
explains the kinds of tokens Upstox issues, how to get each one, when they
expire, and how to keep a valid token every trading day without thinking
about it.

## Create an Upstox app

1. Log in to the Upstox developer console
   (`account.upstox.com/developer/apps`) and create an app.
2. Set its **redirect URL** to `http://localhost:3561/callback`. It must match
   `UPSTOX_REDIRECT_URI` in `.env` character for character.
3. Copy the **API key** and **API secret** into `.env` as `UPSTOX_API_KEY`
   and `UPSTOX_API_SECRET`.

## The four kinds of token

| Token | Lifetime | Can trade? | Stored in | Used by |
|---|---|---|---|---|
| **Daily access token** | Until **03:30 IST** the next morning | Yes | `data/upstox_token.json` (and optionally `UPSTOX_ACCESS_TOKEN`) | Everything — the bot, dashboard, scripts |
| **Extended token** | About 1 year | No (read-only) | `data/upstox_extended_token.json`, `UPSTOX_EXTENDED_TOKEN` | Market data where a long-lived token is convenient |
| **Analytics token** | About 1 year | No (read-only) | Paste into `UPSTOX_ACCESS_TOKEN` | Market data only; generated in the developer console |
| **Sandbox token** | About 30 days | Sandbox orders only | `data/upstox_sandbox_token.json` | `scripts/order.py --sandbox`, `scripts/test_upstox.py --sandbox` |

### When the daily token expires

A daily token is not valid for "24 hours". Every token stops working at
**03:30 IST the morning after it was issued** — or the same morning if it was
issued between midnight and 03:30. A token obtained at 09:00 on Monday dies at
03:30 on Tuesday; one obtained at 23:00 on Monday also dies at 03:30 on Tuesday.

All expiry checks in the code use one rule, `token_expires_at()` /
`token_hours_left()` in `data_engine/upstox/auth.py`: the bot's startup check,
`check_token.py`, `health.py`, `status.py`, `auto_login.sh`, the dashboard's
status bar and every data endpoint. So the whole system agrees on whether a
token is still alive.

## Logging in — three methods

`scripts/upstox_login.py` implements every way Upstox lets you get a token. It
reads credentials from `.env` (prompting for anything missing) and, unless you
pass `--force`, exits early if the saved token is still valid.

### Method 1 — browser OAuth (default)

```bash
python scripts/upstox_login.py            # opens your browser
python scripts/upstox_login.py --no-browser   # prints the URL instead (headless/SSH)
python main.py --mode auth                # same flow via the bot's entry point
```

1. A small HTTP server starts on `localhost:3561` (change with `--port`).
2. Your browser opens the Upstox login page. Log in with mobile, PIN and TOTP.
3. Upstox redirects to `http://localhost:3561/callback?code=…`; the script
   captures the code and exchanges it for a token.
4. The token is saved to `data/upstox_token.json` with an `obtained_at`
   timestamp. If Upstox also returned an **extended token**, it is saved to
   `data/upstox_extended_token.json` and written to `.env` as
   `UPSTOX_EXTENDED_TOKEN`.

### Method 2 — approve on your phone (`--token-request`)

```bash
python scripts/upstox_login.py --token-request
```

No browser, no TOTP. The script asks Upstox to send a WhatsApp message and an
in-app notification; you tap **Approve**, and Upstox posts the token to a local
webhook the script is listening on. One-time setup: in your app's settings on
the developer console, set the **Notifier URL** to
`http://localhost:3561/callback`. Common errors the script explains:
`UDAPI100069` (wrong key/secret) and `UDAPI1123` (Notifier URL not configured).

### Method 3 — sandbox token (`--sandbox`)

```bash
python scripts/upstox_login.py --sandbox
```

Sandbox tokens are generated in the developer portal (`#sandbox` tab →
**Generate**) and pasted in (input is hidden). They last about 30 days and only
work against the sandbox — useful for testing order placement without money.

## Checking your token

```bash
python scripts/check_token.py            # daily token: validity, JWT expiry, live prices
python scripts/check_token.py --all      # every saved token
python scripts/check_token.py --extended # just the extended token
python scripts/check_token.py --sandbox  # just the sandbox token
./loony.sh token                         # same as the first command
```

The dashboard's sidebar footer also shows **Token** with a green dot and the
token's age, or red **missing** when there is no valid token — in which case
the app switches to demo data (see the next chapter).

Where the code looks for a token, in order:

1. An explicit `--token` argument (most scripts accept one).
2. `UPSTOX_ACCESS_TOKEN` from the environment / `.env`.
3. `data/upstox_token.json`, if it has not passed its 03:30 expiry.

## Renewing automatically every morning

`scripts/auto_login.sh` is built for cron. It activates the virtualenv
(`VENV_PATH`, default `.venv`), checks the saved token with the 03:30 rule,
and renews only if it has expired:

```bash
bash scripts/auto_login.sh --check-only   # just report; exit code 1 if expired
bash scripts/auto_login.sh                # renew if expired (paste-token mode)
bash scripts/auto_login.sh --force        # always run the OAuth browser flow
```

A typical crontab entry (08:45 IST = 03:15 UTC, weekdays):

```cron
15 3 * * 1-5 /path/to/loony-trading/scripts/auto_login.sh >> /path/to/loony-trading/logs/auto_login.log 2>&1
```

Set `SERVICE_NAME` at the top of the script to restart a systemd service (for
example your bot) after a successful renewal. It warns when the token expires
within `WARN_HOURS_LEFT` (default 3) hours.

> Upstox login always needs a human step — a browser login with TOTP, or a tap
> on your phone with `--token-request`. Fully unattended renewal is not
> possible; the script makes the daily step as short as possible.

## Generating TOTP codes

If you log in from a server without your phone, `scripts/generate_totp.py`
produces the same 6-digit code as your authenticator app from your TOTP secret
(the base32 string in the 2FA QR code), using only the standard library:

```bash
python scripts/generate_totp.py                     # prompts for the secret
python scripts/generate_totp.py --secret XXXX --live    # refresh every 30 s
python scripts/generate_totp.py --save              # remember the secret locally
```

Treat the TOTP secret like a password: anyone with it and your PIN can log in.

## Security notes

- `.env`, `data/`, `logs/` and `models/` are git-ignored. Never commit them —
  `data/` holds your tokens.
- The daily token can place real orders. Do not paste it into chats, issues or
  logs. Read-only extended/analytics tokens are safer for data-only tools.
- If a token leaks, change your Upstox password and log in again; until it is
  revoked, assume the leaked token works until its 03:30 expiry.
