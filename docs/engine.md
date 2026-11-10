# The Deep Fried risk engine

How fried could your portfolio get? The `downside/` package is the risk engine behind the Downside panel,
the Downside check in reports and desk mode. It also runs on its own as a command-line report.

Most "AI stock analysis" tools ask a language model for a score, a buy/sell call and entry and exit
prices. Those numbers read confidently, but no model stands behind them and nobody tracks how often
they hold. Deep Fried does the opposite. Every number comes from code you can read, and the report
is organized around the question a holder actually needs answered: **how much can I lose from here,
and how fast?**

It understands daily-reset leveraged ETFs (TQQQ, SOXL, NVDL, GGLL and others), which is where most
retail portfolios get hurt by math nobody showed them.

## What's in the report

- **The book in one line:** value, the day's change, P&L against cost, and how much stock the book really
  moves like once leverage is counted ("$4,263 that moves like $6,889").
- **Next week's dollar range:** 80% and 95% bands for the whole book, from per-ticker volatility
  forecasts and their correlations.
- **If things fall:** the book's dollar loss if everything falls 10/20/30/40%, on a smooth path and on
  a choppy one (choppy paths cost leveraged funds more).
- **Your levels, translated:** exit lines are usually set on the stock, but a 2x fund falls twice as far.
  The report shows what each line costs the fund you actually hold, and flags lines that only fire
  after a loss of 25% or more.
- **Back to even:** the move each holding needs to get back to cost, and roughly what the underlying
  has to do for a leveraged fund to get there.
- **How bad it has been:** the worst fall in each underlying over the data window, and what a
  daily-reset fund at your leverage did over the same stretch (often 2 to 3 times worse).
- **Next week's ranges and level odds:** calibrated volatility forecasts, 80/95% price ranges, and the
  chance of touching or closing beyond each level this week.
- **Scorecard:** how often the model's own ranges held over the last 26 weeks, replayed with no look-ahead.
  The tool grades itself in every report.
- **Headlines:** the last 48 hours per ticker from Google News. There's an optional short brief
  written by Claude, which is rejected if it contains any number the headlines don't.

## Sample

From `portfolio.example.yaml` (made-up positions, real market data for the week ending 2026-11-06):

```
Book $4,263 (cash $250), +$66 on the day, -$297 against cost (-6.9%).
It moves like $6,889 of stock (1.62x the book, leverage counted). Next week, 4 weeks in 5
should land within ±$288; a 1-in-40 bad week costs about $441.

| Everything moves | Smooth path | Choppy path | Book after (smooth) |
| -20.0%           | -$1,229     | -$1,241     | $3,033              |

| Holding | Level                | Distance | Touch this week | Holding at level | From your cost |
| GGLL    | GOOGL exit below 255 | -11.0%   | 3%              | 52.56            | -34.3%         |

> GGLL: the GOOGL 255 line only fires once the holding is -34.3% from your cost.

| Underlying | Worst fall | When                     | At your leverage |
| QQQ        | -22.9%     | 2025-02-19 to 2025-04-08 | -56.9% at 3x     |
```

## Command-line report

From the repo root, with the app's requirements installed:

```bash
cp docs/portfolio.example.yaml portfolio.yaml   # git-ignored: put your real positions here
python -m downside.cli --portfolio portfolio.yaml
```

The report prints and is saved to `reports/<date>.md` (git-ignored). No API keys are needed: prices come
from Nasdaq's public historical-quotes endpoint, headlines from Google News RSS.

Options:
- `--no-fetch` reuses cached bars.
- `--no-news` skips headlines.
- `--brief` adds a Claude news brief (needs the `anthropic` package and `ANTHROPIC_API_KEY`).
- `--notify` pushes to your phone.
- `--quiet` keeps the report out of stdout.

## Portfolio file

```yaml
name: My account
cash: 250
positions:
  - symbol: TQQQ          # known leveraged funds resolve to their underlying automatically
    shares: 20
    avg_cost: 58
    levels:
      exit_below: 600     # levels are prices of the underlying (QQQ here)
  - symbol: NVDA
    shares: 6
    avg_cost: 195
    levels:
      buy_at: 175
  - symbol: XYZU          # anything not in the registry: say what it tracks
    shares: 10
    avg_cost: 20
    underlying: XYZ
    leverage: 2
watch: [SPY, SMH]         # extra tickers for ranges and news
```

The leveraged-fund registry is in [`downside/levered.py`](../downside/levered.py). Check an entry
against the fund's prospectus before relying on it.

## Push notifications

`python -m downside.cli --notify` sends a short summary plus the full report as a file to every channel configured in
the environment:

| Channel  | Variables |
|----------|-----------|
| Discord  | `DISCORD_WEBHOOK_URL` |
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Email    | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` (`SMTP_PORT`, default 465) |

## How the numbers are made

- **Index ETFs.** SPY and QQQ use Cboe's VIX and VXN instead (free daily history files), rescaled the
  same way. In the same test, implied volatility beat every model on those two ETFs, while HAR-PK won
  across single stocks. If Cboe is unreachable they fall back to HAR-PK, and the report says so.
- **Scorecard.** Every run replays the last 26 weekly forecasts per ticker, each made only with data
  from its own day, and reports how often the week's move landed inside the 80% and 95% ranges. No
  state is stored, so it works the same in CI. An honest 80% range holds about 80% of weeks.
- **Volatility.** For everything else, next week's variance comes from HAR-PK.
  - It regresses the next 5 sessions' realized variance on the daily, weekly and monthly Parkinson range,
    fitted on the trailing 500 sessions.
  - The forecast is then rescaled by the model's own error over the last 52 weeks.
  - In a pre-registered test on 10 US large caps and ETFs (2024-2026, scored on QLIKE), it beat EWMA,
    GARCH(1,1) and a zero-shot time-series foundation model.
  - Tickers with less than about three years of history fall back to EWMA, and the report says so.
- **Odds.** A driftless lognormal path over 5 sessions. "Touch" uses the reflection principle (twice the
  chance of closing beyond, capped at 1).
- **Leveraged funds.** Value after an underlying move R is `(1+R)^L * exp(-0.5 L (L-1) v)`, where v is the
  path's variance. Fees and financing are ignored, so real funds do slightly worse.
- **Book range.** Dollar exposure per underlying times its forecast volatility, combined with 250-session
  return correlations. Linear in returns, so it understates tails.

**Known limits:**
- The volatility model doesn't know about earnings dates, so ranges run too narrow in a week with a
  report.
- Prices come from an unofficial endpoint that can change without notice.
- US-listed symbols only.
