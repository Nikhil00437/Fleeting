// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import AssistantView from "../AssistantView";
import { api } from "../../api";
import type { ChatHistoryItem, ChatMessage } from "../../types";

const item = (over: Partial<ChatHistoryItem> = {}): ChatHistoryItem => ({
  id: "c1",
  title: "router decision",
  pinned: 0,
  created_at: "2026-10-08T09:00:00Z",
  updated_at: "2026-10-08T09:10:00Z",
  messages: [
    { role: "user", content: "what did we decide about the router" },
    { role: "assistant", content: "ship the v2 config" },
  ],
  hit_count: 1,
  preview: "ship the v2 config",
  ...over,
});

const renderView = (props: Partial<React.ComponentProps<typeof AssistantView>> = {}) => {
  render(
    <AssistantView onOpenNote={() => {}} onToast={() => {}} initialSuggestions={[]} {...props} />,
  );
};

function typeInHistory(text: string) {
  fireEvent.change(screen.getByLabelText("Search conversation history"), { target: { value: text } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AssistantView conversation history (#111)", () => {
  it("lists saved conversations and reopens one into the thread", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([item()]);
    renderView();

    const entry = await screen.findByText("router decision");
    entry.closest("button")?.click();
    await waitFor(() => expect(screen.getByText("ship the v2 config")).toBeTruthy());
  });

  it("searches the history box against the query it types", async () => {
    const spy = vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    renderView();
    await waitFor(() => expect(spy).toHaveBeenCalledWith(""));

    typeInHistory("router");
    await waitFor(() => expect(spy).toHaveBeenCalledWith("router"));
  });

  it("says so when the search matches nothing", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    renderView();

    typeInHistory("nothing");
    expect(await screen.findByText("No conversation mentions that.")).toBeTruthy();
  });

  it("pins an entry", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([item()]);
    const pin = vi.spyOn(api, "pinChat").mockResolvedValue(item({ pinned: 1 }));
    renderView();

    (await screen.findByLabelText("Pin router decision")).click();
    await waitFor(() => expect(pin).toHaveBeenCalledWith("c1", true));
  });

  it("saves the transcript it is showing", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    const save = vi.spyOn(api, "saveChatHistory").mockResolvedValue(item());
    renderView({
      initialMessages: [
        { role: "user", content: "what did we decide" },
        { role: "assistant", content: "this" },
      ] as ChatMessage[],
    });

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(expect.stringMatching(/^chat-\d+$/), [
        { role: "user", content: "what did we decide" },
        { role: "assistant", content: "this" },
      ]),
    );
  });

  it("starts a fresh thread without deleting the old one", async () => {
    vi.spyOn(api, "chatHistory").mockResolvedValue([]);
    const del = vi.spyOn(api, "deleteChat").mockResolvedValue(undefined);
    renderView({ initialMessages: [{ role: "user", content: "old turn" }] as ChatMessage[] });

    screen.getByLabelText("New conversation").click();
    await waitFor(() => expect(screen.queryByText("old turn")).toBeNull());
    expect(del).not.toHaveBeenCalled();
  });
});