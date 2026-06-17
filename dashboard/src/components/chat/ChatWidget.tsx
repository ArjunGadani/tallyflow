// Persistent floating dock — mounted once in Layout (outside <Outlet/>) so the
// conversation survives navigation. Cmd/Ctrl-K toggles; Esc closes.
import { AnimatePresence, motion } from 'framer-motion';
import { MessageCircle, Plus, Sparkles, X } from 'lucide-react';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { chatStore } from '../../chatStore';
import { ChatConversation } from './ChatConversation';

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const h = () => setReduced(mq.matches);
    mq.addEventListener('change', h);
    return () => mq.removeEventListener('change', h);
  }, []);
  return reduced;
}

function Header() {
  return (
    <div className="flex items-center gap-2 px-3.5 py-3 border-b border-slate-200">
      <span className="w-6 h-6 rounded-lg bg-emerald-50 grid place-items-center text-emerald-600">
        <Sparkles size={15} />
      </span>
      <span className="font-display text-sm flex-1">TallyChat</span>
      <button onClick={() => chatStore.clear()} aria-label="New chat"
        className="text-slate-400 hover:text-slate-600 p-1"><Plus size={16} /></button>
      <button onClick={() => chatStore.close()} aria-label="Close assistant"
        className="text-slate-400 hover:text-slate-600 p-1"><X size={16} /></button>
    </div>
  );
}

export function ChatWidget() {
  const state = useSyncExternalStore(chatStore.subscribe, chatStore.getSnapshot);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const editable = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA'
        || t.tagName === 'SELECT' || t.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        if (editable) return;            // don't hijack typing in any field
        e.preventDefault();
        chatStore.toggle();
      } else if (e.key === 'Escape' && chatStore.getSnapshot().open) {
        chatStore.close();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const panelMotion = reduced
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } }
    : { initial: { opacity: 0, scale: 0.96, y: 12 }, animate: { opacity: 1, scale: 1, y: 0 }, exit: { opacity: 0, scale: 0.96, y: 12 } };

  return (
    <>
      <AnimatePresence>
        {state.open && (
          <motion.div {...panelMotion} transition={{ duration: 0.18, ease: 'easeOut' }}
            style={{ transformOrigin: 'bottom right' }}
            role="dialog" aria-label="TallyChat assistant"
            className="fixed z-50 bg-white shadow-xl border border-slate-200 flex flex-col
                       inset-0 rounded-none
                       md:inset-auto md:bottom-6 md:right-6 md:w-[400px] md:h-[600px] md:max-h-[80vh] md:rounded-2xl">
            <Header />
            <ChatConversation />
          </motion.div>
        )}
      </AnimatePresence>

      {!state.open && (
        <button onClick={() => chatStore.open()} aria-label="Open TallyChat assistant" aria-expanded={false}
          className="fixed z-40 bottom-6 right-6 h-12 px-4 rounded-full bg-emerald-600 text-white shadow-lg
                     flex items-center gap-2 text-sm font-medium hover:bg-emerald-700 transition-colors">
          <MessageCircle size={18} /> Ask TallyChat
        </button>
      )}
    </>
  );
}
