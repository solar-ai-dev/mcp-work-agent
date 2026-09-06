import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import type { RunAction, RunSnapshot } from "../../../src/api/contract";
import { ActionPlanCard } from "../../../src/features/approval/action_plan_card";

afterEach(() => vi.restoreAllMocks());

test("Task preview resolves the actual Task List name across continuation pages", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ tasklist_id: "other", title: "다른 목록" }], next_page_token: "next" }), { status: 200, headers: { "content-type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ items: [{ tasklist_id: "target", title: "검증용 목록" }], next_page_token: null }), { status: 200, headers: { "content-type": "application/json" } }));
  const action = taskAction(); action.arguments.task_list_id = "target";
  render(<ActionPlanCard {...propsFor(action)} />);
  expect(await screen.findByText("검증용 목록")).toBeVisible();
  expect(fetchMock.mock.calls[1][0]).toContain("page_token=next");
});

function taskAction(): RunAction {
  return { action_id: "task", tool_name: "tasks_create_task", arguments: { task_list_id: "@default", payload: { title: "회의록 공유", notes: "기존 메모", scheduled_date: "2026-09-11" } }, status: "PROPOSED", version: 0, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", risk: {}, next_allowed_commands: ["APPROVE_ACTION", "MODIFY_ACTION", "REJECT_ACTION"], required_acknowledgements: [], editable_fields: ["title", "notes", "due"], attachment_allowed: false, delivery_certainty: null };
}

function propsFor(action = taskAction()) {
  return { snapshot: { current_plan: { summary_text: "할 일을 준비했습니다." }, actions: [action], approvals: [] } as unknown as RunSnapshot, busy: null, retryActionIds: new Set<string>(), formatTime: String, onApprove: vi.fn(), onModify: vi.fn(), onReject: vi.fn(), onRetry: vi.fn(), onAttachDescriptors: vi.fn() };
}

test("Task default preview is compact and natural-language modification is sent verbatim", async () => {
  const props = propsFor();
  render(<ActionPlanCard {...props} />);
  expect(screen.getByRole("button", { name: "만들기" })).toBeEnabled();
  for (const field of screen.queryAllByRole("textbox")) expect(field).not.toBeVisible();
  expect(screen.getByText("직접 편집").closest("details")).not.toHaveAttribute("open");
  expect(document.body.textContent).not.toContain("계획 에이전트");
  fireEvent.click(screen.getByRole("button", { name: "수정" }));
  const request = "예정일을 9월 8일로 바꾸고 메모는 빼줘";
  fireEvent.change(screen.getByLabelText("어떻게 수정할까요?"), { target: { value: request } });
  fireEvent.click(screen.getByRole("button", { name: "수정 요청" }));
  expect(props.onModify).toHaveBeenCalledWith(props.snapshot.actions[0], request);
  expect(props.onApprove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "건너뛰기" }));
  expect(props.onReject).toHaveBeenCalledWith(props.snapshot.actions[0]);
});

test("Direct edit distinguishes explicit memo removal from untouched title and date", () => {
  const props = propsFor();
  render(<ActionPlanCard {...props} />);
  fireEvent.click(screen.getByText("직접 편집"));
  fireEvent.change(screen.getByLabelText("메모"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "이 내용으로 바꿀게요" }));
  expect(props.onModify).toHaveBeenCalledWith(props.snapshot.actions[0], { notes: "" });
});

test("New revision resets acknowledgements, shows removed fields, and uses current approval version", async () => {
  const action = taskAction();
  action.required_acknowledgements = ["TASK_DUPLICATE"];
  action.risk = { duplicate: { decision: "SIMILAR_CANDIDATE" } };
  const props = propsFor(action);
  const { rerender } = render(<ActionPlanCard {...props} />);
  fireEvent.click(screen.getByRole("checkbox"));
  const modified = { ...action, version: 1, status: "MODIFIED", arguments: { ...action.arguments, payload: { title: "회의록 공유", notes: "", scheduled_date: "2026-09-08" } } };
  rerender(<ActionPlanCard {...props} snapshot={{ ...props.snapshot, actions: [modified] }} />);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "위험을 확인하고 실행해 주세요" })).toBeDisabled();
  expect(screen.getByText("수정 전후 비교 · 다시 승인해 주세요")).toBeInTheDocument();
  expect(screen.getByLabelText("태스크 미리보기")).toHaveTextContent("없음");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "위험을 확인하고 실행해 주세요" }));
  expect(props.onApprove.mock.calls[0][0].version).toBe(1);
});

