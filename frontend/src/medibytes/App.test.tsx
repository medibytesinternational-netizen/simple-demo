import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Job } from "./api/types";
import { createFakeClient } from "./test/fakeClient";
import { loadSucceededJob } from "./test/fixtures";

function runningJob(): Job {
  const job = loadSucceededJob();
  return {
    ...job,
    status: "running",
    result: null,
    stages: job.stages.map((s, i) => ({
      ...s,
      state: i < 2 ? "done" : i === 2 ? "running" : "pending",
      seconds: i < 2 ? s.seconds : null,
      detail: i < 2 ? s.detail : "",
    })),
  };
}

describe("App", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("uploads, tracks pipeline progress, and displays the complete processed output", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const done = loadSucceededJob();
    const client = createFakeClient();
    client.submitJob.mockResolvedValue({ job_id: done.job_id, status: "queued", status_url: "" });
    client.getJob.mockResolvedValueOnce(runningJob()).mockResolvedValue(done);

    render(<App client={client} />);
    expect(await screen.findByText(/gpt-4\.1 is configured/)).toBeInTheDocument();
    expect(screen.getByText("Recent jobs")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Pipeline progress" })).toBeInTheDocument();

    await user.upload(screen.getByLabelText("Browse files"), new File(["RIFF"], "s1.mp4", { type: "audio/mp4" }));
    await user.click(screen.getByRole("button", { name: "Process dictation" }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });

    const tab = await screen.findByRole("tab", { name: "Transcript" });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("transcript-text")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "JSON" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Extracted chart" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Verification results" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Discharge note" })).toBeInTheDocument();
    expect(client.getJob).toHaveBeenCalledTimes(2);
  });
});
