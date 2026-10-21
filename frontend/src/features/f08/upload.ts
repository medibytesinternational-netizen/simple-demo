import { api } from "../../api";
import type { DocType } from "./types";

/** Upload a report with its type. The shared uploadDocument in api.ts sends no type. */
export function uploadReport(file: File, docType: DocType) {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  return api<any>("/documents/upload", { method: "POST", body: form });
}
