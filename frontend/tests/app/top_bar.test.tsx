import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { TopBar } from "../../src/app/top_bar";

test("shows the product and controls without account or connection badges", async () => {
  const toggleTheme = vi.fn();
  const openSettings = vi.fn();
  render(<TopBar statusLine="ready" onOpenSettings={openSettings} onShowHelp={vi.fn()} onToggleResourcePanel={vi.fn()} onToggleConversationPanel={vi.fn()} resourcePanelOpen conversationPanelOpen theme="light" onThemeChange={toggleTheme} />);

  expect(screen.getByText("mcp-work-agent")).toBeInTheDocument();
  expect(screen.queryByText("Google 연결됨")).not.toBeInTheDocument();
  expect(screen.queryByText("user@example.com")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자료 패널 전환" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "테마 전환" }));
  expect(toggleTheme).toHaveBeenCalledWith("dark");
  await userEvent.click(screen.getByRole("button", { name: "설정" }));
  expect(openSettings).toHaveBeenCalledOnce();
});

test("does not promote a disconnected connector in the global header", () => {
  render(<TopBar statusLine="ready" onOpenSettings={vi.fn()} onShowHelp={vi.fn()} onToggleResourcePanel={vi.fn()} onToggleConversationPanel={vi.fn()} resourcePanelOpen conversationPanelOpen theme="light" onThemeChange={vi.fn()} />);

  expect(screen.queryByRole("button", { name: "Google 연결", exact: true })).not.toBeInTheDocument();
});
