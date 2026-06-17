import { Activity, FileText, History, LayoutDashboard, MessageCircle, ShieldCheck, UploadCloud } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { api } from '../api';
import { ChatWidget } from './chat/ChatWidget';
import { Logo } from './Logo';

const LINKS: Array<[string, string, LucideIcon]> = [
  ['/', 'Overview', LayoutDashboard],
  ['/activity', 'Activity', Activity],
  ['/invoices', 'Invoices', FileText],
  ['/review', 'Review', ShieldCheck],
  ['/upload', 'Upload', UploadCloud],
  ['/chat', 'Ask TallyChat', MessageCircle],
  ['/runs', 'Scheduled', History],
];

export function Layout() {
  // Live count of items needing attention -> red badge on Review (polled).
  const [reviewCount, setReviewCount] = useState(0);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const c = await api.reviewCount();
        if (active) setReviewCount(c.total || 0);
      } catch {
        /* leave last known count on transient errors */
      }
    };
    void load();
    const id = window.setInterval(load, 7000);
    return () => { active = false; clearInterval(id); };
  }, []);

  return (
    <div className="min-h-screen flex bg-slate-50">
      <aside className="w-60 shrink-0 hidden md:flex flex-col gap-1 px-4 py-6 border-r border-slate-200 bg-white sticky top-0 h-screen">
        <div className="flex items-center gap-2.5 px-3 mb-8">
          <Logo size={28} />
          <span className="font-display text-lg">TallyFlow</span>
        </div>
        {LINKS.map(([to, label, Icon]) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive ? 'bg-emerald-50 text-emerald-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`
            }
          >
            <Icon size={18} strokeWidth={2} />
            <span className="flex-1">{label}</span>
            {to === '/review' && reviewCount > 0 && (
              <span className="min-w-[20px] h-5 px-1.5 grid place-items-center rounded-full bg-rose-500 text-white text-xs font-bold tnum">
                {reviewCount}
              </span>
            )}
          </NavLink>
        ))}
        <div className="mt-auto px-3 text-xs text-slate-400">Accounts-payable automation</div>
      </aside>
      <main className="flex-1 px-5 md:px-10 py-8 max-w-6xl w-full mx-auto">
        <Outlet />
      </main>
      {/* Persistent dock — outside <main>/<Outlet> so the conversation survives navigation. */}
      <ChatWidget />
    </div>
  );
}
