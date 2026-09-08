import { Fragment, useEffect, useRef, type Dispatch, type ReactNode, type SetStateAction } from "react";
import type { ConversationMessage, RunAction, RunContext, RunSnapshot } from "../../api/contract";
import type { StagedAttachmentDescriptor } from "../attachment";
import { ActionPlanCard } from "../approval";
import { RecoveryCard } from "../recovery";
import { ConfirmationCard, ContextPreviewCard, ExecutionStatusCard, ExternalLlmDisclosureCard, RequestComposer, RunProgress } from "../run";
import type { RunSseEvent } from "../run/api/run_sse_event";
import { AssistantMessageBubble, DateSeparator, UserMessageBubble } from "./MessageBubble";

type RecoveryKind = NonNullable<RunSnapshot["recovery"]>["allowed_resolution_kinds"][number];

export type ConversationViewModel = {
  controller: {
    selectedConversationId: string | null;
    historyMessages: ConversationMessage[];
    runSnapshot: RunSnapshot | null;
    runSnapshots: RunSnapshot[];
    runContext: RunContext | null;
    latestRunEvent?: RunSseEvent | null;
    confirmationText: string;
    setConfirmationText: Dispatch<SetStateAction<string>>;
    composerText: string;
    composerError: string | null;
    setComposerText: Dispatch<SetStateAction<string>>;
    setComposerError: Dispatch<SetStateAction<string | null>>;
    busyCommand: string | null;
    handleStartRun: (quickPrompt?: string) => Promise<void>;
    handleApprove: (action: RunAction, acknowledgements?: ReadonlySet<string>) => Promise<void>;
    handleSimpleAction: (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch?: Record<string, unknown> | string) => Promise<void>;
    handleAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void>;
    handleCancelRun: () => Promise<void>;
    handleResumeRun: (resumeKind: "SAFE_CHECKPOINT_RESUME") => Promise<void>;
    handleAdjustContext: (kind: "EXCLUDE_EVIDENCE" | "RETRIEVE_MORE", value: string[] | string) => Promise<void>;
    handleConfirmation: (selectedOption?: string) => Promise<void>;
    handleResolveRecovery: (resolutionKind: RecoveryKind) => Promise<void>;
  };
  resourceContext: { selectedResourceIds: string[]; selectedResourceLabels: string[]; composerPrompt: string };
  formatTime: (value: number) => string;
  onOpenSettings: () => void;
  onOpenDiagnostics: () => void;
};

export type ConversationViewProps = { children: ReactNode; viewModel: ConversationViewModel };

