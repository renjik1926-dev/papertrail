import { useCallback, useEffect, useRef, useState, type DragEvent, type MouseEvent } from "react";
import type { DocumentOut } from "../api/client";
import { useAsync } from "../lib/useAsync";
import { source } from "../api/source";
import { PrivacyNotice } from "../components/Notices";
import { formatDate } from "../lib/dates";
import { STEP_LABELS, isProcessing } from "../lib/status";
import { href, navigate } from "../router";

const POLL_MS = 2000;

export function UploadPage() {
  const loadDocuments = useCallback(() => source.listDocuments(), []);
  const loadSettings = useCallback(() => source.getSettings(), []);
  const list = useAsync(loadDocuments);
  const settings = useAsync(loadSettings);
  const [acknowledgedNow, setAcknowledgedNow] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const documents = list.data;
  const acknowledged =
    acknowledgedNow || (settings.data?.privacy_notice_ack ?? (settings.error ? false : null));
  const error = problem ?? list.error;
  const { reload } = list;

  const busy = documents?.some((d) => isProcessing(d.status)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, reload]);

  async function send(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    setUploading(true);
    try {
      const created = await source.upload(file);
      navigate(`/documents/${created.id}`);
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "The upload failed.");
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function acknowledge() {
    try {
      await source.putSetting("privacy_notice_ack", "true");
    } finally {
      setAcknowledgedNow(true);
    }
  }

  async function remove(doc: DocumentOut) {
    if (!window.confirm(`Delete “${doc.filename}” and everything PaperTrail stored about it?`))
      return;
    try {
      await source.remove(doc.id);
      reload();
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Couldn't delete it.");
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    void send(event.dataTransfer.files[0]);
  }

  return (
    <div className="page-upload">
      <h1>Your letters</h1>
      <p className="lede">
        Upload a letter as a PDF. PaperTrail lists what it asks you to do — actions, documents,
        deadlines and amounts — and links every item to the passage it came from.
      </p>

      {!source.demo && acknowledged === false && <PrivacyNotice onAck={() => void acknowledge()} />}

      {!source.demo && acknowledged && (
        <div
          className={`dropzone${dragging ? " dropzone--active" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <label htmlFor="file" className="dropzone__label">
            Choose a PDF, or drop it here
          </label>
          <input
            id="file"
            ref={input}
            type="file"
            accept="application/pdf,.pdf"
            disabled={uploading}
            onChange={(e) => void send(e.target.files?.[0])}
          />
          <p className="hint">
            {uploading
              ? "Uploading…"
              : "Up to 20 MB and 50 pages, with selectable text (not a scan)."}
          </p>
          <p className="hint">
            The letter stays on this computer; its text is sent to Anthropic's API to read it.
          </p>
        </div>
      )}

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      <h2>{source.demo ? "Sample letters" : "Uploaded"}</h2>
      {documents === null ? (
        <p>Loading…</p>
      ) : documents.length === 0 ? (
        <p className="empty">No letters yet.</p>
      ) : (
        <table className="documents">
          <thead>
            <tr>
              <th scope="col">Letter</th>
              <th scope="col">Status</th>
              <th scope="col">Dated</th>
              {!source.demo && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {documents.map((doc) => (
              <tr key={doc.id}>
                <td>
                  <a
                    href={href(`/documents/${doc.id}`)}
                    onClick={(e) => linkClick(e, `/documents/${doc.id}`)}
                  >
                    {doc.filename}
                  </a>
                </td>
                <td>
                  {doc.status_message && doc.status !== "ready"
                    ? doc.status_message
                    : STEP_LABELS[doc.status]}
                </td>
                <td>{doc.document_date ? formatDate(doc.document_date) : "–"}</td>
                {!source.demo && (
                  <td>
                    <button type="button" className="link-button" onClick={() => void remove(doc)}>
                      Delete<span className="visually-hidden"> {doc.filename}</span>
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function linkClick(event: MouseEvent, path: string) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
  event.preventDefault();
  navigate(path);
}
