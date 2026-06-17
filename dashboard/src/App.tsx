import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Logo } from './components/Logo';
import { api } from './api';
import { Layout } from './components/Layout';
import { Activity } from './views/Activity';
import { Chat } from './views/Chat';
import { InvoiceDetail } from './views/InvoiceDetail';
import { Invoices } from './views/Invoices';
import { Overview } from './views/Overview';
import { ReviewQueue } from './views/ReviewQueue';
import { Runs } from './views/Runs';
import { Upload } from './views/Upload';

// Cloud Run scales to zero, so the first request can cold-start. Poll /healthz
// until the backend answers before showing the app.
function useBackendReady() {
  const [ready, setReady] = useState(false);
  const [waking, setWaking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let tries = 0;
    const poll = async () => {
      try {
        await api.health();
        if (!cancelled) setReady(true);
      } catch {
        if (cancelled) return;
        setWaking(true);
        tries += 1;
        window.setTimeout(poll, Math.min(3000, 400 * tries));
      }
    };
    void poll();
    return () => { cancelled = true; };
  }, []);

  return { ready, waking };
}

function BootScreen({ waking }: { waking: boolean }) {
  return (
    <div className="min-h-screen grid place-items-center bg-slate-50">
      <div className="text-center">
        <div className="flex justify-center mb-5"><Logo size={44} /></div>
        <div className="font-display text-xl">TallyFlow</div>
        <div className="flex items-center justify-center gap-2 text-slate-400 mt-3 text-sm">
          <Loader2 size={15} className="animate-spin" />
          {waking ? 'Waking up the server…' : 'Starting…'}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { ready, waking } = useBackendReady();
  if (!ready) return <BootScreen waking={waking} />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Overview />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/invoices" element={<Invoices />} />
          <Route path="/invoice/:id" element={<InvoiceDetail />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/runs" element={<Runs />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
