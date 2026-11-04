// Answers /api reads from captured synthetic fixtures; refuses every write.
// Loaded only in the UI-preview build, so the preview never contacts a backend.
import fixtures from "./fixtures.json";
import { PREVIEW_WRITE_MESSAGE } from "./config";
import { eventDetail, timeline, upgrade } from "./contract";

type FixtureMap = Record<string, any>;
const data = fixtures as FixtureMap;

export class PreviewError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function lookup(path: string): any {
  const [bare, query = ""] = path.split("?");
  return upgrade(bare, find(path, bare, query), data);
}

function find(path: string, bare: string, query: string): any {
  const history = bare.match(/^\/patients\/([^/]+)\/timeline$/);
  if (history) {
    const found = timeline(data, history[1], query);
    if (found) return found;
  }
  if (path in data) return data[path];
  if (bare === "/drafts") {
    const feature = new URLSearchParams(query).get("feature");
    return data[`/drafts?feature=${feature}&limit=1`] ?? { drafts: [] };
  }
  if (bare in data) return data[bare];
  const event = bare.match(/^\/events\/([^/]+)$/);
  if (event) {
    const record = data["/patients/pat_ravi/timeline?limit=250"];
    const found = (record?.events || []).find((item: any) => item.id === event[1]);
    if (found) return eventDetail(data, found);
  }
  const patient = bare.match(/^\/patients\/([^/]+)$/);
  if (patient && data.__patients__?.[patient[1]]) return { patient: data.__patients__[patient[1]] };
  const audit = bare.match(/^\/audit$/);
  if (audit) return data["/audit?limit=80"];
  throw new PreviewError("This information is not available in the current patient records.", 404);
}

export async function mockRequest(method: string, path: string): Promise<any> {
  // A short delay keeps loading states visible, as with a real network.
  await new Promise((resolve) => setTimeout(resolve, 120));
  if (method.toUpperCase() !== "GET") throw new PreviewError(PREVIEW_WRITE_MESSAGE, 403);
  return clone(lookup(path));
}

export function previewPatients(): Record<string, any> {
  return clone(data.__patients__ || {});
}
