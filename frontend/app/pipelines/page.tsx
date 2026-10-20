import { redirect } from "next/navigation";

// Legacy public demo route. Pipelines are managed inside the gated console.
// Redirect to the console overview (requires sign-in).
export default function PipelinesRedirect() {
  redirect("/app");
}
