import { useEffect, useRef, useState } from "react";
import type { ApprovalSnapshot, RunAction, RunSnapshot } from "../../api/contract";
import { AttachmentPicker, type StagedAttachmentDescriptor } from "../attachment";
import { calendarConflictDecision, feasibilityDecision, hasOtherRisk, taskDuplicateDecision } from "./risk_presentation";
import { listTaskLists } from "../resource_browser/api/list_resources";
import { ApiClientError } from "../../api/client";
import {
  UserActionCard,
  UserActionDisclosure,
  UserActionEditor,
  UserActionField,
  UserActionFields,
  UserActionNotice,
  type UserActionGlyphName,
} from "../../ui/user_action_card";

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
      {snapshot.current_plan.summary_text ? <p className="action-plan-summary">{snapshot.current_plan.summary_text}</p> : null}
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
  const patch = buildArgumentsPatch(action, editValues);
  const missingAcknowledgement = requiredAcknowledgements.some((item) => !acknowledgements.has(item));
  const duplicate = taskDuplicateDecision(action.risk);
  const conflict = calendarConflictDecision(action.risk);
  const feasibility = feasibilityDecision(action.risk);
  const argumentSummary = approvalArgumentSummary(action, taskListName);
  const previewItems = isTask
    ? ["title", "task_list_id", "due", "notes"].map((field) => ({
      field,
      label: argumentLabel(field),
      value: field === "task_list_id"
          ? taskListDisplayName(action, taskListName)
          : displayArgumentValue(action, field) || (field === "due" ? "미지정" : "없음"),
      }))
    : argumentSummary.filter((item) => !["thread_id", "in_reply_to"].includes(item.field));
  const directEditFields = editableFields.filter((field) => field !== "attachments");
  const canModify = action.next_allowed_commands.includes("MODIFY_ACTION")
    && (isTask || directEditFields.length > 0 || action.attachment_allowed);
  const showInlineEditor = editing && !isTask && directEditFields.length > 0;
  const submitModification = async (value: Record<string, unknown> | string): Promise<boolean> => {
    setModificationError(null);
    try {
      await onModify(action, value);
      return true;
    } catch (error) {
      setModificationError(error instanceof ApiClientError ? error.message : "수정하지 못했습니다. 기존 내용을 유지합니다. 다시 요청해 주세요.");
      return false;
    }
  };
  const toggleEditing = async (): Promise<void> => {
    if (!editing) {
      setEditing(true);
      return;
    }
    if (Object.keys(patch).length > 0 && !(await submitModification(patch))) return;
    setEditing(false);
  };
  return (
    <UserActionCard
      tone="approval"
      glyph={actionGlyph(action.tool_name)}
      title={actionQuestion(action.tool_name)}
      description="내용을 확인한 뒤 실행 여부를 선택해 주세요."
      ariaLabel={`${actionLabel(action.tool_name)} 승인 요청`}
      dataToolName={action.tool_name}
      footer={(
        <>
          {action.next_allowed_commands.includes("REJECT_ACTION") ? <button className="button-quiet" type="button" disabled={busy !== null} onClick={() => onReject(action)}>건너뛰기</button> : null}
          <div className="user-action-footer-main">
            {canModify ? <button className={editing ? "button-primary" : "button-secondary"} type="button" disabled={busy !== null} aria-expanded={editing} onClick={() => void toggleEditing()}>{editing ? "수정 완료" : "수정"}</button> : null}
            {canRetry ? <button className="button-secondary" type="button" disabled={busy !== null} onClick={() => onRetry(action)}>다시 준비해 주세요</button> : null}
            {action.next_allowed_commands.includes("APPROVE_ACTION") ? <button className="button-primary" type="button" disabled={editing || busy !== null || missingAcknowledgement} title={editing ? "수정 완료 후 실행할 수 있습니다." : undefined} onClick={() => onApprove(action, acknowledgements)}>{approvalPrimaryLabel(duplicate, conflict)}</button> : null}
          </div>
        </>
      )}
    >
      {duplicate === "SIMILAR_CANDIDATE" ? <UserActionNotice>비슷한 기존 작업이 있습니다.</UserActionNotice> : null}
      {duplicate === "CLEAR_DUPLICATE" ? <UserActionNotice>동일한 작업이 이미 있습니다.</UserActionNotice> : null}
      {conflict === "WARNING" ? <UserActionNotice>겹칠 가능성이 있거나 업무 시간 밖의 일정입니다.</UserActionNotice> : null}
      {conflict === "HARD_CONFLICT" ? <UserActionNotice>해당 시간에 기존 일정이 있습니다.</UserActionNotice> : null}
      {feasibility === "RISK" ? <UserActionNotice>현재 일정 기준으로 가능한 시간이 제한적입니다.</UserActionNotice> : null}
      {feasibility === "INFEASIBLE" ? <UserActionNotice>현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수 없습니다.</UserActionNotice> : null}
      {hasOtherRisk(action.risk) ? <UserActionNotice>서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요.</UserActionNotice> : null}

      {showInlineEditor ? <UserActionEditor title={null}>
        <DirectEditor action={action} fields={directEditFields} values={editValues} onChange={setEditValues} />
        {action.attachment_allowed ? <div className="user-action-attachment"><AttachmentPicker disabled={busy !== null} onStaged={(descriptors) => onAttachDescriptors(action, descriptors)} /></div> : null}
      </UserActionEditor> : <UserActionFields label={isTask ? "태스크 미리보기" : `${actionLabel(action.tool_name)} 미리보기`}>
        {previewItems.map((item) => <UserActionField key={item.field} label={item.label} value={item.value} multiline={isMultilineField(item.field)} hideLabel={item.field === "body"} />)}
      </UserActionFields>}

      {requiredAcknowledgements.length > 0 ? <div className="user-action-acknowledgements">{requiredAcknowledgements.map((item) => (
        <label key={item}><input type="checkbox" checked={acknowledgements.has(item)} onChange={(event) => setAcknowledgements((current) => { const next = new Set(current); if (event.target.checked) next.add(item); else next.delete(item); return next; })} /> <span>{item === "TASK_DUPLICATE" ? "중복 가능성을 확인했습니다." : "일정 충돌 가능성을 확인했습니다."}</span></label>
      ))}</div> : null}

      {isTask && beforeAction ? <UserActionDisclosure label="수정 전후 비교 · 다시 승인해 주세요"><UserActionFields label="수정 전후 비교">{["title", "due", "notes"].filter((field) => argumentValue(beforeAction, field) !== argumentValue(action, field)).map((field) => <UserActionField key={field} label={argumentLabel(field)} value={<>{argumentValue(beforeAction, field) || "없음"} → {argumentValue(action, field) || "없음"}</>} multiline={isMultilineField(field)} />)}</UserActionFields></UserActionDisclosure> : null}

      {approval ? <p className="user-action-status">{approvalStatusLabel(approval.status)}{approval.status === "ACTIVE" ? ` · ${formatTime(approval.expires_at_ms)}까지 유효합니다.` : ""}</p> : null}

      {editing && canModify && isTask ? <UserActionEditor>
        {isTask ? <div className="user-action-form"><label>어떻게 수정할까요?<textarea value={modification} maxLength={2000} rows={3} placeholder="예정일을 9월 8일로 바꾸고 메모는 빼줘" onChange={(event) => setModification(event.target.value)} /></label><div className="user-action-editor-actions"><button className="button-secondary" type="button" disabled={busy !== null || !modification.trim()} onClick={() => void submitModification(modification)}>수정 요청</button><span>변경 후 새 미리보기에서 다시 승인합니다.</span></div></div> : null}
        {directEditFields.length > 0 ? <UserActionDisclosure label="직접 편집"><DirectEditor action={action} fields={directEditFields} values={editValues} onChange={setEditValues} /></UserActionDisclosure> : null}
        {action.attachment_allowed ? <div className="user-action-attachment"><AttachmentPicker disabled={busy !== null} onStaged={(descriptors) => onAttachDescriptors(action, descriptors)} /></div> : null}
      </UserActionEditor> : null}
      {editing && canModify && !isTask && directEditFields.length === 0 && action.attachment_allowed ? <UserActionEditor title={null}><div className="user-action-attachment"><AttachmentPicker disabled={busy !== null} onStaged={(descriptors) => onAttachDescriptors(action, descriptors)} /></div></UserActionEditor> : null}

      {modificationError ? <p className="user-action-error" role="alert">{modificationError}</p> : null}
      {busy === `modify-${action.action_id}` ? <p className="user-action-status" role="status">수정 내용을 검토하고 있습니다…</p> : null}
      {action.status === "UNKNOWN_RESULT" ? <UserActionNotice>실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</UserActionNotice> : null}
      {isTask && action.status === "REJECTED" ? <p className="user-action-status">건너뛴 작업입니다.</p> : null}
    </UserActionCard>
  );
}

