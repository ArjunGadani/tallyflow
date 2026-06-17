import {
  Area, AreaChart, Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { useState } from 'react';
import { api } from '../api';
import { Card } from '../components/Card';
import { CountUp } from '../components/CountUp';
import { DateRangeFilter, EMPTY_RANGE, type DateRange } from '../components/DateRangeFilter';
import { Skeleton } from '../components/Skeleton';
import { useAsync } from '../hooks';
import type { Invoice, Summary } from '../types';
import { CHART_COLORS, fmtMoney, nfmt, toNumber } from '../utils';

function StatCard({ label, children, sub, delay }: {
  label: string; children: React.ReactNode; sub?: React.ReactNode; delay: number;
}) {
  return (
    <Card delay={delay} className="flex flex-col gap-1">
      <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</span>
      <span className="font-display text-2xl text-slate-900 tabular-nums leading-tight">{children}</span>
      {sub && <span className="text-xs text-slate-400">{sub}</span>}
    </Card>
  );
}

function spendOverTime(invoices: Invoice[]) {
  const byMonth = new Map<string, number>();
  for (const i of invoices) {
    if (i.status !== 'clean' && i.status !== 'stored') continue;
    if (i.doc_type === 'credit_note' || !i.is_invoice) continue;
    if (!i.invoice_date) continue;                       // skip undated — no "unknown" bucket
    const month = i.invoice_date.slice(0, 7);
    byMonth.set(month, (byMonth.get(month) ?? 0) + toNumber(i.base_total));
  }
  return [...byMonth.entries()].sort().map(([month, value]) => ({ month, value }));
}

export function Overview() {
  const [range, setRange] = useState<DateRange>(EMPTY_RANGE);
  const summaryQ = useAsync<Summary>((s) => api.summary(range, s), [range.from, range.to]);
  const invoicesQ = useAsync<Invoice[]>((s) => api.invoices(undefined, range, s), [range.from, range.to]);
  const s = summaryQ.data;

  if (summaryQ.error) return <ErrorBanner message={summaryQ.error} />;
  if (invoicesQ.error) return <ErrorBanner message={invoicesQ.error} />;

  const cur = s?.base_currency ?? '';
  const counted = s?.invoices_counted ?? 0;
  const total = toNumber(s?.total_spend);
  const avg = counted > 0 ? total / counted : 0;
  const catData = s ? Object.entries(s.by_category).map(([name, v]) => ({ name, value: toNumber(v) })).sort((a, b) => b.value - a.value) : [];
  const vendorData = s ? Object.entries(s.by_vendor).map(([name, v]) => ({ name, value: toNumber(v) })).sort((a, b) => b.value - a.value) : [];
  const topCategory = catData[0]?.name ?? '—';
  const timeData = invoicesQ.data ? spendOverTime(invoicesQ.data) : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl">Overview</h1>
          <p className="text-sm text-slate-500 mt-1">Reconciled spend{range.from || range.to ? ' for the selected period' : ' across all processed documents'}.</p>
        </div>
        <DateRangeFilter value={range} onChange={setRange} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {!s ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)
        ) : (
          <>
            <StatCard label="Total spend" delay={0}>
              <span className="text-sm font-semibold text-slate-400 mr-1.5">{cur}</span><CountUp value={total} decimals={2} />
            </StatCard>
            <StatCard label="Invoices" delay={0.04}><CountUp value={counted} /></StatCard>
            <StatCard label="Avg / invoice" delay={0.08}>
              <span className="text-sm font-semibold text-slate-400 mr-1.5">{cur}</span><CountUp value={avg} decimals={2} />
            </StatCard>
            <StatCard label="Needs review" delay={0.12}
              sub={`${fmtMoney(s.pending_review_excluded, cur)} excluded`}>
              <CountUp value={s.needs_review_count} />
            </StatCard>
            <StatCard label="Top category" delay={0.16}>
              <span className="text-lg">{topCategory}</span>
            </StatCard>
          </>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="h-72">
          <h2 className="font-display text-sm mb-3">Spend over time</h2>
          <ResponsiveContainer width="100%" height="85%">
            <AreaChart data={timeData} margin={{ left: 4, right: 12, top: 4, bottom: 0 }}>
              <defs>
                <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#059669" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="#059669" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={nfmt} tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={40} />
              <Tooltip formatter={(v: number) => fmtMoney(v, cur)} contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }} />
              <Area type="monotone" dataKey="value" stroke="#059669" strokeWidth={2} fill="url(#g)" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card className="h-72">
          <h2 className="font-display text-sm mb-3">By category</h2>
          <div className="flex items-center gap-3 h-[85%]">
            <ResponsiveContainer width="52%" height="100%">
              <PieChart>
                <Pie data={catData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={82} paddingAngle={2} stroke="none">
                  {catData.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => fmtMoney(v, cur)} contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
            <ul className="flex-1 min-w-0 space-y-1.5 pr-1 overflow-auto max-h-full">
              {catData.map((d, i) => (
                <li key={d.name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                    <span className="truncate text-slate-600">{d.name}</span>
                  </span>
                  <span className="tabular-nums text-slate-500 shrink-0">{fmtMoney(d.value, cur)}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>
      </div>

      <Card className="h-72">
        <h2 className="font-display text-sm mb-3">By vendor</h2>
        <ResponsiveContainer width="100%" height="85%">
          <BarChart data={vendorData} margin={{ left: 4, right: 12, top: 4, bottom: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={nfmt} tick={{ fontSize: 12, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={40} />
            <Tooltip formatter={(v: number) => fmtMoney(v, cur)} contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }} cursor={{ fill: '#f1f5f9' }} />
            <Bar dataKey="value" fill="#059669" radius={[6, 6, 0, 0]} maxBarSize={48} />
          </BarChart>
        </ResponsiveContainer>
      </Card>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return <div className="bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium">{message}</div>;
}
