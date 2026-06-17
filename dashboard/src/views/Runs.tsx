import { useEffect, useState } from 'react';
import { api } from '../api';
import { Card } from '../components/Card';
import { Skeleton } from '../components/Skeleton';
import { useAsync } from '../hooks';
import type { Run } from '../types';
import { fmtDateTime } from '../utils';

export function Runs() {
  const q = useAsync<Run[]>((s) => api.runs(s), []);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [digest, setDigest] = useState<boolean | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api.getSettings().then((s) => { if (active) setDigest(s.digest_enabled); }).catch(() => {});
    return () => { active = false; };
  }, []);

  const run = async () => {
    setBusy(true); setMsg(null);
    try {
      await api.triggerRun();
      q.reload();
      setMsg('Run triggered.');
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleDigest = async () => {
    if (digest === null) return;
    const next = !digest;
    setDigestBusy(true); setDigest(next);            // optimistic
    try {
      const r = await api.setDigest(next);
      setDigest(r.digest_enabled);
    } catch (e) {
      setDigest(!next);                               // revert on failure
      setMsg((e as Error).message);
    } finally {
      setDigestBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl">Scheduled runs</h1>
          <p className="text-sm text-slate-500 mt-1 max-w-xl">
            Each row is one scheduled cycle: <b>poll the inbox → process new emails → send the Email + Slack digest</b>.
            Runs hourly via Cloud Scheduler. Manual dashboard uploads do <b>not</b> appear here — see Activity for those.
          </p>
        </div>
        <button onClick={run} disabled={busy}
          className="shrink-0 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium disabled:opacity-50 transition-colors">
          {busy ? 'Running…' : 'Run inbox now'}
        </button>
      </div>

      {/* digest on/off — muting stops the hourly email + Slack; polling still runs */}
      <Card className="flex items-center justify-between p-4">
        <div>
          <div className="text-sm font-medium text-slate-800">Email + Slack digest</div>
          <div className="text-xs text-slate-500 mt-0.5">
            {digest === null ? 'Loading…'
              : digest ? 'On — a digest is sent after each hourly run.'
              : 'Off — hourly polling still runs, but no digest is sent.'}
          </div>
        </div>
        <button
          role="switch" aria-checked={digest === true} onClick={toggleDigest}
          disabled={digest === null || digestBusy}
          className={`relative inline-flex h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
            digest ? 'bg-emerald-600' : 'bg-slate-300'}`}>
          <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
            digest ? 'translate-x-5' : 'translate-x-0'}`} />
        </button>
      </Card>

      {msg && <div className="text-sm text-slate-500">{msg}</div>}

      {q.loading ? (
        <Skeleton className="h-32" />
      ) : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-left border-b border-slate-200">
                <th className="font-medium px-5 py-3">Started</th>
                <th className="font-medium px-5 py-3">Finished</th>
                <th className="font-medium px-5 py-3 text-right">Processed</th>
                <th className="font-medium px-5 py-3 text-right">Skipped</th>
                <th className="font-medium px-5 py-3 text-right">Failed</th>
              </tr>
            </thead>
            <tbody>
              {(q.data ?? []).map((r, i) => (
                <tr key={r.id ?? i} className="border-b border-slate-100 last:border-0">
                  <td className="px-5 py-3">{fmtDateTime(r.started_at)}</td>
                  <td className="px-5 py-3">{fmtDateTime(r.finished_at)}</td>
                  <td className="px-5 py-3 text-right font-medium text-emerald-700">{r.processed}</td>
                  <td className="px-5 py-3 text-right text-slate-500">{r.skipped}</td>
                  <td className="px-5 py-3 text-right text-rose-600">{r.failed}</td>
                </tr>
              ))}
              {(q.data ?? []).length === 0 && (
                <tr><td className="px-5 py-4 text-slate-400" colSpan={5}>No scheduled runs yet.</td></tr>
              )}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
