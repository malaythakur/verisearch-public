import { redirect } from "next/navigation";

// Legacy public demo route. The answer experience now lives in the gated
// console at /app/answer (which requires sign-in). Redirect there.
export default function AnswerRedirect() {
  redirect("/app/answer");
}
