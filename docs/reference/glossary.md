# Glossary

Trading, market and project terms used in this handbook.

| Term | Meaning |
|---|---|
| **ADX** | Average Directional Index — trend strength regardless of direction; ≥ 25 is treated as trending |
| **Alert** | A saved rule (e.g. `score__gte: 75`) checked against every stock's latest composite signal |
| **AMO** | After-market order — placed outside trading hours for the next session |
| **Analogue (historical)** | A past news event of the same type and direction, with its realised price outcome |
| **ATR** | Average True Range — average bar range including gaps; used to place stops (2× ATR) and targets (3× ATR) |
| **Backtest** | Replaying history bar by bar through a strategy to estimate how it would have done |
| **Beta** | How much a stock or portfolio moves with Nifty; 1.2 means 1.2 % for each 1 % Nifty move |
| **Bhav copy** | NSE's daily end-of-day file of prices and volumes per stock |
| **Bollinger Bands** | A moving average ± 2 standard deviations; %B is the position within them (0 = lower, 1 = upper) |
| **Catalyst** | A news event judged material for a stock; scored 0–10 by the classifier |
| **CNC** | Cash and carry — delivery equity, held across days, no leverage |
| **Cointegration** | Two price series that drift apart only temporarily — the basis of pair trading |
| **Composite score** | MarketPulse's 0–100 blend of catalyst, technical, momentum, volume, historical, regime and risk components |
| **Confidence** | A strategy's 0–1 belief in its signal; ×100 on composite signals |
| **CVaR** | Conditional Value-at-Risk (expected shortfall) — the average loss in the worst x % of outcomes |
| **Delivery %** | Share of traded volume actually taken into delivery rather than squared off intraday |
| **Demo mode** | Running without a valid Upstox token: synthetic, clearly labelled data |
| **DII** | Domestic Institutional Investors (Indian mutual funds, insurers) |
| **Drawdown** | Fall from the highest equity so far; max drawdown is the worst such fall |
| **EMA / SMA** | Exponential / simple moving average |
| **Expectancy** | Average profit per trade = win rate × average win + loss rate × average loss |
| **Extended token** | Long-lived read-only Upstox token |
| **F&O** | Futures and options; traded in whole lots |
| **F&O ban** | Stocks whose open interest exceeds 95 % of the market-wide limit — no new F&O positions that day |
| **FII** | Foreign Institutional Investors; their daily net buying is a widely watched flow |
| **GIFT Nifty** | Nifty futures traded in GIFT City from early morning — an indicator of the opening gap |
| **GTT** | Good-till-triggered order — rests at the broker until a trigger price is hit |
| **HMM** | Hidden Markov Model — a statistical model that infers hidden market regimes |
| **Instrument key** | Upstox's identifier: `NSE_EQ` + ISIN for stocks, `NSE_INDEX` + name for indices, a numeric token for F&O |
| **ISIN** | International Securities Identification Number; changes after some splits, bonuses and mergers |
| **IV / IV rank** | Implied volatility from option prices; IV rank is where today's IV sits in its past range |
| **Kalman filter** | A recursive estimator used for the time-varying hedge ratio in pair trading |
| **Kelly criterion** | A sizing formula from win probability and payoff; used at a fraction (¼) for safety |
| **Lot size** | Minimum F&O trading unit (NIFTY 65, BANKNIFTY 30, …) |
| **LTP** | Last traded price |
| **MACD** | Moving Average Convergence Divergence — difference of two EMAs and its signal line |
| **Max pain** | Option strike at which option writers lose least at expiry |
| **MIS** | Margin intraday square-off — intraday product; must be closed by 15:20 (the bot closes at 15:14) |
| **Monte Carlo** | Resampling trades many times to see the range of outcomes luck alone could produce |
| **NRML** | Normal product for carrying F&O positions overnight |
| **OBV** | On-balance volume — cumulative volume signed by price direction |
| **Paper trading** | Trading with virtual money against real prices |
| **PCR** | Put/call ratio of open interest — a sentiment gauge |
| **PEAD** | Post-earnings announcement drift — prices keep moving in the direction of an earnings surprise |
| **POC / VAH / VAL** | Volume profile: point of control (most traded price), value-area high and low (the 70 % volume band) |
| **Profit factor** | Gross profit ÷ gross loss; above 1 is profitable |
| **Reconciliation** | Comparing the bot's positions with the broker's and correcting differences |
| **Regime** | Market state: trending up/down, ranging, high or low volatility |
| **RSI** | Relative Strength Index, 0–100; below 30 oversold, above 70 overbought |
| **Sharpe ratio** | Annualised return ÷ annualised volatility; above 1 is decent |
| **Slippage** | Difference between the expected and actual fill price |
| **Sortino ratio** | Like Sharpe but counting only downside volatility |
| **Squareoff** | Closing a position, especially intraday positions before the session ends |
| **STT** | Securities Transaction Tax — 0.1 % on delivery trades, 0.025 % on the sell side intraday |
| **Supertrend** | An ATR-based trailing line that flips sides when the trend changes |
| **Tick** | One price update from the live feed |
| **Trailing stop** | A stop that follows price in your favour and never moves back |
| **TOTP** | Time-based one-time password used for Upstox login |
| **VIX (India VIX)** | NSE's 30-day implied volatility index — the "fear gauge" |
| **VWAP** | Volume-weighted average price, reset each session |
| **Walk-forward** | Testing a strategy on consecutive out-of-sample periods to check robustness |
| **Watch** | Composite direction for a stock with a firing strategy and score ≥ 50 that did not clear the full quality gate |
| **Z-score** | How many standard deviations a value is from its recent mean |
