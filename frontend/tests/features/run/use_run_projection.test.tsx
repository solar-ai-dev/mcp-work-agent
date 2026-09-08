import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { ConversationHistoryResponse, RunSnapshot } from "../../../src/api/contract";
import { useRunProjection } from "../../../src/features/run/use_run_projection";
import { getRunSnapshot, getRunContext } from "../../../src/features/run/api/get_run_snapshot";

vi.mock("../../../src/features/run/api/get_run_snapshot", () => ({ getRunSnapshot: vi.fn(), getRunContext: vi.fn() }));
vi.mock("../../../src/features/run/api/subscribe_run_events", () => ({ subscribeRunEvents: vi.fn(() => vi.fn()) }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });

function snapshot(status: RunSnapshot["run"]["status"], version: number): RunSnapshot {
  return { run: { run_id: "run", conversation_id: "conversation", status, version, finished_at_ms: null }, pending_interrupt: null } as RunSnapshot;
}

function options() {
  return {
    busyCommand: null, setBusyCommand: vi.fn(), commandIdFor: () => "command", completeCommand: vi.fn(),
    beginConversationProjection: () => 1,
    getConversationProjection: () => ({ conversationId: "conversation", generation: 1 }),
    isCurrentProjection: () => true, reloadConversationHistory: vi.fn(async () => undefined),
    selectConversationHistory: vi.fn(async () => undefined), isRunHistorySynced: () => false,
    markRunHistorySynced: vi.fn(), onStatusLine: vi.fn(),
  };
}

test("activity cursors prevent equal-version history regression", async () => {
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  const newer = { ...snapshot("WAITING_APPROVAL", 3), activity: { schema_version: 1 as const, trace_cursor: 9, audit_cursor: 5, rows: [] } };
  const older = { ...newer, activity: { ...newer.activity, trace_cursor: 8 } };
  vi.mocked(getRunSnapshot).mockResolvedValueOnce(newer).mockResolvedValueOnce(older);
  const { result } = renderHook(() => useRunProjection(options()));
  await act(async () => { await result.current.refreshRun("run"); });
  await act(async () => { await result.current.refreshRun("run"); });
  expect(result.current.runSnapshot?.activity?.trace_cursor).toBe(9);
});

test("active runs reconcile approval snapshots without an SSE event and stop polling when suspended", async () => {
  vi.useFakeTimers();
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  vi.mocked(getRunSnapshot).mockResolvedValueOnce(snapshot("ANALYZING", 1)).mockResolvedValue(snapshot("WAITING_APPROVAL", 3));
  const { result } = renderHook(() => useRunProjection(options()));
  await act(async () => { await result.current.selectRun("run"); });
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current.runSnapshot?.run.status).toBe("WAITING_APPROVAL");
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(getRunSnapshot).toHaveBeenCalledTimes(2);
});

test("a late older snapshot cannot replace newer approval state", async () => {
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  vi.mocked(getRunSnapshot).mockResolvedValueOnce(snapshot("WAITING_APPROVAL", 3)).mockResolvedValueOnce(snapshot("ANALYZING", 1));
  const { result } = renderHook(() => useRunProjection(options()));
  await act(async () => { await result.current.refreshRun("run"); });
  await act(async () => { await result.current.refreshRun("run"); });
  expect(result.current.runSnapshot?.run.status).toBe("WAITING_APPROVAL");
});

