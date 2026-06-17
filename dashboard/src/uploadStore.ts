// ---------------------------------------------------------------------------
// Upload store — module-level so upload state SURVIVES navigation and browser
// tab switches (the Upload view's local state used to vanish on unmount). Files
// are processed one-by-one through the live pipeline; in-flight uploads keep
// updating the store even if the Upload view isn't mounted.
// ---------------------------------------------------------------------------
import { api } from './api';
import type { IngestResponse } from './types';

export type UploadItem = {
  id: string;
  name: string;
  status: 'processing' | 'done' | 'error';
  result?: IngestResponse;
  error?: string;
};

type State = { items: UploadItem[]; busy: boolean };

let state: State = { items: [], busy: false };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const setState = (patch: Partial<State>) => { state = { ...state, ...patch }; emit(); };

let seq = 0;
const uid = () => `u${Date.now()}_${seq++}`;

const patchItem = (id: string, p: Partial<UploadItem>) =>
  setState({ items: state.items.map((it) => (it.id === id ? { ...it, ...p } : it)) });

export const uploadStore = {
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
  getSnapshot(): State { return state; },
  clear() { if (!state.busy) setState({ items: [] }); },

  /** Process every selected file sequentially (gentle on the backend + LLM). */
  async ingest(files: File[]) {
    const accepted = Array.from(files).filter(Boolean);
    if (!accepted.length) return;
    const pending: UploadItem[] = accepted.map((f) => ({ id: uid(), name: f.name, status: 'processing' }));
    setState({ items: [...pending, ...state.items], busy: true });
    for (let i = 0; i < accepted.length; i++) {
      try {
        const result = await api.ingest(accepted[i], 'upload');
        patchItem(pending[i].id, { status: 'done', result });
      } catch (e) {
        patchItem(pending[i].id, { status: 'error', error: (e as Error).message });
      }
    }
    setState({ busy: false });
  },
};
