import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ResourceViewer } from "../../../src/features/resource_browser/resource_viewer";
import * as detailApi from "../../../src/features/resource_browser/api/get_resource_detail";

vi.mock("../../../src/features/resource_browser/api/get_resource_detail", () => ({
  getGmailResourceDetail: vi.fn(),
  getTaskResourceDetail: vi.fn(),
  getCalendarResourceDetail: vi.fn(),
}));

test("ResourceViewer invokes and renders the focused task detail contract", async () => {
  vi.mocked(detailApi.getTaskResourceDetail).mockResolvedValue({ schema_version: 1, resource_id: "provider-id", title: "후속 조치", task_status: "incomplete", scheduled_date: "2026-08-31", completed_at: null, tasklist_id: "default", notes: "검토 필요" });
  render(<ResourceViewer
    focusedItem={{ selection_handle: "opaque", source: "tasks", resource_type: "task", resource_id: "provider-id", title: "후속 조치", link_url: "https://tasks.google.com/", version: "v1", related_resource_ids: [], metadata: { task_status: "incomplete", scheduled_date: "2026-08-31" } }}
    emptyMessage="없음"
    onOpenContainer={vi.fn()}
    presentResource={(item) => ({ title: item.title, secondary: null, snippet: null, time: null })}
  />);
  expect(await screen.findByRole("heading", { name: "후속 조치" })).toBeInTheDocument();
  expect(detailApi.getTaskResourceDetail).toHaveBeenCalledWith("provider-id", "opaque");
  expect(screen.getByText("미완료")).toBeInTheDocument();
  expect(screen.queryByText("incomplete")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "후속 조치 상세" })).toBeInTheDocument();
  expect(screen.queryByText("요청에서 제외")).not.toBeInTheDocument();
  expect(screen.queryByText("요청에 포함")).not.toBeInTheDocument();
});

test("ResourceViewer invokes and renders the focused Calendar detail contract", async () => {
  vi.mocked(detailApi.getCalendarResourceDetail).mockResolvedValue({ schema_version: 1, resource_id: "event-1", title: "프로젝트 검토", start: "2026-08-31T09:00:00+09:00", end: "2026-08-31T10:00:00+09:00", timezone: "Asia/Seoul", calendar_id: "primary", attendees: ["user@example.com"], location: null, description: "주간 검토" });
  render(<ResourceViewer
    focusedItem={{ selection_handle: "calendar-handle", source: "calendar", resource_type: "calendar_event", resource_id: "event-1", title: "프로젝트 검토", link_url: null, version: "v1", related_resource_ids: [], metadata: { start: "2026-08-31T09:00:00+09:00", end: "2026-08-31T10:00:00+09:00", calendar_id: "primary" } }}
    emptyMessage="없음"
    onOpenContainer={vi.fn()}
    presentResource={(item) => ({ title: item.title, secondary: null, snippet: null, time: null })}
  />);
  expect(await screen.findByRole("heading", { name: "프로젝트 검토" })).toBeInTheDocument();
  expect(detailApi.getCalendarResourceDetail).toHaveBeenCalledWith("event-1", "calendar-handle");
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
});

test("ResourceViewer renders the complete Gmail body without an inner clamp", async () => {
  const body = "첫 줄\n둘째 줄\n셋째 줄\n넷째 줄도 생략하지 않습니다.";
  vi.mocked(detailApi.getGmailResourceDetail).mockResolvedValue({
    schema_version: 1,
    resource_id: "thread-1",
    message_id: "message-1",
    sender_name: "보낸 사람",
    sender_email: "sender@example.com",
    recipients: ["recipient@example.com"],
    cc: [],
    subject: "전체 원문",
    received_at: "2026-09-12T09:00:00+09:00",
    body,
    attachments: [],
    canonical_url: "https://mail.google.com/mail/u/0/#all",
  });
  render(<ResourceViewer
    focusedItem={{ selection_handle: "gmail-handle", source: "gmail", resource_type: "gmail_thread", resource_id: "thread-1", title: "전체 원문", link_url: null, version: "v1", related_resource_ids: [], metadata: {} }}
    emptyMessage="없음"
    onOpenContainer={vi.fn()}
    presentResource={(item) => ({ title: item.title, secondary: null, snippet: null, time: null })}
  />);

  expect(await screen.findByText((_content, element) => (
    element?.classList.contains("gmail-detail-body") === true && element.textContent === body
  ))).toBeInTheDocument();
  expect(screen.queryByText("… 더보기")).not.toBeInTheDocument();
});
