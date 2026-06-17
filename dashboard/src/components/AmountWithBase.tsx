import type { Money } from '../types';
import { fmtMoney } from '../utils';
import { MoneyText } from './MoneyText';

/**
 * Native invoice amount as the primary value (it's what's on the document), with
 * a small muted base-currency equivalent beneath — shown ONLY when the currency
 * differs from the base, so USD invoices don't get a redundant "≈ USD" line.
 */
export function AmountWithBase({ total, currency, baseTotal, baseCurrency, size = 'lg', align = 'left' }: {
  total: Money;
  currency?: string | null;
  baseTotal?: Money | null;
  baseCurrency?: string | null;
  size?: 'lg' | 'sm';
  align?: 'left' | 'right';
}) {
  const showBase = !!currency && !!baseCurrency && currency !== baseCurrency && baseTotal != null;
  const primary = size === 'lg' ? 'text-lg font-semibold text-slate-900' : 'text-sm font-medium text-slate-700';
  return (
    <div className={align === 'right' ? 'text-right' : ''}>
      <MoneyText value={total} currency={currency ?? undefined} className={`block ${primary}`} />
      {showBase && (
        <span className="block text-xs text-slate-400 tnum" title={`Converted to ${baseCurrency}`}>
          ≈ {fmtMoney(baseTotal, baseCurrency!)}
        </span>
      )}
    </div>
  );
}
