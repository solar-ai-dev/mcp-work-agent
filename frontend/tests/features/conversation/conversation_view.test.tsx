import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ConversationMessage, RunSnapshot } from "../../../src/api/contract";
import {
  ConversationView,
  type ConversationViewModel,
} from "../../../src/features/conversation/ConversationView";

const finalMessage: ConversationMessage = {
  schema_version: 1,
  id: "message-final",
  run_id: "run-1",
  role: "ASSISTANT",
  content: "요청하신 태스크를 만들고 Google에서 결과를 확인했습니다.",
  created_at_ms: 2,
};

test("terminal snapshot message appears immediately and is deduplicated from history", () => {
  const snapshot = {
    run: {
      run_id: "run-1",
      conversation_id: "conversation-1",
      status: "COMPLETED",
      version: 2,
      entry_mode: "AGENT_SEARCH",
      requested_mode: "AUTO",
      actual_runtime: "LOCAL_GPU",
      started_at_ms: 1,
      finished_at_ms: 2,
      next_allowed_commands: [],
    },
    messages: [finalMessage],
    current_plan: null,
    actions: [],
    context_preview: null,
    approvals: [],
    execution_status: { action_count: 0, terminal_action_count: 0 },
    verification_summary: { verified_count: 0, mismatch_count: 0 },
    recovery_summary: { unknown_result_action_count: 0 },
    pending_interrupt: null,
    recovery: null,
    error: null,
    external_llm_transfer_scope: null,
    terminal_result_kind: "SUCCESS",
    projection_version: 1,
  } satisfies RunSnapshot;
  const viewModel = {
    controller: {
      selectedConversationId: "conversation-1",
      historyMessages: [{ ...finalMessage, content: "stale history copy" }],
      runSnapshot: snapshot,
      runSnapshots: [snapshot],
      runContext: null,
      latestRunEvent: null,
      confirmationText: "",
      setConfirmationText: vi.fn(),
      composerText: "",
      composerError: null,
      setComposerText: vi.fn(),
      setComposerError: vi.fn(),
      busyCommand: null,
      handleStartRun: vi.fn(),
      handleApprove: vi.fn(),
      handleSimpleAction: vi.fn(),
      handleAttachDescriptors: vi.fn(),
      handleCancelRun: vi.fn(),
      handleResumeRun: vi.fn(),
      handleAdjustContext: vi.fn(),
      handleConfirmation: vi.fn(),
      handleResolveRecovery: vi.fn(),
    },
    resourceContext: { selectedResourceIds: [], selectedResourceLabels: [], composerPrompt: "" },
    formatTime: (value: number) => String(value),
    onOpenSettings: vi.fn(),
    onOpenDiagnostics: vi.fn(),
  } satisfies ConversationViewModel;

  render(<ConversationView viewModel={viewModel}><div /></ConversationView>);

  expect(screen.getAllByText(finalMessage.content)).toHaveLength(1);
  expect(screen.queryByText("stale history copy")).not.toBeInTheDocument();
  expect(screen.getByLabelText("에이전트 진행")).toBeInTheDocument();
});

test("each retained Run keeps its Activity beside its own request and final answer", () => {
  const messages: ConversationMessage[] = [
    { schema_version: 1, id: "request-a", run_id: "run-a", role: "USER", content: "요청 A", created_at_ms: 1 },
    { schema_version: 1, id: "answer-a", run_id: "run-a", role: "ASSISTANT", content: "최종 답변 A", created_at_ms: 2 },
    { schema_version: 1, id: "request-b", run_id: "run-b", role: "USER", content: "요청 B", created_at_ms: 3 },
    { schema_version: 1, id: "answer-b", run_id: "run-b", role: "ASSISTANT", content: "최종 답변 B", created_at_ms: 4 },
  ];
  const makeSnapshot = (runId: string, label: string, startedAt: number): RunSnapshot => ({
    run: {
      run_id: runId, conversation_id: "conversation-1", status: "COMPLETED", version: 2,
      entry_mode: "AGENT_SEARCH", requested_mode: "LOCAL_GPU", actual_runtime: "LOCAL_GPU",
      started_at_ms: startedAt, finished_at_ms: startedAt + 1, next_allowed_commands: [],
    },
    messages: messages.filter((message) => message.run_id === runId),
    activity: {
      schema_version: 1, trace_cursor: 1, audit_cursor: 0,
      rows: [{ execution_id: `${runId}-execution`, sequence: 1, role: "요청 분석", state: "RECORDED", label, details: [], started_at_ms: startedAt, updated_at_ms: startedAt + 1 }],
    },
    current_plan: null, actions: [], context_preview: null, approvals: [],
    execution_status: { action_count: 0, terminal_action_count: 0 },
    verification_summary: { verified_count: 0, mismatch_count: 0 },
    recovery_summary: { unknown_result_action_count: 0 }, pending_interrupt: null,
    recovery: null, error: null, external_llm_transfer_scope: null,
    terminal_result_kind: "SUCCESS", projection_version: 1,
  });
  const snapshotA = makeSnapshot("run-a", "요청 A를 분석했습니다.", 1);
  const snapshotB = makeSnapshot("run-b", "요청 B를 분석했습니다.", 3);
  const controller = {
    selectedConversationId: "conversation-1", historyMessages: messages,
    runSnapshot: snapshotB, runSnapshots: [snapshotA, snapshotB], runContext: null,
    latestRunEvent: null, confirmationText: "", setConfirmationText: vi.fn(),
    composerText: "", composerError: null, setComposerText: vi.fn(), setComposerError: vi.fn(),
    busyCommand: null, handleStartRun: vi.fn(), handleApprove: vi.fn(),
    handleSimpleAction: vi.fn(), handleAttachDescriptors: vi.fn(), handleCancelRun: vi.fn(),
    handleResumeRun: vi.fn(), handleAdjustContext: vi.fn(), handleConfirmation: vi.fn(),
    handleResolveRecovery: vi.fn(),
  } satisfies ConversationViewModel["controller"];

  render(<ConversationView viewModel={{
    controller,
    resourceContext: { selectedResourceIds: [], selectedResourceLabels: [], composerPrompt: "" },
    formatTime: String, onOpenSettings: vi.fn(), onOpenDiagnostics: vi.fn(),
  }}><div /></ConversationView>);

  expect(screen.getAllByLabelText("에이전트 진행")).toHaveLength(2);
  expect(screen.getByText(/요청 A를 분석했습니다/)).toBeVisible();
  expect(screen.getByText(/요청 B를 분석했습니다/)).toBeVisible();
  expect(screen.getByText("최종 답변 A")).toBeVisible();
  expect(screen.getByText("최종 답변 B")).toBeVisible();
});
