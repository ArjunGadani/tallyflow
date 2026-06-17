// ---------------------------------------------------------------------------
// TallyChat store — module-level (like uploadStore) so the conversation and the
// in-flight request SURVIVE navigation and dock open/close. History is in-memory
// only (no localStorage): avoids stale grounded data and PII at rest.
// ---------------------------------------------------------------------------
import { api, ApiError } from './api';
import type { ChatMessage, ChatRole } from './types';

type State = { open: boolean; messages: ChatMessage[]; busy: boolean };

let state: State = { open: false, messages: [], busy: false };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const setState = (patch: Partial<State>) => { state = { ...state, ...patch }; emit(); };

let seq = 0;
const uid = () => `c${Date.now()}_${seq++}`;
const now = () => new Date().toISOString();

let controller: AbortController | null = null;
let conversationId: string | null = null;

const patch = (id: string, p: Partial<ChatMessage>) =>
  setState({ messages: state.messages.map((m) => (m.id === id ? { ...m, ...p } : m)) });

/** Prior completed turns (text only) from a given message list, for context. */
function historyOf(msgs: ChatMessage[]): { role: ChatRole; content: string }[] {
  return msgs
    .filter((m) => m.status === 'complete' && m.content)
    .map((m) => ({ role: m.role, content: m.content }));
}

/** Send `userText` to the backend and stream the answer into a NEW assistant
 * bubble. Does not add a user message — the caller owns that, so retry can reuse
 * the existing user turn instead of duplicating it. */
async function dispatch(userText: string, history: { role: ChatRole; content: string }[]) {
  const assistantId = uid();
  setState({
    busy: true,
    messages: [...state.messages, { id: assistantId, role: 'assistant', content: '', status: 'sending', ts: now() }],
  });
  controller = new AbortController();
  try {
    const res = await api.chat(
      { message: userText, conversation_id: conversationId, history },
      controller.signal,
    );
    conversationId = res.conversation_id;
    patch(assistantId, {
      content: res.answer ?? '',
      status: 'complete',
      citations: res.citations,
      toolTrace: res.tool_trace,
      result: res.result,
      resolvedRange: res.resolved_range,
      groundingOk: res.grounding_ok,
      maxIterations: res.max_iterations_reached,
    });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') {
      // User pressed stop: keep whatever we have; drop the empty placeholder.
      setState({ messages: state.messages.filter((m) => m.id !== assistantId) });
    } else {
      const msg = e instanceof ApiError ? e.message : 'Something went wrong.';
      patch(assistantId, { status: 'error', error: msg });
    }
  } finally {
    controller = null;
    setState({ busy: false });
  }
}

export const chatStore = {
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
  getSnapshot(): State { return state; },

  open() { setState({ open: true }); },
  close() { setState({ open: false }); },
  toggle() { setState({ open: !state.open }); },

  send(text: string) {
    const t = text.trim();
    if (!t || state.busy) return;
    const history = historyOf(state.messages);
    setState({ messages: [...state.messages, { id: uid(), role: 'user', content: t, status: 'complete', ts: now() }] });
    void dispatch(t, history);
  },

  stop() { controller?.abort(); },

  retryLast() {
    if (state.busy) return;
    // Drop the errored assistant turn, then RE-ANSWER the existing last user
    // message (don't append a second copy). History is everything before it.
    const msgs = state.messages.filter((m) => m.status !== 'error');
    const idx = msgs.map((m) => m.role).lastIndexOf('user');
    if (idx === -1) return;
    setState({ messages: msgs });
    void dispatch(msgs[idx].content, historyOf(msgs.slice(0, idx)));
  },

  clear() {
    if (state.busy) return;
    conversationId = null;
    setState({ messages: [] });
  },
};
