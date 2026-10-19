// Demo mode: reads the JSON written by `papertrail export-demo` from public/demo/.
// Review actions work in memory only; there are no uploads.
import type {
  AppSettings,
  DocumentDetail,
  DocumentOut,
  Item,
  ItemsPayload,
  ReviewIn,
} from "../api/client";
import type { DataSource } from "../api/source";

const base = `${import.meta.env.BASE_URL}demo/`;
const cache = new Map<string, { document: DocumentDetail; items: ItemsPayload }>();
const originals = new Map<string, Item>();

async function load(id: string): Promise<{ document: DocumentDetail; items: ItemsPayload }> {
  const cached = cache.get(id);
  if (cached) return cached;
  const response = await fetch(`${base}${encodeURIComponent(id)}.json`);
  if (!response.ok) throw new Error("That sample letter isn't available.");
  const data = (await response.json()) as { document: DocumentDetail; items: ItemsPayload };
  for (const item of data.items.items) originals.set(item.id, structuredClone(item));
  cache.set(id, data);
  return data;
}

const STATE: Record<ReviewIn["action"], Item["review_state"]> = {
  accept: "accepted",
  edit: "edited",
  dismiss: "dismissed",
  restore: "none",
};

function noUploads(): never {
  throw new Error("The demo can't process new letters. Install PaperTrail to use your own.");
}

export const demoSource: DataSource = {
  demo: true,
  async listDocuments() {
    const response = await fetch(`${base}index.json`);
    return (await response.json()) as DocumentOut[];
  },
  async getDocument(id) {
    return (await load(id)).document;
  },
  async getItems(id) {
    return (await load(id)).items;
  },
  async review(itemId, body) {
    for (const entry of cache.values()) {
      const list = entry.items.items;
      const index = list.findIndex((i) => i.id === itemId);
      if (index < 0) continue;
      const current = list[index] as Item;
      const original = originals.get(itemId) ?? current;
      let next: Item = { ...current, review_state: STATE[body.action] };
      if (body.action === "edit" && body.changes) {
        const changes = Object.fromEntries(
          Object.entries(body.changes).filter(([, value]) => value !== undefined && value !== null),
        );
        next = {
          ...next,
          ...changes,
          original: {
            text: original.text,
            due_date: original.due_date,
            amount_cents: original.amount_cents,
            requirement: original.requirement,
            condition: original.condition,
          },
        };
      }
      if (body.action === "restore") next = { ...structuredClone(original), review_state: "none" };
      list[index] = next;
      return next;
    }
    throw new Error("That item no longer exists.");
  },
  upload: async () => noUploads(),
  reprocess: async () => noUploads(),
  remove: async () => noUploads(),
  async getSettings(): Promise<AppSettings> {
    return { privacy_notice_ack: true };
  },
  async putSetting(): Promise<AppSettings> {
    return { privacy_notice_ack: true };
  },
  fileUrl: (id) => `${base}${encodeURIComponent(id)}.pdf`,
  calendarUrl: () => null,
};
