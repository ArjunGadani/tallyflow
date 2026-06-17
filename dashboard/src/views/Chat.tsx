// Full-page chat (the /chat route + sidebar entry). Reuses the same conversation
// and module-level store as the floating dock, so history is shared between them.
import { Sparkles } from 'lucide-react';
import { ChatConversation } from '../components/chat/ChatConversation';

export function Chat() {
  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center gap-2 mb-5">
        <span className="w-8 h-8 rounded-xl bg-emerald-50 grid place-items-center text-emerald-600">
          <Sparkles size={18} />
        </span>
        <div>
          <h1 className="font-display text-xl">TallyChat</h1>
          <p className="text-sm text-slate-400">Grounded, read-only answers about your invoices and spend.</p>
        </div>
      </div>
      <div className="relative h-[70vh] bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
        <ChatConversation />
      </div>
    </div>
  );
}
