import { useEffect, useRef, useState } from "react";
import type { ApprovalSnapshot, RunAction, RunSnapshot } from "../../api/contract";
import { AttachmentPicker, type StagedAttachmentDescriptor } from "../attachment";
import { calendarConflictDecision, feasibilityDecision, hasOtherRisk, taskDuplicateDecision } from "./risk_presentation";
import { listTaskLists } from "../resource_browser/api/list_resources";
import { ApiClientError } from "../../api/client";

export function ActionPlanCard({ snapshot, busy, retryActionIds, formatTime, onApprove, onModify, onReject, onRetry, onAttachDescriptors }: {
  snapshot: RunSnapshot;
  busy: string | null;
  retryActionIds: ReadonlySet<string>;
  formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void;
  onModify: (action: RunAction, patch: Record<string, unknown> | string) => Promise<void> | void;
  onReject: (action: RunAction) => void;
  onRetry: (action: RunAction) => void;
  onAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void> | void;
}): JSX.Element | null {
  const [taskListNames, setTaskListNames] = useState<Record<string, string>>({});
  const taskListIds = snapshot.actions.filter((action) => action.tool_name.startsWith("tasks_")).map((action) => String(action.arguments.task_list_id ?? "")).sort().join("|");
  useEffect(() => {
    let active = true;
    setTaskListNames({});
    if (taskListIds && taskListIds !== "@default") {
      void (async () => {
        const names: Record<string, string> = {};
        const seen = new Set<string>();
        let continuation: string | null = null;
        do {
          const response = await listTaskLists(continuation);
          if (!active) return;
          for (const item of response.items) names[item.tasklist_id] = item.title;
          setTaskListNames({ ...names });
          if (taskListIds.split("|").every((id) => id === "@default" || names[id])) return;
          continuation = response.next_page_token;
          if (continuation && seen.has(continuation)) return;
          if (continuation) seen.add(continuation);
        } while (continuation && active && seen.size < 10);
      })().catch(() => undefined);
    }
    return () => { active = false; };
  }, [taskListIds]);
  if (!snapshot.current_plan || snapshot.actions.length === 0) return null;
  return (
    <section className="action-plan-conversation" aria-label="실행 계획">
      {snapshot.current_plan.summary_text ? <p className="agent-status-line">작업 제안 · {snapshot.current_plan.summary_text}</p> : null}
      {snapshot.actions.map((action) => (
        <ActionDecisionCard key={action.action_id} action={action} taskListName={taskListNames[String(action.arguments.task_list_id)]} approval={snapshot.approvals.find((item) => item.action_id === action.action_id)} busy={busy} canRetry={retryActionIds.has(action.action_id)} formatTime={formatTime} onApprove={onApprove} onModify={onModify} onReject={onReject} onRetry={onRetry} onAttachDescriptors={onAttachDescriptors} />
      ))}
    </section>
  );
}

