import { fmtMoney } from '../utils';

export function MoneyText({ value, currency, className = '' }: {
  value: string | number | null | undefined;
  currency?: string;
  className?: string;
}) {
  return <span className={`tnum font-num ${className}`}>{fmtMoney(value, currency)}</span>;
}
