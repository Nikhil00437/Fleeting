/**
 * @vitest-environment jsdom
 *
 * The End buttons previously appeared on every row and only reported failure
 * afterwards. These assert the refusal happens *before* the click, and that the
 * reason is legible.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import ProcessesView from "../ProcessesView";
import { api } from "../../api";
import type { ProcessInfo } from "../../types";

vi.mock("../../api", () => ({
  api: {
    processApps: vi.fn(),
    processList: vi.fn(),
    processDetails: vi.fn(),
    processKill: vi.fn(),
    whoami: vi.fn(),
  },
}));

const me = "nikhil";

function procs(): ProcessInfo[] {
  return [
    { pid: 100, name: "zen", username: me, cpu_percent: 1, memory_mb: 200, status: "running", command: "zen", sessions: 1, seconds: 60, last_day: "2026-10-04", window_title: "docs", threads: 4, open_files: 10, connections: 1, parent_pid: 1, children: [] } as unknown as ProcessInfo,
    { pid: 200, name: "systemd", username: "root", cpu_percent: 0, memory_mb: 10, status: "sleeping", command: "/sbin/init", sessions: 0, seconds: 0, last_day: "2026-10-04", window_title: null, threads: 1, open_files: 0, connections: 0, parent_pid: 0, children: [] } as unknown as ProcessInfo,
  ];
}

function setup(list: ProcessInfo[], user = me) {
  vi.mocked(api.processList).mockResolvedValue(list as never);
  vi.mocked(api.processApps).mockResolvedValue([] as never);
  vi.mocked(api.whoami).mockResolvedValue({ user } as never);
  return render(<ProcessesView onToast={() => {}} />);
}

/**
 * The process table lives behind the second tab, and rows arrive from an
 * awaited fetch — so callers must await this before asserting.
 */
async function openProcessesTab() {
  await screen.findByRole("button", { name: "Active Processes" });
  fireEvent.click(screen.getByRole("button", { name: "Active Processes" }));
  await screen.findByText("systemd");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("process ownership gating", () => {
  it("offers End for your own process", async () => {
    setup(procs());
    await openProcessesTab();
    const own = (await screen.findAllByTitle("End process")) as HTMLButtonElement[];
    expect(own.length).toBeGreaterThan(0);
    expect(own.every((b) => !b.disabled)).toBe(true);
  });

  it("refuses to end another user's process", async () => {
    setup(procs());
    await openProcessesTab();
    const blocked = (await screen.findAllByTitle(/Owned by root/)) as HTMLButtonElement[];
    expect(blocked.length).toBeGreaterThan(0);
    for (const b of blocked) expect(b.disabled).toBe(true);
  });

  it("says who owns it and who you are", async () => {
    setup(procs());
    await openProcessesTab();
    const tip = (await screen.findAllByTitle(/Owned by root/))[0].getAttribute("title") ?? "";
    expect(tip).toContain("root");
    expect(tip).toContain(me);
    expect(tip).toMatch(/sudo/i);
  });

  it("disables everything when the server user is unknown", async () => {
    // Better a dead button than a 403 the user cannot act on.
    setup(procs(), "");
    await openProcessesTab();
    const buttons = (await screen.findAllByTitle(/Owned by|End process/)) as HTMLButtonElement[];
    expect(buttons.length).toBeGreaterThan(0);
    expect(buttons.every((b) => b.disabled)).toBe(true);
  });
});