function ActionDecisionCard({ action, taskListName, approval, busy, canRetry, formatTime, onApprove, onModify, onReject, onRetry, onAttachDescriptors }: {
  action: RunAction; taskListName?: string; approval?: ApprovalSnapshot; busy: string | null; canRetry: boolean; formatTime: (value: number) => string;
  onApprove: (action: RunAction, acknowledgements: ReadonlySet<string>) => void; onModify: (action: RunAction, patch: Record<string, unknown> | string) => void; onReject: (action: RunAction) => void; onRetry: (action: RunAction) => void; onAttachDescriptors: (action: RunAction, descriptors: StagedAttachmentDescriptor[]) => Promise<void> | void;
}): JSX.Element {
  const [acknowledgements, setAcknowledgements] = useState<Set<string>>(new Set());
  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState(false);
  const [modification, setModification] = useState("");
  const [modificationError, setModificationError] = useState<string | null>(null);
  const previousAction = useRef(action);
  const [beforeAction, setBeforeAction] = useState<RunAction | null>(null);
  const isTask = action.tool_name === "tasks_create_task";
  useEffect(() => {
    if (previousAction.current.version !== action.version) {
      if (JSON.stringify(previousAction.current.arguments) !== JSON.stringify(action.arguments)) setBeforeAction(previousAction.current);
      setAcknowledgements(new Set()); setEditValues({}); setModification(""); setEditing(false); setModificationError(null);
      previousAction.current = action;
    }
  }, [action]);
  const requiredAcknowledgements = action.required_acknowledgements ?? [];
  const editableFields = action.editable_fields ?? [];
  const patch = Object.fromEntries(Object.entries(editValues).filter(([, value]) => isTask || value.trim()).map(([key, value]) => [key, isTask && key === "due" && value === "" ? null : key === "notes" ? value : value.trim()]));
  const missingAcknowledgement = requiredAcknowledgements.some((item) => !acknowledgements.has(item));
  const duplicate = taskDuplicateDecision(action.risk);
  const conflict = calendarConflictDecision(action.risk);
  const feasibility = feasibilityDecision(action.risk);
  const argumentSummary = approvalArgumentSummary(action, taskListName);
  const submitModification = async (value: Record<string, unknown> | string): Promise<void> => {
    setModificationError(null);
    try { await onModify(action, value); }
    catch (error) { setModificationError(error instanceof ApiClientError ? error.message : "수정하지 못했습니다. 기존 내용을 유지합니다. 다시 요청해 주세요."); }
  };
  return (
    <article className="approval-conversation" aria-label={`${actionLabel(action.tool_name)} 승인 요청`} data-tool-name={action.tool_name}>
      <p className="approval-question">{actionLabel(action.tool_name)} 작업을 진행할까요?</p>
      {duplicate === "SIMILAR_CANDIDATE" ? <p className="status-warn">비슷한 기존 작업이 있습니다.</p> : null}
      {duplicate === "CLEAR_DUPLICATE" ? <p className="status-warn">동일한 작업이 이미 있습니다.</p> : null}
      {conflict === "WARNING" ? <p className="status-warn">겹칠 가능성이 있거나 업무 시간 밖의 일정입니다.</p> : null}
      {conflict === "HARD_CONFLICT" ? <p className="status-warn">해당 시간에 기존 일정이 있습니다.</p> : null}
      {feasibility === "RISK" ? <p className="status-warn">현재 일정 기준으로 가능한 시간이 제한적입니다.</p> : null}
      {feasibility === "INFEASIBLE" ? <p className="status-warn">현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수 없습니다.</p> : null}
      {hasOtherRisk(action.risk) ? <p className="status-warn">서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요.</p> : null}
      {isTask ? <dl className="metadata-list" aria-label="태스크 미리보기">{["title", "task_list_id", "due", "notes"].map((field) => <div key={field}><dt>{argumentLabel(field)}</dt><dd style={{ whiteSpace: "pre-wrap" }}>{field === "task_list_id" && taskListName ? taskListName : argumentValue(action, field) || (field === "due" ? "미지정" : "없음")}</dd></div>)}</dl> : <details open><summary>무엇을 실행하나요?</summary><dl className="metadata-list"><div><dt>작업</dt><dd>{actionLabel(action.tool_name)}</dd></div><div><dt>실행 방식</dt><dd>{effectLabel(action.effect_type)}</dd></div>{argumentSummary.map((item) => <div key={item.field}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}<div><dt>결과 확인</dt><dd>{verificationLabel(action.verification_policy)}</dd></div></dl></details>}
      {isTask && beforeAction ? <details><summary>수정 전후 비교 · 다시 승인해 주세요</summary><dl className="metadata-list">{["title", "due", "notes"].filter((field) => argumentValue(beforeAction, field) !== argumentValue(action, field)).map((field) => <div key={field}><dt>{argumentLabel(field)}</dt><dd>{argumentValue(beforeAction, field) || "없음"} → {argumentValue(action, field) || "없음"}</dd></div>)}</dl></details> : null}
      {approval ? <div className="muted">{approvalStatusLabel(approval.status)}{approval.status === "ACTIVE" ? ` · ${formatTime(approval.expires_at_ms)}까지 유효합니다.` : ""}</div> : null}
      {requiredAcknowledgements.map((item) => (
        <label key={item}><input type="checkbox" checked={acknowledgements.has(item)} onChange={(event) => setAcknowledgements((current) => { const next = new Set(current); if (event.target.checked) next.add(item); else next.delete(item); return next; })} /> {item === "TASK_DUPLICATE" ? "중복 가능성을 확인했습니다." : "일정 충돌 가능성을 확인했습니다."}</label>
      ))}
      {isTask && editing && action.next_allowed_commands.includes("MODIFY_ACTION") ? <div><label>어떻게 수정할까요?<textarea value={modification} maxLength={2000} placeholder="예정일을 9월 8일로 바꾸고 메모는 빼줘" onChange={(event) => setModification(event.target.value)} /></label><button className="button-secondary" type="button" disabled={busy !== null || !modification.trim()} onClick={() => void submitModification(modification)}>수정 요청</button><p className="muted">변경 내용을 검토한 뒤 새 미리보기에서 다시 승인합니다.</p></div> : null}
      {modificationError ? <p role="alert">{modificationError}</p> : null}
      {busy === `modify-${action.action_id}` ? <p role="status">수정 내용을 검토하고 있습니다…</p> : null}
      {action.next_allowed_commands.includes("MODIFY_ACTION") && editableFields.some((field) => field !== "attachments") ? <details open={isTask ? undefined : true}><summary>직접 편집</summary><fieldset><legend>바꾸고 싶은 내용</legend>{editableFields.filter((field) => field !== "attachments").map((field) => <label key={field}>{argumentLabel(field)}<input value={editValues[field] ?? (isTask ? argumentValue(action, field) : "")} placeholder={argumentValue(action, field)} onChange={(event) => setEditValues((current) => ({ ...current, [field]: event.target.value }))} /></label>)}<button className="button-secondary" type="button" disabled={busy !== null || Object.keys(patch).length === 0} onClick={() => void submitModification(patch)}>이 내용으로 바꿀게요</button></fieldset></details> : null}
      {action.attachment_allowed && action.next_allowed_commands.includes("MODIFY_ACTION") ? <AttachmentPicker disabled={busy !== null} onStaged={(descriptors) => onAttachDescriptors(action, descriptors)} /> : null}
      <div className="button-row">
        {action.next_allowed_commands.includes("APPROVE_ACTION") ? <button className="button-primary" type="button" disabled={busy !== null || missingAcknowledgement} onClick={() => onApprove(action, acknowledgements)}>{isTask && (duplicate === null || duplicate === "NOT_DUPLICATE") ? "만들기" : approvalLabel(duplicate, conflict)}</button> : null}
        {isTask && action.next_allowed_commands.includes("MODIFY_ACTION") ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => setEditing((current) => !current)}>수정</button> : null}
        {action.next_allowed_commands.includes("REJECT_ACTION") ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => onReject(action)}>{isTask ? "건너뛰기" : "이번에는 실행하지 않을게요"}</button> : null}
        {canRetry ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => onRetry(action)}>다시 준비해 주세요</button> : null}
      </div>
      {action.status === "UNKNOWN_RESULT" ? <p className="status-warn">실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</p> : null}
      {isTask && action.status === "REJECTED" ? <p>건너뛴 작업입니다.</p> : null}
    </article>
  );
}

