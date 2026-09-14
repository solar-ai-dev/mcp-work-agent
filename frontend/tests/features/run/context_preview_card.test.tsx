import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { ContextPreview, ContextPreviewItem } from "../../../src/api/contract";
import { ContextPreviewCard } from "../../../src/features/run/context_preview_card";

function contextItem(
  resourceIdentity: string,
  category: ContextPreviewItem["category"],
  title: string,
  content = `${title}의 전체 내용입니다.`,
  segmentIds = [`segment-${resourceIdentity}`],
): ContextPreviewItem {
  return {
    resource_identity: resourceIdentity,
    category,
    title,
    preview: `${title} 미리보기`,
    content,
    segment_ids: segmentIds,
  };
}

function contextPreview(
  items: ContextPreviewItem[],
  changes: Partial<ContextPreview> = {},
): ContextPreview {
  return {
    schema_version: 1,
    run_id: "run-1",
    retrieval_revision: 1,
    items,
    gmail_count: items.filter((item) => item.category === "mail").length,
    tasks_count: items.filter((item) => item.category === "task").length,
    calendar_count: items.filter((item) => item.category === "calendar").length,
    github_count: items.filter((item) => item.category === "github").length,
    adjustment_allowed: false,
    allowed_adjustments: [],
    ...changes,
  };
}

it("shows a simple empty state and all category counts", async () => {
  const user = userEvent.setup();
  render(<ContextPreviewCard busy={false} onAdjust={vi.fn()} preview={contextPreview([])} />);

  await user.click(screen.getByRole("button", { name: "사용 컨텍스트 0개" }));

  expect(screen.getByRole("dialog", { name: "사용 컨텍스트 0개" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "메일 0" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "태스크 0" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "일정 0" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "GitHub 0" })).toBeInTheDocument();
  expect(screen.getByText("현재 사용 중인 컨텍스트가 없습니다.")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "메일 0" }));
  expect(screen.getByText("메일 컨텍스트가 없습니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "메일 0" })).toHaveAttribute("aria-pressed", "true");
});

it("switches a mixed list by category without invoking product work", async () => {
  const user = userEvent.setup();
  const onAdjust = vi.fn();
  const items = [
    contextItem("mail-1", "mail", "같은 제목"),
    contextItem("mail-2", "mail", "같은 제목"),
    contextItem("task-1", "task", "입고 준비"),
    contextItem("calendar-1", "calendar", "납품 회의"),
    contextItem("github-1", "github", "#208 Activity UI 개선"),
  ];
  render(<ContextPreviewCard busy={false} onAdjust={onAdjust} preview={contextPreview(items)} />);
  await user.click(screen.getByRole("button", { name: "사용 컨텍스트 5개" }));

  expect(screen.getAllByRole("button", { name: "같은 제목 내용 펼치기" })).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "태스크 1" }));
  expect(screen.getByText("입고 준비")).toBeInTheDocument();
  expect(screen.queryByText("납품 회의")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "GitHub 1" }));
  expect(screen.getByText("#208 Activity UI 개선")).toBeInTheDocument();
  expect(screen.queryByText("입고 준비")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "GitHub 1" }));
  expect(screen.getByText("납품 회의")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "같은 제목 내용 펼치기" })).toHaveLength(2);
  expect(onAdjust).not.toHaveBeenCalled();
});

it("expands one item and keeps the default preview compact after refresh", async () => {
  const user = userEvent.setup();
  const item = contextItem(
    "mail-1",
    "mail",
    "Quartz 납품 회신 검토",
    "납품 안내를 확인했습니다.\n입고 준비 담당자와 확인 후 회신드리겠습니다.",
  );
  const initialPreview = contextPreview([item]);
  const { rerender } = render(
    <ContextPreviewCard busy={false} onAdjust={vi.fn()} preview={initialPreview} />,
  );
  await user.click(screen.getByRole("button", { name: "사용 컨텍스트 1개" }));

  const toggle = screen.getByRole("button", { name: "Quartz 납품 회신 검토 내용 펼치기" });
  expect(screen.getByText("Quartz 납품 회신 검토 미리보기")).toHaveClass("context-item-preview");
  await user.click(toggle);
  expect(screen.getByText(/납품 안내를 확인했습니다/)).toHaveClass("context-item-content");
  expect(screen.getByRole("button", { name: "Quartz 납품 회신 검토 내용 접기" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "Quartz 납품 회신 검토 내용 접기" }));

  rerender(<ContextPreviewCard busy={false} onAdjust={vi.fn()} preview={{ ...initialPreview }} />);
  expect(screen.getByText("Quartz 납품 회신 검토 미리보기")).toHaveClass("context-item-preview");
  expect(screen.queryByText("SUPPORTS")).not.toBeInTheDocument();
  expect(screen.queryByText("message-1")).not.toBeInTheDocument();
  expect(screen.queryByText("thread_id")).not.toBeInTheDocument();
  expect(screen.queryByText("null")).not.toBeInTheDocument();
  expect(screen.queryByText("[]")).not.toBeInTheDocument();
});

it("sends every segment bound to a selected deduplicated resource", async () => {
  const user = userEvent.setup();
  const onAdjust = vi.fn().mockResolvedValue(undefined);
  render(<ContextPreviewCard busy={false} onAdjust={onAdjust} preview={contextPreview(
    [contextItem("mail-1", "mail", "프로젝트 메일", undefined, ["segment-1", "segment-2"])],
    {
      adjustment_allowed: true,
      allowed_adjustments: ["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"],
    },
  )} />);

  await user.click(screen.getByRole("button", { name: "사용 컨텍스트 1개" }));
  await user.click(screen.getByRole("checkbox", { name: "프로젝트 메일 제외 선택" }));
  await user.click(screen.getByRole("button", { name: "선택한 근거 제외" }));

  expect(onAdjust).toHaveBeenCalledWith("EXCLUDE_EVIDENCE", ["segment-1", "segment-2"]);
});
