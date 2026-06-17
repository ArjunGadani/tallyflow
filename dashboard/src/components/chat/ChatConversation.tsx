// The inner chat experience (message log + composer), shared by the floating
// dock and the /chat page. State lives in the module-level chatStore.
import { ArrowDown, Check, ChevronDown, Copy, RotateCcw, Send, Sparkles, Square } from 'lucide-react';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Link } from 'react-router-dom';
import { chatStore } from '../../chatStore';
import type { ChatMessage } from '../../types';
import { ErrorBanner } from '../ErrorBanner';
import { InlineResultCard } from './InlineResultCard';
import { Markdown } from './Markdown';

const SUGGESTED = [
  'What did we spend last month?',
  'Show spend by category',
  'Which invoices need review?',
  'Any duplicate invoices?',
  'Top vendors by spend',
];

/** invoice:<id> / events:<id> citations become deep links; the rest are labels. */
function SourceChips({ citations }: { citations: string[] }) {
  const seen = new Set<string>();
  const chips = citations.filter((c) => (seen.has(c) ? false : seen.add(c)));
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {chips.map((c) => {
        const m = /^(invoice|events):(.+)$/.exec(c);
        if (m) {
          return (
            <Link key={c} to={`/invoice/${m[2]}`}
              className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 hover:bg-emerald-100">
              {m[2]}
            </Link>
          );
        }
        return <span key={c} className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{c}</span>;
      })}
    </div>
  );
}

function HowIGotThis({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false);
  if (!msg.toolTrace?.length) return null;
  return (
    <div className="mt-2">
      <button onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600">
        <ChevronDown size={13} className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
        How I got this
      </button>
      {open && (
        <div className="mt-1 rounded-lg bg-slate-50 ring-1 ring-slate-200 p-2 text-xs text-slate-500 space-y-1">
          {msg.resolvedRange && (
            <div>Period: <span className="text-slate-700">{msg.resolvedRange.label}</span>
              {msg.resolvedRange.date_from && ` (${msg.resolvedRange.date_from} → ${msg.resolvedRange.date_to})`}</div>
          )}
          {msg.toolTrace.map((t, i) => (
            <div key={i} className="font-mono">
              {t.ok ? '✓' : '✗'} {t.name}{Object.keys(t.arguments).length ? `(${JSON.stringify(t.arguments)})` : '()'}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MessageActions({ msg }: { msg: ChatMessage }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!navigator.clipboard) return;            // no clipboard (non-secure ctx) → no false success
    try {
      await navigator.clipboard.writeText(msg.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard denied — leave the icon unchanged rather than fake success */
    }
  };
  return (
    <div className="flex items-center gap-2 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
      <button onClick={copy} className="text-slate-400 hover:text-slate-600" aria-label="Copy message">
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
    </div>
  );
}

function Bubble({ msg }: { msg: ChatMessage }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-slate-100 text-slate-800 px-3.5 py-2 text-sm">
          {msg.content}
        </div>
      </div>
    );
  }
  return (
    <div className="group max-w-[92%] text-sm text-slate-800">
      {msg.status === 'sending' ? (
        <div className="flex items-center gap-1 py-1 text-emerald-600" aria-label="Assistant is thinking">
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce motion-reduce:animate-none" />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce motion-reduce:animate-none [animation-delay:0.15s]" />
          <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce motion-reduce:animate-none [animation-delay:0.3s]" />
        </div>
      ) : msg.status === 'error' ? (
        <div className="space-y-2">
          <ErrorBanner message={msg.error || 'Something went wrong.'} />
          <button onClick={() => chatStore.retryLast()}
            className="flex items-center gap-1 text-xs text-emerald-700 hover:underline">
            <RotateCcw size={13} /> Retry
          </button>
        </div>
      ) : (
        <>
          <Markdown text={msg.content} />
          {msg.groundingOk === false && (
            <div className="mt-1.5 flex items-center gap-2 text-xs text-amber-700">
              <span>I couldn't verify that against the data.</span>
              <button onClick={() => chatStore.retryLast()} className="inline-flex items-center gap-1 hover:underline">
                <RotateCcw size={12} /> Retry
              </button>
            </div>
          )}
          {msg.result && <InlineResultCard result={msg.result} />}
          {msg.citations && <SourceChips citations={msg.citations} />}
          <HowIGotThis msg={msg} />
          <MessageActions msg={msg} />
        </>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6 gap-3">
      <div className="w-11 h-11 rounded-xl bg-emerald-50 grid place-items-center text-emerald-600">
        <Sparkles size={22} />
      </div>
      <div className="text-sm text-slate-500 max-w-xs">
        Ask about your spend, vendors, duplicates, or anything the pipeline processed.
        I'm read-only — I can't edit invoices.
      </div>
      <div className="flex flex-wrap justify-center gap-1.5 mt-1">
        {SUGGESTED.map((s) => (
          <button key={s} onClick={() => chatStore.send(s)}
            className="text-xs px-2.5 py-1 rounded-full bg-white ring-1 ring-slate-200 text-slate-600 hover:ring-emerald-300 hover:text-emerald-700">
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Composer({ busy }: { busy: boolean }) {
  const [text, setText] = useState('');
  const submit = () => {
    if (busy || !text.trim()) return;
    chatStore.send(text);
    setText('');
  };
  return (
    <div className="border-t border-slate-200 p-2.5 flex items-end gap-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
        }}
        rows={1}
        placeholder="Ask about your invoices…"
        className="flex-1 resize-none max-h-28 px-3 py-2 rounded-xl border border-slate-200 text-sm
                   focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-400"
      />
      {busy ? (
        <button onClick={() => chatStore.stop()} aria-label="Stop generating"
          className="shrink-0 w-9 h-9 grid place-items-center rounded-xl bg-slate-200 text-slate-600 hover:bg-slate-300">
          <Square size={15} />
        </button>
      ) : (
        <button onClick={submit} disabled={!text.trim()} aria-label="Send message"
          className="shrink-0 w-9 h-9 grid place-items-center rounded-xl bg-emerald-600 text-white
                     hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed">
          <Send size={15} />
        </button>
      )}
    </div>
  );
}

export function ChatConversation() {
  const state = useSyncExternalStore(chatStore.subscribe, chatStore.getSnapshot);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  useEffect(() => {
    if (atBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [state.messages, atBottom]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  };

  return (
    <div className="relative flex flex-col h-full min-h-0">
      <div ref={scrollRef} onScroll={onScroll}
        role="log" aria-live="polite" aria-relevant="additions text"
        className="flex-1 min-h-0 overflow-y-auto px-3.5 py-3 space-y-4">
        {state.messages.length === 0 ? <EmptyState />
          : state.messages.map((m) => <Bubble key={m.id} msg={m} />)}
      </div>
      {!atBottom && (
        <button onClick={() => { setAtBottom(true); }}
          className="absolute bottom-20 left-1/2 -translate-x-1/2 w-8 h-8 grid place-items-center rounded-full
                     bg-white shadow-md ring-1 ring-slate-200 text-slate-500 hover:text-slate-700"
          aria-label="Jump to latest">
          <ArrowDown size={15} />
        </button>
      )}
      <Composer busy={state.busy} />
    </div>
  );
}
