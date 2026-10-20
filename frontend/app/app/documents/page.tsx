"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  ApiError,
  deleteDocument,
  indexDocument,
  listDocuments,
  uploadDocument,
  type DocumentSummary,
} from "@/lib/api";
import { Gate } from "@/components/AppShell";
import { useToast } from "@/components/Toast";
import { ErrorBanner } from "@/components/ui";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.html,.htm";

export default function AppDocumentsPage() {
  const toast = useToast();
  const [tab, setTab] = useState<"upload" | "paste">("upload");
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  // Upload state
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // Paste state
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const [indexing, setIndexing] = useState(false);

  async function refreshDocs() {
    setLoadingDocs(true);
    try {
      const res = await listDocuments();
      setDocs(res.documents);
    } catch {
      // listing is best-effort; don't surface as a blocking error
    } finally {
      setLoadingDocs(false);
    }
  }

  useEffect(() => {
    void refreshDocs();
  }, []);

  async function handleFiles(files: FileList | File[]) {
    setError(null);
    const list = Array.from(files);
    setUploading(true);
    for (const file of list) {
      try {
        await uploadDocument(file);
        toast(`Indexed ${file.name}`, "success");
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : "Upload failed";
        setError(`${file.name}: ${msg}`);
        toast(`${file.name}: ${msg}`, "error");
      }
    }
    setUploading(false);
    await refreshDocs();
  }

  async function submitPaste(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim() || !content.trim()) return;
    setIndexing(true);
    setError(null);
    try {
      await indexDocument(url.trim(), content);
      toast("Document indexed", "success");
      setContent("");
      setUrl("");
      await refreshDocs();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Indexing failed";
      setError(msg);
      toast(msg, "error");
    } finally {
      setIndexing(false);
    }
  }

  async function remove(doc: DocumentSummary) {
    setDeleting(doc.document_id);
    try {
      await deleteDocument(doc.document_id);
      setDocs((d) => d.filter((x) => x.document_id !== doc.document_id));
      toast("Document removed", "success");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Delete failed", "error");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <Gate permission="index">
      <h1 className="text-2xl font-bold">Documents</h1>
      <p className="mt-1 text-muted">
        Step 1 of getting started. Add files or paste text to build your private
        corpus — then Search, Answers, and Research can use them. Everything here
        is visible only to your account.
      </p>

      <div className="mt-5 flex w-fit rounded-lg border border-white/10 p-1 text-sm">
        <button
          onClick={() => setTab("upload")}
          className={`rounded-md px-4 py-2 transition ${
            tab === "upload" ? "bg-accent/15 text-accent" : "text-muted"
          }`}
        >
          Upload files
        </button>
        <button
          onClick={() => setTab("paste")}
          className={`rounded-md px-4 py-2 transition ${
            tab === "paste" ? "bg-accent/15 text-accent" : "text-muted"
          }`}
        >
          Paste text
        </button>
      </div>

      {error && (
        <div className="mt-4">
          <ErrorBanner message={error} />
        </div>
      )}

      {tab === "upload" ? (
        <div className="mt-5">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              if (e.dataTransfer.files?.length) handleFiles(e.dataTransfer.files);
            }}
            onClick={() => fileInput.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-12 text-center transition ${
              dragOver
                ? "border-accent bg-accent/10"
                : "border-white/15 bg-surface/40 hover:border-accent/40"
            }`}
          >
            <div className="grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-2xl text-accent">
              ↑
            </div>
            <p className="mt-4 font-medium">
              {uploading ? "Uploading…" : "Drag & drop files here"}
            </p>
            <p className="mt-1 text-sm text-muted">
              or click to browse · PDF, DOCX, TXT, Markdown, HTML · up to 10MB
            </p>
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.length) handleFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
        </div>
      ) : (
        <motion.form
          onSubmit={submitPaste}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-5 space-y-4 rounded-2xl border border-white/8 bg-surface/40 p-6"
        >
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://source.example.com/doc"
            className="w-full rounded-lg border border-white/10 bg-base px-4 py-3 outline-none ring-accent/40 focus:ring-2"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            placeholder="Document text or HTML…"
            className="w-full resize-y rounded-lg border border-white/10 bg-base px-4 py-3 font-mono text-sm outline-none ring-accent/40 focus:ring-2"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted">
              {url.trim() && content.trim() ? "Ready to index" : "URL and content required"}
            </span>
            <button
              type="submit"
              disabled={!url.trim() || !content.trim() || indexing}
              className="rounded-lg bg-accent px-6 py-3 font-semibold text-[#04141a] transition hover:scale-[1.02] disabled:opacity-40"
            >
              {indexing ? "Indexing…" : "Index document"}
            </button>
          </div>
        </motion.form>
      )}

      {/* Indexed documents with delete */}
      <div className="mt-6 rounded-xl border border-white/8 bg-surface/40 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">
            Indexed documents ({docs.length})
          </h2>
          <button
            onClick={refreshDocs}
            className="text-xs text-muted transition hover:text-accent"
          >
            {loadingDocs ? "Loading…" : "Refresh"}
          </button>
        </div>
        {docs.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted">
            No documents yet. Drag a file above (or paste text) to add your
            first one — then head to Answers or Search.
          </p>
        ) : (
          <ul className="divide-y divide-white/5">
            {docs.map((d) => (
              <li
                key={d.document_id}
                className="flex items-center justify-between gap-3 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm">{d.title}</p>
                  <p className="truncate font-mono text-xs text-muted">
                    {d.source_url} · v{d.version}
                  </p>
                </div>
                <button
                  onClick={() => remove(d)}
                  disabled={deleting === d.document_id}
                  className="shrink-0 rounded-md border border-white/10 px-3 py-1.5 text-xs text-red-400 transition hover:border-red-400/50 hover:bg-red-500/10 disabled:opacity-40"
                >
                  {deleting === d.document_id ? "Removing…" : "Remove"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Gate>
  );
}