function DirectEditor({ action, fields, values, onChange }: {
  action: RunAction;
  fields: string[];
  values: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
}): JSX.Element {
  return (
    <div className="user-action-form" role="group" aria-label="바꾸고 싶은 내용">
      {fields.map((field) => {
        const value = values[field] ?? argumentValue(action, field);
        const handleChange = (nextValue: string) => onChange({ ...values, [field]: nextValue });
        return (
          <label key={field}>
            <span className={field === "body" ? "sr-only" : undefined}>{argumentLabel(field)}</span>
            {isMultilineField(field)
              ? <textarea rows={4} value={value} placeholder={argumentValue(action, field)} onChange={(event) => handleChange(event.target.value)} />
              : <input value={value} placeholder={argumentValue(action, field)} onChange={(event) => handleChange(event.target.value)} />}
          </label>
        );
      })}
    </div>
  );
}

function approvalLabel(duplicate: ReturnType<typeof taskDuplicateDecision>, conflict: ReturnType<typeof calendarConflictDecision>): string {
  if (conflict === "HARD_CONFLICT") return "충돌을 알고도 실행해 주세요";
  if (duplicate === "CLEAR_DUPLICATE") return "그래도 새로 만들어 주세요";
  if (conflict === "WARNING" || duplicate === "SIMILAR_CANDIDATE") return "위험을 확인하고 실행해 주세요";
  return "확인";
}