function approvalLabel(duplicate: ReturnType<typeof taskDuplicateDecision>, conflict: ReturnType<typeof calendarConflictDecision>): string {
  if (conflict === "HARD_CONFLICT") return "충돌을 알고도 실행해 주세요";
  if (duplicate === "CLEAR_DUPLICATE") return "그래도 새로 만들어 주세요";
  if (conflict === "WARNING" || duplicate === "SIMILAR_CANDIDATE") return "위험을 확인하고 실행해 주세요";
  return "네, 실행해 주세요";
}

function actionLabel(toolName: string): string {
  if (toolName === "github_close_issue") return "GitHub 이슈 닫기";
  if (toolName === "github_reopen_issue") return "GitHub 이슈 다시 열기";
  if (toolName.startsWith("github_")) return toolName.includes("create") ? "이슈 만들기" : "이슈 변경";
  if (toolName.startsWith("gmail_")) return toolName.includes("send") ? "메일 보내기" : toolName.includes("draft") ? "메일 초안 만들기" : "메일 작업";
  if (toolName.startsWith("tasks_")) return toolName.includes("create") ? "태스크 만들기" : "태스크 변경";
  if (toolName.startsWith("calendar_")) return toolName.includes("create") ? "일정 만들기" : "일정 변경";
  return "요청한 작업";
}