test("Modification failure retains the current preview and the user's request", async () => {
  const props = propsFor();
  props.onModify.mockRejectedValue(new Error("offline"));
  render(<ActionPlanCard {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "수정" }));
  fireEvent.change(screen.getByLabelText("어떻게 수정할까요?"), { target: { value: "그날로 바꿔줘" } });
  fireEvent.click(screen.getByRole("button", { name: "수정 요청" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("기존 내용을 유지합니다");
  expect(screen.getByLabelText("태스크 미리보기")).toHaveTextContent("2026-09-11");
  expect(screen.getByLabelText("어떻게 수정할까요?")).toHaveValue("그날로 바꿔줘");
});

test.each([
  ["gmail_send", { payload: { to: ["to@example.com"], cc: ["cc@example.com"], bcc: ["bcc@example.com"], subject: "승인한 제목", body: "승인한 본문", thread_id: "thread-1", in_reply_to: "<source@example.com>" } }, ["to@example.com", "cc@example.com", "bcc@example.com", "승인한 제목", "승인한 본문", "thread-1", "<source@example.com>"]],
  ["calendar_create_event", { calendar_id: "primary", payload: { title: "회의", start: "2026-09-08T10:00:00+09:00", end: "2026-09-08T11:00:00+09:00", attendees: ["test@example.com"] } }, ["기본 캘린더", "2026-09-08T10:00:00+09:00", "test@example.com"]],
  ["gmail_create_draft", { payload: { to: ["test@example.com"], subject: "회신", body: "메일 본문" } }, ["test@example.com", "회신", "메일 본문"]],
  ["github_update_issue", { repository: "owner/repository", issue_number: 12, payload: { title: "이슈", body: "변경 내용" } }, ["owner/repository", "12", "변경 내용"]],
])("Shared preview preserves %s approval fields", (tool, args, expected) => {
  const action = { ...taskAction(), tool_name: tool as string, arguments: args as Record<string, unknown>, editable_fields: [] };
  render(<ActionPlanCard {...propsFor(action)} />);
  for (const value of expected as string[]) expect(screen.getByText(value)).toBeInTheDocument();
});

test("ActionPlanCard presents user-facing arguments and sends only explicit acknowledgement", async () => {
  const action = { action_id: "a-1", tool_name: "tasks_create_task", arguments: { task_list_id: "@default", payload: { title: "분기 보고서 제출", scheduled_date: "2026-09-05" } }, status: "PROPOSED", version: 1, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", risk: { duplicate: { decision: "SIMILAR_CANDIDATE", matched_resource_ids: ["private"] } }, next_allowed_commands: ["APPROVE_ACTION"], required_acknowledgements: ["TASK_DUPLICATE"], editable_fields: [], attachment_allowed: false } as const;
  const snapshot = { current_plan: { summary_text: "계획" }, actions: [action], approvals: [] } as unknown as RunSnapshot;
  const onApprove = vi.fn();
  render(<ActionPlanCard snapshot={snapshot} busy={null} retryActionIds={new Set()} formatTime={String} onApprove={onApprove} onModify={vi.fn()} onReject={vi.fn()} onRetry={vi.fn()} onAttachDescriptors={vi.fn()} />);
  const user = userEvent.setup();
  const approve = screen.getByRole("button", { name: "위험을 확인하고 실행해 주세요" });
  expect(screen.queryByText("Action Plan")).not.toBeInTheDocument();
  expect(screen.getByText("분기 보고서 제출")).toBeInTheDocument();
  expect(screen.getByText("내 할 일 목록")).toBeInTheDocument();
  expect(screen.getByText("2026-09-05")).toBeInTheDocument();
  expect(screen.getByText("예정일")).toBeInTheDocument();
  expect(screen.queryByText("마감")).not.toBeInTheDocument();
  expect(screen.queryByText("@default")).not.toBeInTheDocument();
  expect(screen.queryByText("tasks_create_task")).not.toBeInTheDocument();
  expect(approve).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "중복 가능성을 확인했습니다." }));
  expect(approve).toBeEnabled();
  await user.click(approve);
  expect([...onApprove.mock.calls[0][1]]).toEqual(["TASK_DUPLICATE"]);
  expect(document.body.textContent).not.toContain("private");
});
