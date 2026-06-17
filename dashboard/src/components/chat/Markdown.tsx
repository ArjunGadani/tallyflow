// Minimal, dependency-free, XSS-safe markdown for assistant messages. Renders
// React elements only (never dangerouslySetInnerHTML), so embedded HTML in
// invoice text can't execute. Supports bold, inline code, bullet/numbered lists.
import type { ReactNode } from 'react';

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Non-greedy so a bold/code span may contain a lone * or other markers,
  // e.g. "**$5 * 12 = $60**" renders bold instead of leaking literal asterisks.
  const re = /(\*\*(.+?)\*\*|`(.+?)`)/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) {
      nodes.push(<strong key={key++}>{m[2]}</strong>);
    } else if (m[3] !== undefined) {
      nodes.push(
        <code key={key++} className="px-1 py-0.5 rounded bg-slate-100 text-[0.85em]">{m[3]}</code>,
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''));
        i++;
      }
      blocks.push(
        <ul key={key++} className="list-disc pl-5 space-y-0.5">
          {items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}
        </ul>,
      );
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      blocks.push(
        <ol key={key++} className="list-decimal pl-5 space-y-0.5">
          {items.map((it, j) => <li key={j}>{renderInline(it)}</li>)}
        </ol>,
      );
      continue;
    }
    if (line.trim() === '') { i++; continue; }
    blocks.push(<p key={key++}>{renderInline(line)}</p>);
    i++;
  }
  return <div className="space-y-2 leading-relaxed">{blocks}</div>;
}