function approvalPrimaryLabel(duplicate: ReturnType<typeof taskDuplicateDecision>, conflict: ReturnType<typeof calendarConflictDecision>): string {
  return approvalLabel(duplicate, conflict);
}

function actionLabel(toolName: string): string {
  if (toolName === "github_close_issue") return "이슈 닫기";
  if (toolName === "github_reopen_issue") return "이슈 다시 열기";
  if (toolName.startsWith("github_")) return toolName.includes("create") ? "이슈 만들기" : "이슈 변경";
  if (toolName === "gmail_create_draft" || toolName === "gmail_draft") return "초안 만들기";
  if (toolName === "gmail_update_draft") return "초안 수정";
  if (toolName.startsWith("gmail_")) return toolName.includes("send") ? "메일 보내기" : "메일 작업";
  if (toolName.startsWith("tasks_")) return toolName.includes("create") ? "태스크 만들기" : "태스크 변경";
  if (toolName === "calendar_delete_event") return "일정 삭제";
  if (toolName.startsWith("calendar_")) return toolName.includes("create") ? "일정 만들기" : "일정 변경";
  return "요청한 작업";
}

function actionQuestion(toolName: string): string {
  if (toolName === "gmail_create_draft" || toolName === "gmail_draft") return "초안을 만들까요?";
  if (toolName === "gmail_update_draft") return "초안을 수정할까요?";
  if (toolName === "gmail_send") return "메일을 보낼까요?";
  if (toolName === "tasks_create_task") return "태스크를 만들까요?";
  if (toolName === "tasks_update_task") return "태스크를 수정할까요?";
  if (toolName === "calendar_create_event") return "일정을 만들까요?";
  if (toolName === "calendar_update_event") return "일정을 수정할까요?";
  if (toolName === "calendar_delete_event") return "일정을 삭제할까요?";
  if (toolName === "github_create_issue") return "이슈를 만들까요?";
  if (toolName === "github_close_issue") return "이슈를 닫을까요?";
  if (toolName === "github_reopen_issue") return "이슈를 다시 열까요?";
  if (toolName === "github_update_issue") return "이슈를 수정할까요?";
  return "요청한 작업을 진행할까요?";
}

function actionGlyph(toolName: string): UserActionGlyphName {
  if (toolName.startsWith("gmail_")) return "mail";
  if (toolName.startsWith("tasks_")) return "task";
  if (toolName.startsWith("calendar_")) return "calendar";
  if (toolName.startsWith("github_")) return "github";
  return "action";
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
  location: "장소",
  attendees: "참석자",
  thread_id: "답장 대화",
  in_reply_to: "답장 대상 메일",
};

function approvalArgumentSummary(action: RunAction, taskListName?: string): Array<{ field: string; label: string; value: string }> {
  if (action.tool_name.startsWith("calendar_")) return calendarApprovalSummary(action);
  if (action.tool_name.startsWith("github_")) return githubApprovalSummary(action);
  if (action.tool_name.startsWith("tasks_")) return taskApprovalSummary(action, taskListName);
  const preferredFields = action.tool_name.startsWith("gmail_")
    ? ["to", "cc", "bcc", "subject", "body", "thread_id", "in_reply_to"]
    : action.editable_fields;
  return preferredFields.flatMap((field) => {
    const value = field === "task_list_id" && taskListName
      ? taskListName
      : displayArgumentValue(action, field);
    return value ? [{ field, label: argumentLabel(field), value }] : [];
  });
}

