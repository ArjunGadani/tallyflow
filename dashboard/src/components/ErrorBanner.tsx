// Shared error banner (rose). Previously duplicated inline across views; chat
// reuses it too, so it lives here as one component.
export function ErrorBanner({ message, className = '' }: { message: string; className?: string }) {
  return (
    <div className={`bg-rose-50 text-rose-700 ring-1 ring-rose-200 rounded-xl p-4 text-sm font-medium ${className}`}>
      {message}
    </div>
  );
}
