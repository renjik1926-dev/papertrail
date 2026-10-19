import type { DocumentOut } from "../api/client";

export const STEP_LABELS: Record<DocumentOut["status"], string> = {
  queued: "Waiting to start",
  parsing: "Reading the PDF",
  extracting: "Asking the AI model to list what the letter asks",
  verifying: "Checking every item against the letter",
  ready: "Ready",
  failed: "Failed",
  unsupported: "Can't be processed",
};

export function isProcessing(status: DocumentOut["status"]): boolean {
  return (
    status === "queued" || status === "parsing" || status === "extracting" || status === "verifying"
  );
}
