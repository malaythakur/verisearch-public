import { redirect } from "next/navigation";

// Legacy public demo route. Search now lives in the gated console at
// /app/search (requires sign-in). Redirect there.
export default function SearchRedirect() {
  redirect("/app/search");
}
