import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ContextPreviewCard } from "../../../src/features/run/context_preview_card";

it("shows GitHub evidence without Google attribution or approval controls", async () => {
  const user = userEvent.setup();
  render(<ContextPreviewCard busy={false} onAdjust={vi.fn()} preview={{
    schema_version: 1, retrieval_revision: 1, gmail_count: 0, tasks_count: 0,
    calendar_count: 0, github_count: 1, adjustment_allowed: false, allowed_adjustments: [],
    items: [{segment_id: "segment-1", source: "github", role: "SUPPORTS",
      resource_type: "github_issue", resource_id: "acme/repo#7", display_label: "Issue seven",
      excerpt: "Approved evidence"}],
  }} />);
  await user.click(screen.getByRole("button", {name: "사용 컨텍스트 1개"}));
  expect(screen.getByText("GitHub", {exact: true})).toBeInTheDocument();
  expect(screen.getByText("Issue seven")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "선택한 근거 제외"})).not.toBeInTheDocument();
});
