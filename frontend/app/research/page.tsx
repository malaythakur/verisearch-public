import { redirect } from "next/navigation";

// Legacy public demo route. Research now lives in the gated console at
// /app/research (requires sign-in). Redirect there.
export default function ResearchRedirect() {
  redirect("/app/research");
}
