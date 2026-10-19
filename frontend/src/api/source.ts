// Where the app gets its data: the local API, or static JSON in demo mode (BUILD_PLAN §10).
import { api, type AppSettings, type DocumentDetail, type DocumentOut, type Item } from "./client";
import type { ItemsPayload, ReviewIn } from "./client";
import { demoSource } from "../demo/demoSource";

export interface DataSource {
  demo: boolean;
  listDocuments(): Promise<DocumentOut[]>;
  getDocument(id: string): Promise<DocumentDetail>;
  getItems(id: string): Promise<ItemsPayload>;
  review(itemId: string, body: ReviewIn): Promise<Item>;
  upload(file: File): Promise<DocumentOut>;
  reprocess(id: string): Promise<DocumentOut>;
  remove(id: string): Promise<void>;
  getSettings(): Promise<AppSettings>;
  putSetting(key: string, value: string): Promise<AppSettings>;
  fileUrl(id: string): string;
  calendarUrl(id: string): string | null;
}

export const apiSource: DataSource = { demo: false, ...api };

export const isDemo = import.meta.env.VITE_DEMO === "1";

export const source: DataSource = isDemo ? demoSource : apiSource;
