import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle2, Loader2, UploadCloud, XCircle } from 'lucide-react';
import { useRef, useState, useSyncExternalStore } from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../components/Card';
import { FlowTimeline } from '../components/FlowTimeline';
import { MoneyText } from '../components/MoneyText';
import { StatusBadge } from '../components/StatusBadge';
import { uploadStore, type UploadItem } from '../uploadStore';
import { BRANCH_LABEL } from '../utils';

function ResultBody({ item }: { item: UploadItem }) {
  if (item.status === 'processing') {
    return (
      <div className="flex items-center gap-2 text-emerald-700 text-sm font-medium">
        <Loader2 size={16} className="animate-spin" /> Processing {item.name}…
      </div>
    );
  }
  if (item.status === 'error') {
    return (
      <div className="flex items-start gap-2 text-rose-700 text-sm">
        <XCircle size={16} className="mt-0.5 shrink-0" />
        <div><span className="font-medium">{item.name}</span> — {item.error}</div>
      </div>
    );
  }
  const r = item.result!;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 uppercase tracking-wide">
            <CheckCircle2 size={14} className="text-emerald-600" /> {item.name}
          </div>
          <div className="font-display text-lg text-emerald-700">{BRANCH_LABEL[r.branch] ?? r.branch}</div>
          {r.message && <div className="text-sm text-slate-500">{r.message}</div>}
        </div>
        {r.invoice && (
          <div className="flex items-center gap-3">
            <MoneyText value={r.invoice.total} currency={r.invoice.currency} className="text-lg font-semibold text-slate-900" />
            <StatusBadge status={r.invoice.status} />
          </div>
        )}
      </div>
      <FlowTimeline events={r.flow} animated />
      {r.invoice && (
        <Link to={`/invoice/${r.invoice.id}`}
          className="inline-block mt-4 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium transition-colors">
          View invoice →
        </Link>
      )}
    </>
  );
}

export function Upload() {
  const [dragging, setDragging] = useState(false);
  const { items, busy } = useSyncExternalStore(uploadStore.subscribe, uploadStore.getSnapshot);
  const inputRef = useRef<HTMLInputElement>(null);

  const send = (files: FileList | File[] | null) => {
    if (files && (files as FileList).length) void uploadStore.ingest(Array.from(files as FileList));
  };
  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    send(e.dataTransfer.files);
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl">Upload</h1>
        {items.length > 0 && (
          <button onClick={() => uploadStore.clear()} disabled={busy}
            className="text-sm font-medium text-slate-500 hover:text-slate-700 disabled:opacity-40">
            Clear
          </button>
        )}
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-2xl border-2 border-dashed p-12 text-center transition-colors ${
          dragging ? 'border-emerald-500 bg-emerald-50' : 'border-slate-300 bg-white hover:border-slate-400'
        }`}
      >
        <UploadCloud size={32} className="mx-auto text-slate-400 mb-3" strokeWidth={1.5} />
        <div className="font-display text-base">Drop invoices here, or click to choose</div>
        <div className="text-sm text-slate-400 mt-1">One or many — PDF or image, processed through the live pipeline</div>
        <input ref={inputRef} type="file" accept=".pdf,image/*" multiple className="hidden"
          onChange={(e) => { send(e.target.files); e.target.value = ''; }} />
      </div>

      {busy && (
        <div className="text-sm text-slate-500">
          Processing {items.filter((i) => i.status === 'processing').length} of {items.length}…
        </div>
      )}

      <AnimatePresence initial={false}>
        {items.map((item) => (
          <motion.div key={item.id} layout
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}>
            <Card><ResultBody item={item} /></Card>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
