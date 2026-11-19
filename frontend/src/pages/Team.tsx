import { useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
import { api, fmtDate } from "../api";
import { Badge, toast, useAsync } from "../components/ui";
import { getConfig } from "../auth";

export default function Team({ admin }: { admin: boolean }) {
  const t = useAsync(() => api.get("/team"), []);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("estimator");
  if (!t.data) return <p className="text-steel-500">Loading…</p>;
  const act = async (fn: () => Promise<any>, msg = "Saved") => { try { await fn(); toast(msg); t.reload(); } catch (e: any) { toast(e.message); } };
  const invite = (e: React.FormEvent) => {
    e.preventDefault();
    act(async () => { const r = await api.post("/team/invites", { email, role }); setEmail(""); return r; },
      t.data.email_enabled ? `Invitation emailed to ${email}` : `Invited ${email}. Outgoing email isn't set up, so tell them to create an account on this website with that address.`);
  };
  return (
    <div className="space-y-4">
      {admin && <form onSubmit={invite} className="card flex flex-wrap items-end gap-3 p-4">
        <label className="text-sm">Invite by email (any provider)<input className="input mt-1 !w-72" type="email" required placeholder="name@company.com" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="text-sm">Role<select className="input mt-1 !w-36" value={role} onChange={(e) => setRole(e.target.value)}><option value="estimator">Estimator</option><option value="admin">Admin</option></select></label>
        <button className="btn btn-primary"><UserPlus size={14} /> Invite</button>
        <p className="w-full text-xs text-steel-500">They create an account with that email address{getConfig().microsoft ? " or sign in with Microsoft" : ""} and join your shop automatically. Admins can change settings, rates and email accounts.</p>
      </form>}
      <div className="card overflow-x-auto"><table className="w-full">
        <thead><tr><th className="th">Name</th><th className="th">Email</th><th className="th">Sign-in</th><th className="th">Role</th><th className="th">Last sign-in</th><th className="th">Status</th></tr></thead>
        <tbody>{t.data.users.map((u: any) => <tr key={u.id}>
          <td className="td font-medium">{u.name}{u.me && <span className="ml-1 text-xs text-steel-400">(you)</span>}</td><td className="td">{u.email}</td><td className="td text-xs">{u.sign_in}</td>
          <td className="td">{admin && !u.me ? <select className="input !w-auto !py-0.5 text-xs" value={u.role} onChange={(e) => act(() => api.put(`/team/users/${u.id}`, { role: e.target.value }))}>
            <option value="estimator">Estimator</option><option value="admin">Admin</option></select> : <span className="capitalize">{u.role}</span>}</td>
          <td className="td text-xs">{fmtDate(u.last_login_at)}</td>
          <td className="td">{admin && !u.me ? <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={u.active} onChange={(e) => act(() => api.put(`/team/users/${u.id}`, { active: e.target.checked }))} /> Active</label>
            : u.active ? <Badge tone="green">Active</Badge> : <Badge>Disabled</Badge>}</td></tr>)}
          {t.data.invites.map((i: any) => <tr key={i.id} className="bg-steel-50">
            <td className="td text-steel-500">Invited by {i.invited_by}</td><td className="td">{i.email}</td><td className="td text-xs">—</td><td className="td capitalize">{i.role}</td><td className="td text-xs">sent {fmtDate(i.created_at)}</td>
            <td className="td"><Badge tone="amber">Pending</Badge>{admin && <button className="ml-2 text-red-700" aria-label="Cancel invitation" onClick={() => act(() => api.del(`/team/invites/${i.id}`), "Invitation cancelled")}><Trash2 size={14} /></button>}</td></tr>)}
        </tbody></table></div>
    </div>
  );
}