function effectLabel(effectType: string): string {
  return ({ CREATE: "새로 만들기", UPDATE: "내용 변경", DELETE: "삭제", SEND: "보내기" } as Record<string, string>)[effectType] ?? "요청대로 처리";
}

function verificationLabel(policy: string): string {
  return policy === "GET_COMPARE" ? "실행 후 다시 조회해 확인" : policy === "GET_ABSENT" ? "실행 후 삭제 여부 확인" : "실행 결과 확인";
}

function approvalStatusLabel(status: string): string {
  return ({ ACTIVE: "승인이 완료됐습니다.", APPROVED: "승인이 완료됐습니다.", REVOKED: "이전 승인은 취소되었습니다. 다시 승인해 주세요.", REJECTED: "실행하지 않기로 했습니다.", EXPIRED: "승인 시간이 지났습니다." } as Record<string, string>)[status] ?? "승인 상태를 확인하고 있습니다.";
}

const ARGUMENT_LABELS: Record<string, string> = {
  repository: "저장소",
  issue_number: "이슈 번호",
  state: "상태",
  to: "받는 사람",
  cc: "참조",
  bcc: "숨은 참조",
  subject: "제목",
  body: "본문",
  calendar_id: "캘린더",
  task_list_id: "태스크 목록",
  tasklist_id: "태스크 목록",
  task_id: "태스크",
  status: "상태",
  title: "제목",
  start: "시작",
  end: "종료",
  timezone: "시간대",
  due: "예정일",
  notes: "메모",
  description: "설명",
  attendees: "참석자",
  thread_id: "답장 대화",
  in_reply_to: "답장 대상 메일",
};

function approvalArgumentSummary(action: RunAction, taskListName?: string): Array<{ field: string; label: string; value: string }> {
  const preferredFields = action.tool_name.startsWith("gmail_")
    ? ["to", "cc", "bcc", "subject", "body", "thread_id", "in_reply_to"]
    : action.tool_name.startsWith("tasks_")
      ? ["task_list_id", "task_id", "status", "title", "due", "notes"]
      : action.tool_name.startsWith("calendar_")
        ? ["calendar_id", "title", "start", "end", "timezone", "description", "attendees"]
        : action.tool_name.startsWith("github_") ? ["repository", "issue_number", "title", "body", "state"] : action.editable_fields;
  return preferredFields.flatMap((field) => {
    const value = field === "task_list_id" && taskListName
      ? taskListName
      : argumentValue(action, field);
    return value ? [{ field, label: argumentLabel(field), value }] : [];
  });
}

function argumentValue(action: RunAction, field: string): string {
  const payload = action.arguments.payload;
  const payloadFields = payload && typeof payload === "object" && !Array.isArray(payload)
    ? payload as Record<string, unknown>
    : {};
  const nested = field === "due"
    ? payloadFields.due ?? payloadFields.scheduled_date
    : payloadFields[field];
  const value = nested ?? action.arguments[field];
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value === null || value === undefined) return "";
  if (field === "task_list_id" && value === "@default") return "내 할 일 목록";
  if (field === "calendar_id" && value === "primary") return "기본 캘린더";
  if (field === "status" && value === "completed") return "완료";
  if (field === "status" && value === "needsAction") return "미완료";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function argumentLabel(field: string): string {
  return ARGUMENT_LABELS[field] ?? field;
}