export function ConversationView({ children, viewModel }: ConversationViewProps): JSX.Element {
  const { controller, resourceContext, formatTime, onOpenSettings, onOpenDiagnostics } = viewModel;
  const { selectedConversationId, historyMessages, runSnapshot, runSnapshots, runContext, latestRunEvent, confirmationText, setConfirmationText, composerText, composerError, setComposerText, setComposerError, busyCommand, handleStartRun, handleApprove, handleSimpleAction, handleAttachDescriptors, handleCancelRun, handleResumeRun, handleAdjustContext, handleConfirmation, handleResolveRecovery } = controller;
  const timelineMessages = mergeConversationMessages(
    historyMessages,
    runSnapshots.flatMap((snapshot) => snapshot.messages ?? []),
    runSnapshot?.messages ?? [],
  );
  const showTransientRequest = Boolean(runContext?.request_text)
    && !timelineMessages.some((message) => message.role === "USER" && message.run_id === runContext?.run_id);
  const isTerminal = runSnapshot !== null
    && ["COMPLETED", "BLOCKED", "FAILED", "CANCELLED"].includes(runSnapshot.run.status);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const lastUserId = timelineMessages.filter((message) => message.role === "USER").at(-1)?.id;
  const lastMessageId = timelineMessages.at(-1)?.id;
  const previousUserId = useRef(lastUserId);
  useEffect(() => {
    const node = timelineRef.current;
    const newRequest = previousUserId.current !== lastUserId;
    previousUserId.current = lastUserId;
    if (node && (newRequest || (!node.querySelector("details[open]") && node.scrollHeight - node.scrollTop - node.clientHeight < 120))) node.scrollTop = node.scrollHeight;
  }, [selectedConversationId, lastUserId, lastMessageId, showTransientRequest]);
  const snapshotsByRunId = new Map(runSnapshots.map((snapshot) => [snapshot.run.run_id, snapshot]));
  if (runSnapshot) snapshotsByRunId.set(runSnapshot.run.run_id, runSnapshot);
  const displayedRunIds = new Set(
    timelineMessages
      .filter((message) => message.role === "USER" && message.run_id !== null)
      .map((message) => message.run_id!),
  );
  const retryActionIds = new Set(runSnapshot?.error?.actions.filter((action) => action.kind === "PREPARE_RETRY" && action.action_id).map((action) => action.action_id!) ?? []);

  return (
    <>
      <div className="panel-body">
        <div className="central-scroll-area" ref={timelineRef}>
          {children}
          <section className="agent-workspace" aria-label="에이전트 대화">
            <section className="card-list">
              {groupMessagesByDate(timelineMessages).map(({ message, separatorLabel }) => (
                <Fragment key={message.id}>
                  {separatorLabel ? <DateSeparator label={separatorLabel} /> : null}
                  {message.role === "USER" ? <UserMessageBubble content={message.content} createdAtMs={message.created_at_ms} /> : message.role === "ASSISTANT" ? <AssistantMessageBubble content={message.content} createdAtMs={message.created_at_ms} /> : <article className="info-card"><strong>시스템 메시지</strong><p>{message.content}</p></article>}
                  {message.role === "USER" && message.run_id && snapshotsByRunId.has(message.run_id) ? (
                    <RunProgress
                      snapshot={snapshotsByRunId.get(message.run_id)!}
                      latestEvent={message.run_id === runSnapshot?.run.run_id ? latestRunEvent : null}
                      busy={message.run_id === runSnapshot?.run.run_id ? busyCommand : null}
                      interactive={message.run_id === runSnapshot?.run.run_id}
                      onResume={(kind) => void handleResumeRun(kind)}
                    />
                  ) : null}
                </Fragment>
              ))}
              {showTransientRequest ? <UserMessageBubble content={runContext!.request_text} /> : null}
              {runSnapshot && !displayedRunIds.has(runSnapshot.run.run_id) ? <RunProgress snapshot={runSnapshot} latestEvent={latestRunEvent} busy={busyCommand} interactive onResume={(kind) => void handleResumeRun(kind)} /> : null}
              {!isTerminal && runSnapshot?.pending_interrupt ? <ConfirmationCard interrupt={runSnapshot.pending_interrupt} text={confirmationText} busy={busyCommand === "confirm-run"} onTextChange={setConfirmationText} onSubmit={(option) => void handleConfirmation(option)} /> : null}
              {runSnapshot && !isTerminal ? <div className="action-execution-flow"><ActionPlanCard snapshot={runSnapshot} busy={busyCommand} retryActionIds={retryActionIds} formatTime={formatTime} onApprove={(action, acknowledgements) => void handleApprove(action, acknowledgements)} onModify={(action, patch) => handleSimpleAction("modify", action, patch)} onReject={(action) => void handleSimpleAction("reject", action)} onRetry={(action) => void handleSimpleAction("retry", action)} onAttachDescriptors={(action, descriptors) => handleAttachDescriptors(action, descriptors)} /><ExecutionStatusCard snapshot={runSnapshot} /></div> : null}
              {runSnapshot && !isTerminal ? <RecoveryCard snapshot={runSnapshot} busy={busyCommand} onResolve={(kind) => void handleResolveRecovery(kind)} onErrorAction={(kind) => kind === "OPEN_DIAGNOSTICS" ? onOpenDiagnostics() : onOpenSettings()} /> : null}
            </section>
          </section>
        </div>
        {runSnapshot?.external_llm_transfer_scope ? <ExternalLlmDisclosureCard scope={runSnapshot.external_llm_transfer_scope} /> : null}
        {runSnapshot?.context_preview ? <ContextPreviewCard preview={runSnapshot.context_preview} busy={busyCommand?.startsWith("adjust-context:") ?? false} onAdjust={handleAdjustContext} /> : null}
        <RequestComposer text={composerText} error={composerError} busy={busyCommand === "start-run"} cancelAllowed={runSnapshot?.run.next_allowed_commands.includes("REQUEST_CANCEL") ?? false} cancelling={busyCommand === "cancel-run"} prompt={resourceContext.composerPrompt} selectedResourceLabels={resourceContext.selectedResourceLabels} setText={setComposerText} setError={setComposerError} onSubmit={handleStartRun} onCancel={handleCancelRun} />
      </div>
    </>
  );
}

export function mergeConversationMessages(
  ...messageGroups: ConversationMessage[][]
): ConversationMessage[] {
  const byId = new Map<string, ConversationMessage>();
  for (const messages of messageGroups) {
    for (const message of messages) byId.set(message.id, message);
  }
  return Array.from(byId.values()).sort(
    (left, right) => left.created_at_ms - right.created_at_ms || left.id.localeCompare(right.id),
  );
}

type MessageWithSeparator = { message: ConversationMessage; separatorLabel: string | null };

function groupMessagesByDate(messages: ConversationMessage[]): MessageWithSeparator[] {
  let lastDateKey: string | null = null;
  return messages.map((message) => {
    const date = new Date(message.created_at_ms);
    const dateKey = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
    const separatorLabel = dateKey === lastDateKey ? null : date.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
    lastDateKey = dateKey;
    return { message, separatorLabel };
  });
}
