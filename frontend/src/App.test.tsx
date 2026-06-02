import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => [],
    }),
  );
});

describe("App", () => {
  it("renders the header and navigation", () => {
    render(<App />);
    expect(screen.getByText(/WG Activity Tracker/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "threads" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "pipeline" })).toBeInTheDocument();
  });

  it("shows an empty state when there are no threads", async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getByText(/No threads yet/i)).toBeInTheDocument(),
    );
  });
});
