import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UploadPanel } from "./UploadPanel";

function setup(props: Partial<Parameters<typeof UploadPanel>[0]> = {}) {
  const onSubmit = vi.fn<(file: File) => void>();
  const user = userEvent.setup({ applyAccept: false });
  render(<UploadPanel onSubmit={onSubmit} busy={false} uploading={false} serverError={null} {...props} />);
  const input = screen.getByLabelText(/browse files|choose another file/i);
  return { onSubmit, user, input };
}

describe("UploadPanel", () => {
  it("rejects a file with an unsupported extension", async () => {
    const { onSubmit, user, input } = setup();
    await user.upload(input, new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(screen.getByRole("alert")).toHaveTextContent(".txt files are not supported");
    expect(screen.getByRole("button", { name: "Process dictation" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects files over 64 MB", async () => {
    const { user, input } = setup();
    const big = new File(["x"], "long.wav", { type: "audio/wav" });
    Object.defineProperty(big, "size", { value: 64 * 1024 * 1024 + 1 });
    await user.upload(input, big);
    expect(screen.getByRole("alert")).toHaveTextContent("64 MB");
  });

  it("accepts a supported file and submits it", async () => {
    const { onSubmit, user, input } = setup();
    const file = new File(["RIFF"], "Ward Round.M4A", { type: "audio/mp4" });
    await user.upload(input, file);
    expect(screen.getByText("Ward Round.M4A")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Process dictation" }));
    expect(onSubmit).toHaveBeenCalledWith(file);
  });

  it("accepts a dropped file", () => {
    setup();
    const file = new File(["RIFF"], "drop.wav", { type: "audio/wav" });
    fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file] } });
    expect(screen.getByText("drop.wav")).toBeInTheDocument();
  });

  it("shows the server detail inline", () => {
    setup({ serverError: "Unsupported audio type: .xyz" });
    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported audio type: .xyz");
  });
});
