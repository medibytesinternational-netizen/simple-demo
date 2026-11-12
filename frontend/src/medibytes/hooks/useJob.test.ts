import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import type { Job, JobStatus } from "../api/types";
import { loadSucceededJob } from "../test/fixtures";
import { createFakeClient } from "../test/fakeClient";
import { useJob } from "./useJob";

function jobWithStatus(status: JobStatus): Job {
  const job = loadSucceededJob();
  return { ...job, job_id: "job-1", status, result: status === "succeeded" ? job.result : null };
}

const flush = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

describe("useJob", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("submits, polls every interval, and stops on a terminal status", async () => {
    const sequence: JobStatus[] = ["queued", "running", "running", "succeeded"];
    const client = createFakeClient();
    client.getJob.mockImplementation(() => Promise.resolve(jobWithStatus(sequence.shift() ?? "succeeded")));

    const { result } = renderHook(() => useJob(client, { intervalMs: 1000 }));
    await act(async () => {
      await result.current.submit(new File(["x"], "a.wav"));
    });

    expect(client.submitJob).toHaveBeenCalledTimes(1);
    expect(client.getJob).toHaveBeenCalledTimes(1);
    expect(result.current.jobId).toBe("job-1");

    await flush(1000);
    await flush(1000);
    await flush(1000);
    expect(client.getJob).toHaveBeenCalledTimes(4);
    expect(result.current.job?.status).toBe("succeeded");

    await flush(10_000);
    expect(client.getJob).toHaveBeenCalledTimes(4);
  });

  it("stops polling when the job fails", async () => {
    const client = createFakeClient();
    client.getJob.mockResolvedValue({ ...jobWithStatus("failed"), error: "MedASR crashed" });
    const { result } = renderHook(() => useJob(client));
    act(() => result.current.open("job-1"));
    await flush(0);
    await flush(5000);
    expect(client.getJob).toHaveBeenCalledTimes(1);
    expect(result.current.job?.error).toBe("MedASR crashed");
  });

  it("backs off exponentially on network errors, then recovers", async () => {
    const client = createFakeClient();
    client.getJob
      .mockRejectedValueOnce(new ApiError(0, "offline"))
      .mockRejectedValueOnce(new ApiError(503, "unavailable"))
      .mockResolvedValue(jobWithStatus("succeeded"));

    const { result } = renderHook(() => useJob(client, { intervalMs: 1000, maxBackoffMs: 16_000 }));
    act(() => result.current.open("job-1"));
    await flush(0);
    expect(client.getJob).toHaveBeenCalledTimes(1);
    expect(result.current.reconnecting).toBe(true);

    await flush(1999); // first retry waits 2 s
    expect(client.getJob).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(client.getJob).toHaveBeenCalledTimes(2);

    await flush(3999); // second retry waits 4 s
    expect(client.getJob).toHaveBeenCalledTimes(2);
    await flush(1);
    expect(client.getJob).toHaveBeenCalledTimes(3);
    expect(result.current.reconnecting).toBe(false);
    expect(result.current.job?.status).toBe("succeeded");
  });

  it("gives up immediately on a non-transient error", async () => {
    const client = createFakeClient();
    client.getJob.mockRejectedValue(new ApiError(404, "Job not found"));
    const { result } = renderHook(() => useJob(client));
    act(() => result.current.open("missing"));
    await flush(0);
    await flush(10_000);
    expect(client.getJob).toHaveBeenCalledTimes(1);
    expect(result.current.pollError).toBe("Job not found");
  });

  it("exposes the server detail when the upload is refused", async () => {
    const client = createFakeClient();
    client.submitJob.mockRejectedValue(new ApiError(415, "Unsupported audio type: .txt"));
    const { result } = renderHook(() => useJob(client));
    await act(async () => {
      await result.current.submit(new File(["x"], "a.wav"));
    });
    expect(result.current.submitError).toBe("Unsupported audio type: .txt");
    expect(client.getJob).not.toHaveBeenCalled();
  });

  it("stops polling on unmount", async () => {
    const client = createFakeClient();
    client.getJob.mockResolvedValue(jobWithStatus("running"));
    const { result, unmount } = renderHook(() => useJob(client));
    act(() => result.current.open("job-1"));
    await flush(0);
    expect(client.getJob).toHaveBeenCalledTimes(1);
    unmount();
    await flush(10_000);
    expect(client.getJob).toHaveBeenCalledTimes(1);
  });
});
