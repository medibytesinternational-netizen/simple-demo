import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function clientReturning(response: Response | Promise<Response>) {
  const fetchImpl = vi.fn<typeof fetch>(() => Promise.resolve(response));
  return { client: createApiClient({ fetchImpl }), fetchImpl };
}

const file = () => new File(["abc"], "note.wav", { type: "audio/wav" });

describe("api client", () => {
  it("posts the file as multipart field 'file' and returns the accepted job", async () => {
    const { client, fetchImpl } = clientReturning(
      jsonResponse(202, { job_id: "abc", status: "queued", status_url: "/api/jobs/abc" }),
    );
    const accepted = await client.submitJob(file());
    expect(accepted.job_id).toBe("abc");
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe("/api/jobs");
    expect(init?.method).toBe("POST");
    const body = init?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("surfaces the server detail for 413 too large", async () => {
    const { client } = clientReturning(jsonResponse(413, { detail: "File exceeds 64 MB limit" }));
    const err = await client.submitJob(file()).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 413, detail: "File exceeds 64 MB limit" });
    expect((err as ApiError).transient).toBe(false);
  });

  it("surfaces the server detail for 415 unsupported type", async () => {
    const { client } = clientReturning(jsonResponse(415, { detail: "Unsupported audio type: .txt" }));
    await expect(client.submitJob(file())).rejects.toMatchObject({
      status: 415,
      detail: "Unsupported audio type: .txt",
    });
  });

  it("falls back to a readable message when the body has no detail", async () => {
    const { client } = clientReturning(new Response("", { status: 413 }));
    await expect(client.submitJob(file())).rejects.toMatchObject({
      status: 413,
      detail: "The file is too large (64 MB maximum).",
    });
  });

  it("joins FastAPI validation error messages", async () => {
    const { client } = clientReturning(jsonResponse(422, { detail: [{ msg: "Field required" }] }));
    await expect(client.getJob("x")).rejects.toMatchObject({ status: 422, detail: "Field required" });
  });

  it("maps network failures to a transient ApiError with status 0", async () => {
    const client = createApiClient({ fetchImpl: () => Promise.reject(new TypeError("Failed to fetch")) });
    const err = await client.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).transient).toBe(true);
  });

  it("rethrows aborts untouched", async () => {
    const abort = new DOMException("aborted", "AbortError");
    const client = createApiClient({ fetchImpl: () => Promise.reject(abort) });
    await expect(client.listJobs()).rejects.toBe(abort);
  });

  it("builds encoded file URLs", () => {
    const client = createApiClient({ baseUrl: "http://host/" });
    expect(client.fileUrl("a b", "cleaned.wav")).toBe("http://host/api/jobs/a%20b/files/cleaned.wav");
  });
});
