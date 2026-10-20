"use client";

import { useState } from "react";
import { Gate } from "@/components/AppShell";
import { useSession } from "@/components/SessionProvider";
import { useToast } from "@/components/Toast";

interface Member {
  id: string;
  email: string;
  role: string;
}

const ROLES = ["org_admin", "analyst", "auditor", "read_only"];

export default function AdminPage() {
  const { me } = useSession();
  const toast = useToast();
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");

  // In production these call backend org-management endpoints. The roles map to
  // the RBAC matrix enforced server-side; this UI assigns them.
  function invite() {
    if (!email.trim()) return;
    setMembers((m) => [
      { id: crypto.randomUUID(), email: email.trim(), role },
      ...m,
    ]);
    toast(`Invited ${email.trim()} as ${role}`, "success");
    setEmail("");
  }

  function changeRole(id: string, newRole: string) {
    setMembers((m) => m.map((x) => (x.id === id ? { ...x, role: newRole } : x)));
    toast("Role updated", "success");
  }

  function remove(id: string) {
    setMembers((m) => m.filter((x) => x.id !== id));
    toast("Member removed", "info");
  }

  return (
    <Gate role="org_admin">
      <h1 className="text-2xl font-bold">Organization</h1>
      <p className="mt-1 text-muted">
        Manage members and roles for tenant{" "}
        <span className="font-mono text-accent">{me?.tenant_id}</span>.
      </p>

      <div className="mt-5 flex flex-wrap gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="member@company.com"
          className="flex-1 rounded-lg border border-white/10 bg-surface px-4 py-2.5 outline-none ring-accent/40 focus:ring-2"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="rounded-lg border border-white/10 bg-surface px-3 py-2.5 text-sm outline-none"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          onClick={invite}
          disabled={!email.trim()}
          className="rounded-lg bg-accent px-5 py-2.5 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
        >
          Invite
        </button>
      </div>

      <div className="mt-6 rounded-xl border border-white/8 bg-surface/40">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-muted">
            <tr className="border-b border-white/8">
              <th className="px-4 py-3">Member</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {members.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-muted">
                  No members yet. Invite your team above.
                </td>
              </tr>
            ) : (
              members.map((m) => (
                <tr key={m.id} className="border-b border-white/5 last:border-0">
                  <td className="px-4 py-3">{m.email}</td>
                  <td className="px-4 py-3">
                    <select
                      value={m.role}
                      onChange={(e) => changeRole(m.id, e.target.value)}
                      className="rounded-md border border-white/10 bg-base px-2 py-1 text-xs outline-none"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => remove(m.id)}
                      className="text-xs text-red-400 hover:underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-xs text-muted">
        Roles map to the server-enforced RBAC matrix (org_admin, analyst, auditor,
        read_only). Member persistence is wired to a backend org API in production.
      </p>
    </Gate>
  );
}
