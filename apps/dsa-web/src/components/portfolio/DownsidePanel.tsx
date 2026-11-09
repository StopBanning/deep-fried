import type React from 'react';
import { TrendingDown } from 'lucide-react';
import { Bar, BarChart, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Badge, Card } from '../common';
import type { PortfolioDownsideBlock } from '../../types/portfolio';

const usd = (x?: number | null, sign = false): string => {
  if (x === undefined || x === null || !Number.isFinite(x)) return '--';
  const s = `$${Math.abs(x).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  if (x < 0) return `-${s}`;
  return sign ? `+${s}` : s;
};
const pct = (x?: number | null, sign = true): string => {
  if (x === undefined || x === null || !Number.isFinite(x)) return '--';
  const v = (x * 100).toFixed(1);
  return sign && x > 0 ? `+${v}%` : `${v}%`;
};
const chance = (p: number): string => (p < 0.005 ? '<1%' : p > 0.995 ? '>99%' : `${Math.round(p * 100)}%`);

const TH = 'px-2 py-1.5 text-left text-[11px] font-medium uppercase tracking-wide text-secondary';
const TD = 'px-2 py-1.5 text-xs text-foreground whitespace-nowrap';

const Table: React.FC<{ head: string[]; children: React.ReactNode }> = ({ head, children }) => (
  <div className="overflow-x-auto">
    <table className="w-full border-collapse">
      <thead>
        <tr className="border-b border-border/60">{head.map((h) => <th key={h} className={TH}>{h}</th>)}</tr>
      </thead>
      <tbody className="divide-y divide-border/40">{children}</tbody>
    </table>
  </div>
);

const Section: React.FC<{ title: string; note?: string; children: React.ReactNode }> = ({ title, note, children }) => (
  <div className="mt-5">
    <h3 className="text-xs font-semibold text-foreground">{title}</h3>
    {note ? <p className="mt-0.5 mb-2 text-[11px] text-secondary">{note}</p> : <div className="mb-2" />}
    {children}
  </div>
);

export const DownsidePanel: React.FC<{ downside?: PortfolioDownsideBlock | null }> = ({ downside }) => {
  if (!downside) return null;
  if (!downside.available) {
    if (downside.reason === 'disabled' || downside.reason === 'no US positions') return null;
    return (
      <section>
        <Card padding="md">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-cyan" />
            <h2 className="text-sm font-semibold text-foreground">Downside</h2>
            <Badge variant="default">Unavailable</Badge>
          </div>
          <p className="mt-2 text-xs text-secondary">{downside.reason}</p>
        </Card>
      </section>
    );
  }

  const stressData = (downside.stress ?? []).map((s) => ({ name: pct(s.move), smooth: s.smooth, choppy: s.choppy }));
  const late = (downside.levels ?? []).filter((l) => l.late);

  return (
    <section>
      <Card padding="md">
        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <TrendingDown className="h-4 w-4 text-cyan" />
            <h2 className="text-sm font-semibold text-foreground">Downside</h2>
            <span className="text-[11px] text-secondary">close of {downside.asOf} · numbers from code, not a language model</span>
          </div>
          {downside.scorecard ? (
            <Badge variant={downside.scorecard.in80 >= 0.72 ? 'success' : 'warning'}>
              Ranges held {Math.round(downside.scorecard.in80 * 100)}% of {downside.scorecard.weeks} weeks (80% target)
            </Badge>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-xl bg-elevated/60 p-3">
            <p className="text-[11px] text-secondary">Book</p>
            <p className="text-lg font-semibold text-foreground">{usd(downside.bookValue)}</p>
            <p className="text-[11px] text-secondary">{usd(downside.pnl, true)} against cost</p>
          </div>
          <div className="rounded-xl bg-elevated/60 p-3">
            <p className="text-[11px] text-secondary">Moves like</p>
            <p className="text-lg font-semibold text-foreground">{usd(downside.exposure)}</p>
            <p className="text-[11px] text-secondary">{downside.leverageRatio?.toFixed(2)}x the book, leverage counted</p>
          </div>
          <div className="rounded-xl bg-elevated/60 p-3">
            <p className="text-[11px] text-secondary">Normal week (4 in 5)</p>
            <p className="text-lg font-semibold text-foreground">±{usd(downside.weekRange80)}</p>
            <p className="text-[11px] text-secondary">next 5 sessions</p>
          </div>
          <div className="rounded-xl bg-elevated/60 p-3">
            <p className="text-[11px] text-secondary">Bad week (1 in 40)</p>
            <p className="text-lg font-semibold text-danger">-{usd(downside.weekRange95)}</p>
            <p className="text-[11px] text-secondary">95% band</p>
          </div>
        </div>

        {late.map((l) => (
          <p key={`${l.symbol}-${l.level}`} className="mt-3 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
            <strong>{l.symbol}:</strong> the {l.underlying} {l.level} line only fires once the holding is {pct(l.fromCost)} from your cost.
          </p>
        ))}

        <Section title="If things fall" note="Every underlying moves the same amount. Choppy paths cost daily-reset funds more than smooth ones.">
          <div className="h-44 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stressData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="currentColor" className="text-secondary" />
                <YAxis tickFormatter={(v: number) => usd(v)} tick={{ fontSize: 11 }} width={64} stroke="currentColor" className="text-secondary" />
                <ReferenceLine y={0} stroke="currentColor" className="text-border" />
                <Tooltip formatter={(v) => usd(Number(v), true)} />
                <Bar dataKey="choppy" name="Choppy path" isAnimationActive={false}>
                  {stressData.map((d) => <Cell key={d.name} fill={d.choppy < 0 ? '#f43f3f' : '#20ad6b'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <Table head={['Everything moves', 'Smooth path', 'Choppy path', 'Book after']}>
            {(downside.stress ?? []).map((s) => (
              <tr key={s.move}>
                <td className={TD}>{pct(s.move)}</td><td className={TD}>{usd(s.smooth, true)}</td>
                <td className={TD}>{usd(s.choppy, true)}</td><td className={TD}>{usd(s.bookAfter)}</td>
              </tr>
            ))}
          </Table>
        </Section>

        {downside.levels && downside.levels.length > 0 ? (
          <Section title="Your levels" note="Levels sit on the underlying; the last columns show what the holding is worth if it gets there.">
            <Table head={['Holding', 'Level', 'Distance', 'Touch this week', 'Close beyond', 'Holding at level', 'From your cost']}>
              {downside.levels.map((l) => (
                <tr key={`${l.symbol}-${l.kind}`}>
                  <td className={TD}>{l.symbol}</td>
                  <td className={TD}>{l.underlying} {l.kind === 'exit_below' ? 'exit below' : 'buy at'} {l.level}</td>
                  <td className={TD}>{pct(l.distance)}</td><td className={TD}>{chance(l.touch)}</td>
                  <td className={TD}>{chance(l.closeBeyond)}</td><td className={TD}>{l.holdingAtLevel.toFixed(2)}</td>
                  <td className={`${TD} ${l.late ? 'text-danger font-semibold' : ''}`}>{pct(l.fromCost)}</td>
                </tr>
              ))}
            </Table>
          </Section>
        ) : null}

        <Section title="Back to even">
          <Table head={['Holding', 'Tracks', 'Value', 'Against cost', 'To get back to cost']}>
            {(downside.holdings ?? []).map((h) => (
              <tr key={h.symbol}>
                <td className={TD}>{h.symbol}</td>
                <td className={TD}>{h.leverage !== 1 ? `${h.underlying} ${h.leverage}x` : 'itself'}</td>
                <td className={TD}>{usd(h.value)}</td>
                <td className={`${TD} ${h.pnl < 0 ? 'text-danger' : 'text-success'}`}>{usd(h.pnl, true)} ({pct(h.pnlPct)})</td>
                <td className={TD}>
                  {h.toCost <= 0 ? 'above cost' : h.leverage !== 1 ? `${pct(h.toCost)} (about ${pct(h.underlyingToCost)} in ${h.underlying})` : pct(h.toCost)}
                </td>
              </tr>
            ))}
          </Table>
        </Section>

        <Section title="How bad it has been" note="Worst fall in the data window, and a daily-reset fund at your leverage over the same stretch (no fees).">
          <Table head={['Underlying', 'Worst fall', 'When', 'At your leverage', 'Worst 5 sessions']}>
            {(downside.history ?? []).map((r) => (
              <tr key={`${r.underlying}-${r.leverage}`}>
                <td className={TD}>{r.underlying}</td><td className={TD}>{pct(r.worstFall)}</td>
                <td className={TD}>{r.peak} to {r.trough}</td>
                <td className={`${TD} ${r.atLeverage !== null ? 'text-danger font-semibold' : ''}`}>
                  {r.atLeverage !== null ? `${pct(r.atLeverage)} at ${r.leverage}x` : 'n/a (1x)'}
                </td>
                <td className={TD}>{pct(r.worstWeek)}</td>
              </tr>
            ))}
          </Table>
        </Section>

        <Section title="Next week's ranges and scorecard" note="Scorecard: the same model replayed over 26 weeks, each forecast made only with data from its own day. An honest 80% range holds about 80% of weeks.">
          <Table head={['Ticker', 'Last', 'Weekly vol', '80% range', '95% range', 'Model', 'Held 80% / 95%']}>
            {(downside.ranges ?? []).map((r) => (
              <tr key={r.ticker}>
                <td className={TD}>{r.ticker}</td><td className={TD}>{r.last.toFixed(2)}</td>
                <td className={TD}>{pct(r.weeklyVol, false)}</td>
                <td className={TD}>{r.r80Low.toFixed(2)} to {r.r80High.toFixed(2)}</td>
                <td className={TD}>{r.r95Low.toFixed(2)} to {r.r95High.toFixed(2)}</td>
                <td className={TD}>{r.method}</td>
                <td className={TD}>{r.record ? `${Math.round(r.record.in80 * 100)}% / ${Math.round(r.record.in95 * 100)}%` : '--'}</td>
              </tr>
            ))}
          </Table>
          <p className="mt-2 text-[11px] text-secondary">The models don't know about earnings dates: ranges run too narrow in a week with a report.</p>
        </Section>

        {downside.skipped && downside.skipped.length > 0 ? (
          <p className="mt-3 text-[11px] text-secondary">Not included (non-US): {downside.skipped.join(', ')}</p>
        ) : null}
        {downside.warnings && downside.warnings.length > 0 ? (
          <p className="mt-1 text-[11px] text-warning">Data warnings: {downside.warnings.join('; ')}</p>
        ) : null}
      </Card>
    </section>
  );
};

export default DownsidePanel;
