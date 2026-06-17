// Inline render of a grounded tool result. The values come from the backend's
// typed `result` payload (built from a tool dict, never from prose), so a chart
// here can't disagree with reconcile_summary.
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { Link } from 'react-router-dom';
import type { ChatResultData, InvoiceStatus } from '../../types';
import { CHART_COLORS, fmtMoney, toNumber } from '../../utils';
import { MoneyText } from '../MoneyText';
import { StatusBadge } from '../StatusBadge';

function SummaryCard({ data }: { data: Extract<ChatResultData, { kind: 'summary' }>['data'] }) {
  const cur = data.base_currency;
  const cats = Object.entries(data.by_category || {})
    .map(([name, v]) => ({ name, value: toNumber(v) }))
    .sort((a, b) => b.value - a.value);
  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="grid grid-cols-2 gap-3 mb-2">
        <Stat label="Total spend"><MoneyText value={data.total_spend} currency={cur} className="text-base font-semibold" /></Stat>
        <Stat label="Invoices">{data.invoices_counted}</Stat>
        {toNumber(data.credits_total) > 0 && (
          <Stat label="Credits"><MoneyText value={data.credits_total} currency={cur} /></Stat>
        )}
        {data.needs_review_count > 0 && (
          <Stat label="Pending review">
            <MoneyText value={data.pending_review_excluded} currency={cur} /> · {data.needs_review_count}
          </Stat>
        )}
      </div>
      {cats.length > 0 && (
        <div className="flex items-center gap-3">
          <div className="w-24 h-24 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={cats} dataKey="value" nameKey="name" innerRadius={22} outerRadius={42} paddingAngle={2}>
                  {cats.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => fmtMoney(v, cur)}
                         contentStyle={{ borderRadius: 12, border: '1px solid #e2e8f0', fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-1 text-xs">
            {cats.slice(0, 5).map((c, i) => (
              <li key={c.name} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-sm" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                <span className="flex-1 truncate text-slate-600">{c.name}</span>
                <MoneyText value={c.value} className="text-slate-500" />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-sm text-slate-800 tnum">{children}</div>
    </div>
  );
}

function InvoiceRow({ row }: { row: Record<string, unknown> }) {
  const id = String(row.id ?? '');
  const num = (row.invoice_number as string) || id;
  const vendor = (row.vendor_name as string) || '';
  const status = row.status as InvoiceStatus;  // StatusBadge has a safe fallback for unknowns
  const inner = (
    <div className="flex items-center gap-2 px-3 py-2 text-sm">
      <span className="font-medium text-slate-700">{num}</span>
      {vendor && <span className="text-slate-400 truncate flex-1">{vendor}</span>}
      <MoneyText value={(row.total as string) ?? null} currency={(row.currency as string) || undefined} className="text-slate-600" />
      {row.status ? <StatusBadge status={status} /> : null}
    </div>
  );
  return id ? (
    <Link to={`/invoice/${id}`} className="block rounded-lg hover:bg-slate-50 transition-colors">{inner}</Link>
  ) : inner;
}

export function InlineResultCard({ result }: { result: ChatResultData }) {
  if (result.kind === 'summary') return <SummaryCard data={result.data} />;
  if (result.kind === 'invoice') {
    const inv = result.data;
    return (
      <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/60 divide-y divide-slate-100">
        <InvoiceRow row={inv as Record<string, unknown>} />
      </div>
    );
  }
  // invoice_list
  const rows = result.data || [];
  if (!rows.length) return null;
  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-slate-50/60 divide-y divide-slate-100">
      {rows.slice(0, 10).map((r, i) => <InvoiceRow key={i} row={r} />)}
      {result.truncated && <div className="px-3 py-1.5 text-xs text-slate-400">More results — ask to narrow.</div>}
    </div>
  );
}
