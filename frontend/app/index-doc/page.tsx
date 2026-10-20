import { redirect } from "next/navigation";

// Legacy public demo route. Document indexing now lives in the gated console at
// /app/documents (requires sign-in). Redirect there.
export default function IndexDocRedirect() {
  redirect("/app/documents");
}
