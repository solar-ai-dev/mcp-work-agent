import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RunSnapshot } from "../../../src/api/contract";
import { RunProgress } from "../../../src/features/run/run_progress";
import type { RunSseEvent } from "../../../src/features/run/api/run_sse_event";

function snapshot(count = 1): RunSnapshot {
  return {
    run: { run_id: "run-1", version: 3, status: "WAITING_APPROVAL" },
    recovery_summary: { unknown_result_action_count: 0 },
    terminal_result_kind: "NONE",
    activity: { schema_version: 1, trace_cursor: count, audit_cursor: 0, rows: Array.from({ length: count }, (_, i) => ({
      execution_id: `row-${i}`, sequence: i + 1, role: "계획 생성", state: "RECORDED",
      label: `계획 ${i} 기록`, details: [{ label: "제목", value: `그 시점 제목 ${i}`, display_text: `제목: 그 시점 제목 ${i}` }],
      started_at_ms: i, updated_at_ms: i,
    })) },
  } as RunSnapshot;
}

test("retains more than twelve server rows and expands in place without requests", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  const value = snapshot(20);
  const view = render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);
  expect(screen.getAllByTestId("run-event-progress")).toHaveLength(20);
  const first = screen.getAllByTestId("run-event-progress")[0]!;
  await userEvent.setup().click(first);
  expect(first.closest("details")).toHaveAttribute("open");
  expect(screen.getByText("제목: 그 시점 제목 0")).toBeVisible();
  view.rerender(<RunProgress snapshot={{ ...value, run: { ...value.run, version: 4 } }} busy={null} onResume={vi.fn()} />);
  expect(first.closest("details")).toHaveAttribute("open");
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

test("activity rows omit historical disclaimers and state glyphs", () => {
  const value = snapshot(7);
  const states = ["RUNNING", "WAITING", "RECORDED", "PARTIAL", "FAILED", "INTERRUPTED", "UNKNOWN"] as const;
  value.activity!.rows.forEach((row, index) => { row.state = states[index]!; });

  render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);

  expect(screen.queryByText(/실행 시점의 기록/)).not.toBeInTheDocument();
  for (const summary of screen.getAllByTestId("run-event-progress")) {
    expect(summary.textContent).toMatch(/^계획 생성 · 계획 \d+ 기록$/);
  }
});

test("SSE duplicates, out of order and other Run events cannot fabricate rows", () => {
  const value = snapshot(2);
  const event = { run_id: "other", event_type: "phase_changed", payload: { phase: "ACTION_EXECUTION" } } as RunSseEvent;
  const view = render(<RunProgress snapshot={value} latestEvent={event} busy={null} onResume={vi.fn()} />);
  view.rerender(<RunProgress snapshot={value} latestEvent={event} busy={null} onResume={vi.fn()} />);
  expect(screen.getAllByTestId("run-event-progress")).toHaveLength(2);
  expect(screen.queryByText(/승인된 작업을 실행/)).not.toBeInTheDocument();
});

test("restores identical rows from Snapshot and isolates a new Run", async () => {
  const value = snapshot(2);
  const view = render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);
  await userEvent.setup().click(screen.getAllByTestId("run-event-progress")[0]!);
  view.unmount();
  const restored = render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);
  expect(screen.getAllByTestId("run-event-progress")).toHaveLength(2);
  restored.rerender(<RunProgress snapshot={{ ...snapshot(0), run: { ...value.run, run_id: "new" } }} busy={null} onResume={vi.fn()} />);
  expect(screen.queryAllByTestId("run-event-progress")).toHaveLength(0);
  expect(screen.queryByText(/저장된 단계 이력이 없습니다/)).not.toBeInTheDocument();
});

test("partial results rely on the recorded cause instead of a generic disclaimer", () => {
  const value = { ...snapshot(0), terminal_result_kind: "PARTIAL", recovery_summary: { unknown_result_action_count: 1 } } as RunSnapshot;
  render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);
  expect(screen.queryByText(/미완료 이유/)).not.toBeInTheDocument();
  expect(screen.getByText(/검증 전 성공으로 판단하지 않습니다/)).toBeVisible();
  expect(screen.queryByText(/나머지는 취소/)).not.toBeInTheDocument();
});