test("restores every retained Run snapshot and keeps the latest Run interactive", async () => {
  const snapshots = new Map([
    ["run-a", { ...snapshot("COMPLETED", 2), run: { ...snapshot("COMPLETED", 2).run, run_id: "run-a", started_at_ms: 1, finished_at_ms: 2 } }],
    ["run-b", { ...snapshot("WAITING_APPROVAL", 3), run: { ...snapshot("WAITING_APPROVAL", 3).run, run_id: "run-b", started_at_ms: 3 } }],
  ]);
  vi.mocked(getRunSnapshot).mockImplementation(async (runId) => snapshots.get(runId)!);
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  const history = {
    schema_version: 1,
    conversation: { schema_version: 1, conversation_id: "conversation", title: null, latest_message_at_ms: 3, open_run_id: "run-b" },
    messages: [],
    runs: [
      { schema_version: 1, run_id: "run-a", status: "COMPLETED", started_at_ms: 1, finished_at_ms: 2 },
      { schema_version: 1, run_id: "run-b", status: "WAITING_APPROVAL", started_at_ms: 3, finished_at_ms: null },
    ],
    truncated: false,
  } satisfies ConversationHistoryResponse;
  const hookOptions = {
    ...options(),
    selectConversationHistory: vi.fn(async () => history),
  };
  const { result } = renderHook(() => useRunProjection(hookOptions));

  await act(async () => { await result.current.selectConversation("conversation"); });

  expect(result.current.runSnapshots.map((item) => item.run.run_id)).toEqual(["run-a", "run-b"]);
  expect(result.current.runSnapshot?.run.run_id).toBe("run-b");
});

test("startup open-Run selection also restores earlier Runs from Conversation history", async () => {
  const snapshots = new Map([
    ["run-a", { ...snapshot("COMPLETED", 2), run: { ...snapshot("COMPLETED", 2).run, run_id: "run-a", started_at_ms: 1, finished_at_ms: 2 } }],
    ["run-b", { ...snapshot("ANALYZING", 3), run: { ...snapshot("ANALYZING", 3).run, run_id: "run-b", started_at_ms: 3 } }],
  ]);
  vi.mocked(getRunSnapshot).mockImplementation(async (runId) => snapshots.get(runId)!);
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  const history = {
    schema_version: 1,
    conversation: { schema_version: 1, conversation_id: "conversation", title: null, latest_message_at_ms: 3, open_run_id: "run-b" },
    messages: [],
    runs: [
      { schema_version: 1, run_id: "run-a", status: "COMPLETED", started_at_ms: 1, finished_at_ms: 2 },
      { schema_version: 1, run_id: "run-b", status: "ANALYZING", started_at_ms: 3, finished_at_ms: null },
    ],
    truncated: false,
  } satisfies ConversationHistoryResponse;
  let projection = { conversationId: null as string | null, generation: 1 };
  const hookOptions = {
    ...options(),
    beginConversationProjection: (conversationId: string) => {
      projection = { conversationId, generation: 2 };
      return 2;
    },
    getConversationProjection: () => projection,
    isCurrentProjection: (conversationId: string, generation: number) => (
      projection.conversationId === conversationId && projection.generation === generation
    ),
    reloadConversationHistory: vi.fn(async () => history),
  };
  const { result } = renderHook(() => useRunProjection(hookOptions));

  await act(async () => { await result.current.selectRun("run-b"); });

  expect(result.current.runSnapshots.map((item) => item.run.run_id)).toEqual(["run-a", "run-b"]);
  expect(result.current.runSnapshot?.run.run_id).toBe("run-b");
});

test("a failed terminal history reload remains retryable", async () => {
  vi.mocked(getRunContext).mockResolvedValue({ context: null } as never);
  vi.mocked(getRunSnapshot).mockResolvedValue({
    ...snapshot("COMPLETED", 2),
    run: { ...snapshot("COMPLETED", 2).run, finished_at_ms: 2 },
  });
  const reloadConversationHistory = vi.fn()
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce({} as ConversationHistoryResponse);
  const markRunHistorySynced = vi.fn();
  const { result } = renderHook(() => useRunProjection({
    ...options(),
    reloadConversationHistory,
    markRunHistorySynced,
  }));

  await act(async () => { await result.current.refreshRun("run"); });
  await act(async () => { await result.current.refreshRun("run"); });

  expect(reloadConversationHistory).toHaveBeenCalledTimes(2);
  expect(markRunHistorySynced).toHaveBeenCalledTimes(1);
});