function taskApprovalSummary(action: RunAction, taskListName?: string): Array<{ field: string; label: string; value: string }> {
  return [
    { field: "task_list_id", label: "태스크 목록", value: taskListDisplayName(action, taskListName) },
    { field: "title", label: "제목", value: displayArgumentValue(action, "title") },
    { field: "due", label: "예정일", value: displayArgumentValue(action, "due") },
    { field: "status", label: "상태", value: displayArgumentValue(action, "status") },
    { field: "notes", label: "메모", value: displayArgumentValue(action, "notes") },
  ].filter((item) => item.value);
}

function taskListDisplayName(action: RunAction, taskListName?: string): string {
  if (taskListName) return taskListName;
  return argumentValue(action, "task_list_id") === "내 할 일 목록" ? "내 할 일 목록" : "";
}

function calendarApprovalSummary(action: RunAction): Array<{ field: string; label: string; value: string }> {
  const start = displayArgumentValue(action, "start");
  const end = displayArgumentValue(action, "end");
  const schedule = formatCalendarSchedule(start, end);
  return [
    { field: "title", label: "제목", value: displayArgumentValue(action, "title") },
    { field: "schedule", label: "일시", value: schedule },
    { field: "location", label: "장소", value: displayArgumentValue(action, "location") },
    { field: "description", label: "설명", value: displayArgumentValue(action, "description") },
    { field: "attendees", label: "참석자", value: displayArgumentValue(action, "attendees") },
  ].filter((item) => item.value);
}

function githubApprovalSummary(action: RunAction): Array<{ field: string; label: string; value: string }> {
  const repository = argumentValue(action, "repository");
  const issueNumber = argumentValue(action, "issue_number");
  const isCreate = action.tool_name === "github_create_issue";
  const target = !isCreate && repository && issueNumber
    ? `${repository} #${issueNumber}`
    : repository;
  return [
    { field: isCreate ? "repository" : "issue", label: isCreate ? "저장소" : "이슈", value: target },
    { field: "title", label: "제목", value: displayArgumentValue(action, "title") },
    { field: "state", label: "상태", value: githubTargetState(action) },
    { field: "body", label: "본문", value: displayArgumentValue(action, "body") },
  ].filter((item) => item.value);
}

function githubTargetState(action: RunAction): string {
  if (action.tool_name === "github_close_issue") return "닫힘";
  if (action.tool_name === "github_reopen_issue") return "열림";
  return displayArgumentValue(action, "state");
}

function displayArgumentValue(action: RunAction, field: string): string {
  const current = argumentValue(action, field);
  const value = current || action.target_display?.[field] || "";
  if (field === "status" && value === "completed") return "완료";
  if (field === "status" && value === "needsAction") return "미완료";
  if (field === "state" && value === "open") return "열림";
  if (field === "state" && value === "closed") return "닫힘";
  return value;
}

function formatCalendarSchedule(start: string, end: string): string {
  if (!start) return end;
  if (/^\d{4}-\d{2}-\d{2}$/.test(start)) return `${formatCalendarDate(start)} · 하루 종일`;
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : null;
  if (Number.isNaN(startDate.getTime())) return end ? `${start} ~ ${end}` : start;
  const date = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "short",
  }).format(startDate);
  if (!endDate || Number.isNaN(endDate.getTime())) return `${date} ${formatCalendarTime(startDate)}`;
  return `${date} ${formatCalendarTime(startDate)} ~ ${formatCalendarTime(endDate)}`;
}

function formatCalendarTime(value: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(value);
  const hour = Number(parts.find((part) => part.type === "hour")?.value);
  const minute = parts.find((part) => part.type === "minute")?.value;
  if (!Number.isInteger(hour) || minute === undefined) return "";
  return `${hour < 12 ? "오전" : "오후"} ${hour % 12 || 12}:${minute}`;
}

function formatCalendarDate(value: string): string {
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "short",
  }).format(new Date(Date.UTC(year, month - 1, day, 12)));
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

function buildArgumentsPatch(action: RunAction, editValues: Record<string, string>): Record<string, unknown> {
  const isTask = action.tool_name === "tasks_create_task";
  const patch: Record<string, unknown> = {};
  for (const [field, value] of Object.entries(editValues)) {
    if (isTask) {
      patch[field] = field === "due" && value === "" ? null : field === "notes" ? value : value.trim();
      continue;
    }
    if (action.tool_name.startsWith("calendar_")) {
      if (field === "attendees") {
        patch[field] = [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
        continue;
      }
      if (field === "description" || field === "location") {
        patch[field] = value.trim();
        continue;
      }
    }
    if (value.trim()) patch[field] = value.trim();
  }
  return patch;
}

function argumentLabel(field: string): string {
  return ARGUMENT_LABELS[field] ?? field;
}

function isMultilineField(field: string): boolean {
  return ["body", "description", "notes"].includes(field);
}