test("child facts use the server identity and distinguish progress from completion", async () => {
  const value = snapshot(1);
  value.activity!.rows[0]!.details = [
    { fact_id: "fact-running", label: "자료 조회", value: "자료를 확인하고 있습니다.", display_text: "자료를 확인하고 있습니다.", state: "RUNNING", occurred_at_ms: 2 },
    { fact_id: "fact-recorded", label: "검색 계획", value: "검색할 조건을 확인했습니다.", display_text: "검색할 조건을 확인했습니다.", state: "RECORDED", occurred_at_ms: 1 },
  ];
  render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);

  await userEvent.setup().click(screen.getByTestId("run-event-progress"));

  expect(screen.getByText("진행 중", { exact: false })).toBeVisible();
  expect(screen.getByText(/자료를 확인하고 있습니다\./)).toBeVisible();
  expect(screen.getByText("검색할 조건을 확인했습니다.")).toBeVisible();
  expect(screen.queryByText("완료", { exact: false })).not.toBeInTheDocument();
  expect(screen.queryByText("검색 계획")).not.toBeInTheDocument();
});

test("only a server-running row is animated and a state update preserves expanded facts", async () => {
  const running = snapshot(1);
  running.activity!.rows[0]!.state = "RUNNING";
  running.activity!.rows[0]!.details = [
    { fact_id: "fact-started", label: "자료 조회", value: "자료 조회를 시작했습니다.", display_text: "자료 조회를 시작했습니다.", state: "RECORDED", occurred_at_ms: 1 },
  ];
  const view = render(<RunProgress snapshot={running} busy={null} onResume={vi.fn()} />);
  const summary = screen.getByTestId("run-event-progress");
  const row = summary.closest("details")!;

  expect(row).toHaveClass("agent-status-line--active");
  await userEvent.setup().click(summary);
  expect(row).toHaveAttribute("open");

  const waiting = snapshot(1);
  waiting.activity!.rows[0]!.state = "WAITING";
  waiting.activity!.rows[0]!.details = [
    ...running.activity!.rows[0]!.details,
    { fact_id: "fact-waiting", label: "사용자 결정", value: "사용자 확인을 기다리고 있습니다.", display_text: "사용자 확인을 기다리고 있습니다.", state: "WAITING", occurred_at_ms: 2 },
  ];
  view.rerender(<RunProgress snapshot={waiting} busy={null} onResume={vi.fn()} />);

  expect(row).toHaveAttribute("open");
  expect(row).not.toHaveClass("agent-status-line--active");
  expect(screen.getByText("자료 조회를 시작했습니다.")).toBeVisible();
  expect(screen.getByText(/사용자 확인을 기다리고 있습니다\./)).toBeVisible();

  const failed = snapshot(1);
  failed.activity!.rows[0]!.state = "FAILED";
  failed.activity!.rows[0]!.details = waiting.activity!.rows[0]!.details;
  view.rerender(<RunProgress snapshot={failed} busy={null} onResume={vi.fn()} />);

  expect(row).toHaveAttribute("open");
  expect(row).not.toHaveClass("agent-status-line--active");
});

test("RunProgress exposes only the server-projected resume action", async () => {
  const value = snapshot(0);
  value.run.status = "BLOCKED";
  value.error = { schema_version: 1, error_code: "BLOCKED", message: "", actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] };
  const onResume = vi.fn();
  const view = render(<RunProgress snapshot={value} busy={null} onResume={onResume} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "재개" }));
  expect(onResume).toHaveBeenCalledWith("SAFE_CHECKPOINT_RESUME");
  view.rerender(<RunProgress snapshot={{ ...value, run: { ...value.run, status: "ANALYZING" } }} busy={null} onResume={onResume} />);
  expect(screen.queryByRole("button", { name: "재개" })).not.toBeInTheDocument();
});

test("a restored historical Run is read-only even when its snapshot has a resume action", () => {
  const value = snapshot(0);
  value.run.status = "BLOCKED";
  value.error = { schema_version: 1, error_code: "BLOCKED", message: "", actions: [{ kind: "RESUME_SAFE_CHECKPOINT", resume_kind: "SAFE_CHECKPOINT_RESUME" }] };

  render(<RunProgress snapshot={value} busy={null} interactive={false} onResume={vi.fn()} />);

  expect(screen.queryByRole("button", { name: "재개" })).not.toBeInTheDocument();
});

test("dynamic Activity text is rendered literally without executing markup", async () => {
  const value = snapshot(1);
  const dynamicValue = `<img src="invalid" onerror="alert(1)">${"긴 기록 ".repeat(80)}`;
  value.activity!.rows[0]!.details = [{ label: "Provider 결과", value: dynamicValue, display_text: dynamicValue }];

  render(<RunProgress snapshot={value} busy={null} onResume={vi.fn()} />);
  await userEvent.setup().click(screen.getByTestId("run-event-progress"));

  expect(document.querySelector(".agent-activity-detail-facts p")?.textContent).toBe(dynamicValue);
  expect(screen.queryByText("Provider 결과")).not.toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
});
