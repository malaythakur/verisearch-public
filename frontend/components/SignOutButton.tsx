"use client";

import { useRouter } from "next/navigation";
import { useClerk } from "@clerk/nextjs";
import { useSession } from "@/components/SessionProvider";
import { CLERK_ENABLED } from "@/lib/clerk";

function ClerkAwareSignOut() {
  const router = useRouter();
  const { signOut: clerkSignOut } = useClerk();
  const { signOut } = useSession();

  return (
    <button
      onClick={async () => {
        signOut();
        try {
          await clerkSignOut();
        } catch {
          /* ignore */
        }
        router.replace("/login");
      }}
      className="rounded-md border border-white/10 px-2 py-1 transition hover:border-red-400 hover:text-red-400"
    >
      Sign out
    </button>
  );
}

function LocalSignOut() {
  const router = useRouter();
  const { signOut } = useSession();
  return (
    <button
      onClick={() => {
        signOut();
        router.replace("/login");
      }}
      className="rounded-md border border-white/10 px-2 py-1 transition hover:border-red-400 hover:text-red-400"
    >
      Sign out
    </button>
  );
}

export function SignOutButton() {
  return CLERK_ENABLED ? <ClerkAwareSignOut /> : <LocalSignOut />;
}
