import { useAuth } from "../hooks/useAuth";

interface Props {
  connected: boolean;
}

export default function Navbar({ connected }: Props) {
  const { user, logout } = useAuth();

  return (
    <header className="border-b border-border bg-card px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-accent">predic-bot</span>
        <span className={`badge ${connected ? "badge-success" : "badge-danger"}`}>
          {connected ? "LIVE" : "OFFLINE"}
        </span>
      </div>
      <div className="flex items-center gap-4">
        <span className="text-xs text-muted">{user?.email}</span>
        <button onClick={logout} className="text-xs text-muted hover:text-slate-100 transition-colors">
          Logout
        </button>
      </div>
    </header>
  );
}
