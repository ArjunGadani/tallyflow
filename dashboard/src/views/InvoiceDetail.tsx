import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api';
import { Card } from '../components/Card';
import { ConfidenceRing } from '../components/ConfidenceRing';
import { FlowTimeline } from '../components/FlowTimeline';
import { MoneyText } from '../components/MoneyText';
import { Skeleton } from '../components/Skeleton';
import { StatusBadge } from '../components/StatusBadge';
import { useAsync } from '../hooks';
import type { Invoice } from '../types';
import { fmtDate } from '../utils';

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-bold text-slate-400 uppercase tracking-wide">{label}</div>
      <div className="font-semibold text-slate-700">{children}</div>
    </div>
  );
}

export function InvoiceDetail() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const q = useAsync<Invoice>((s) => api.invoice(id, s), [id]);
  const [deleting, setDeleting] = useState(false);

  const remove = async () => {
    if (!window.confirm('Delete this invoice and all its data (line items, tax lines, events, original)? This cannot be undone.')) return;
    setDeleting(true);
    try {
      await api.deleteInvoice(id);
      nav('/invoices');
    } catch (e) {
      alert((e as Error).message);
      setDeleting(false);
    }
  };

  if (q.loading) return <Skeleton className="h-96" />;
  if (q.error || !q.data) {
    return (
      <div className="space-y-4">
        <div className="bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium">{q.error ?? 'Not found'}</div>
        <Link to="/invoices" className="text-emerald-700 text-sm font-medium">← Back to invoices</Link>
      </div>
    );
  }
  const inv = q.data;

  return (
    <div className="space-y-6">
      <Link to="/invoices" className="text-emerald-700 text-sm font-medium">← Invoices</Link>
      <div className="flex flex-wrap items-center gap-4 justify-between">
        <h1 className="font-display text-2xl">{inv.vendor_name}</h1>
        <div className="flex items-center gap-3">
          <ConfidenceRing value={inv.confidence_overall} size={52} />
          <StatusBadge status={inv.status} />
          <button onClick={remove} disabled={deleting} title="Delete invoice"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-rose-600 ring-1 ring-rose-200 hover:bg-rose-50 disabled:opacity-50 transition-colors">
            <Trash2 size={15} /> {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <Field label="Invoice no.">{inv.invoice_number || '—'}</Field>
              <Field label="Date">{fmtDate(inv.invoice_date)}</Field>
              <Field label="Due">{fmtDate(inv.due_date)}</Field>
              <Field label="Category">{inv.category || '—'}</Field>
              <Field label="Doc type">{inv.doc_type}</Field>
              <Field label="Version">v{inv.version}</Field>
              <Field label="Total"><MoneyText value={inv.total} currency={inv.currency} /></Field>
              <Field label="Base total"><MoneyText value={inv.base_total} currency={inv.base_currency} /></Field>
              <Field label="FX rate">{inv.fx_rate ?? '—'}{inv.fx_date ? ` @ ${fmtDate(inv.fx_date)}` : ''}</Field>
            </div>
            {(inv.supersedes_id || inv.credit_of_id || inv.status === 'superseded') && (
              <div className="mt-4 flex flex-wrap gap-2 text-sm">
                {inv.supersedes_id && <Badge>Supersedes {inv.supersedes_id.slice(0, 8)}</Badge>}
                {inv.credit_of_id && <Badge>Credit of {inv.credit_of_id.slice(0, 8)}</Badge>}
                {inv.status === 'superseded' && <Badge>Superseded by a newer version</Badge>}
              </div>
            )}
          </Card>

          <Card>
            <h2 className="font-display text-sm mb-3">Line items</h2>
            <table className="w-full text-sm">
              <thead><tr className="text-slate-400 text-left">
                <th className="py-1">Description</th><th>Qty</th><th>Unit</th><th className="text-right">Amount</th>
              </tr></thead>
              <tbody>
                {inv.line_items.map((li, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="py-2">{li.description}</td>
                    <td>{String(li.quantity ?? '')}</td>
                    <td><MoneyText value={li.unit_price} /></td>
                    <td className="text-right"><MoneyText value={li.amount} /></td>
                  </tr>
                ))}
                {inv.line_items.length === 0 && <tr><td className="py-2 text-slate-400" colSpan={4}>No line items</td></tr>}
              </tbody>
            </table>
            {inv.tax_lines.length > 0 && (
              <div className="mt-4">
                <h3 className="font-medium text-slate-700 mb-2 text-sm">Tax breakdown</h3>
                {inv.tax_lines.map((t, i) => (
                  <div key={i} className="flex justify-between text-sm border-t border-slate-100 py-1">
                    <span>{t.label} {t.rate ? `(${t.rate}%)` : ''}</span>
                    <MoneyText value={t.amount} />
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <h2 className="font-display text-sm mb-3">Processing flow</h2>
            <FlowTimeline events={inv.events} animated={false} />
          </Card>
          <Card>
            <h2 className="font-display text-sm mb-3">Original</h2>
            {inv.files.length ? (
              <div className="rounded-2xl bg-primary-50 p-4 text-sm">
                <div className="font-bold text-slate-700">{inv.files[0].original_name}</div>
                <div className="text-slate-400">{inv.files[0].mime} · {inv.files[0].pages ?? '?'} page(s)</div>
                <div className="text-slate-400 break-all mt-1">{inv.files[0].storage_path}</div>
              </div>
            ) : <p className="text-slate-400 text-sm">No original on file.</p>}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="px-2.5 py-0.5 rounded-md bg-slate-100 text-slate-700 ring-1 ring-slate-200 text-xs font-medium">{children}</span>;
}
