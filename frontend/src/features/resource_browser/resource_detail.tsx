import type {
  CalendarResourceDetailResponse,
  GmailResourceDetailResponse,
  ResourceItem,
  TaskResourceDetailResponse,
} from "../../api/contract";
import { AttachmentList } from "../attachment";

export type GmailDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: GmailResourceDetailResponse | null;
  error: string | null;
};

export type TaskDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: TaskResourceDetailResponse | null;
  error: string | null;
};

export type CalendarDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: CalendarResourceDetailResponse | null;
  error: string | null;
};

export type ResourceDetailProps = {
  focusItem: ResourceItem | null;
  gmailDetail: GmailDetailState;
  taskDetail: TaskDetailState;
  calendarDetail: CalendarDetailState;
  onRetryGmailDetail: () => void;
  onRetryTaskDetail: () => void;
  onRetryCalendarDetail: () => void;
  onDownloadGmailAttachment: (messageId: string, attachmentId: string) => void;
  onDrillInto: () => void;
  presentResource: (item: ResourceItem) => {
    title: string | null;
    secondary: string | null;
    snippet: string | null;
    time: string | null;
  };
  metadataEntriesFor: (item: ResourceItem) => Array<[string, string]>;
  emptyMessage: string;
  formatMailboxIdentity: (name: string | null, email: string | null) => string | null;
};

export function ResourceDetail({
  focusItem,
  gmailDetail,
  taskDetail,
  calendarDetail,
  onRetryGmailDetail,
  onRetryTaskDetail,
  onRetryCalendarDetail,
  onDownloadGmailAttachment,
  onDrillInto,
  presentResource,
  metadataEntriesFor,
  emptyMessage,
  formatMailboxIdentity,
}: ResourceDetailProps): JSX.Element {
  const canonicalUrl = focusItem
    ? gmailDetail.detail?.resource_id === focusItem.resource_id
      ? gmailDetail.detail.canonical_url
      : focusItem.link_url
    : null;
  const metadataEntries = focusItem ? metadataEntriesFor(focusItem) : [];

  return (
    <section
      className={`resource-viewer${focusItem ? "" : " resource-viewer--empty"}`}
      aria-label="선택 자료 상세"
    >
      {focusItem ? (
        <div className="viewer-actions viewer-actions-floating">
          {canonicalUrl && hasCanonicalResourceUrl(canonicalUrl) ? (
            <button
              className="icon-button icon-button--plain"
              type="button"
              aria-label={focusItem.source === "github" ? "GitHub에서 열기" : "Google에서 열기"}
              title={focusItem.source === "github" ? "GitHub에서 열기" : "Google에서 열기"}
              onClick={() => window.open(safeResourceLink(canonicalUrl), "_blank", "noopener,noreferrer")}
            >
              ↗
            </button>
          ) : null}
          {focusItem.parent_id && (focusItem.source === "tasks" || focusItem.source === "calendar") ? (
            <button
              className="icon-button"
              type="button"
              aria-label="하위 자료 보기"
              title="하위 자료 보기"
              onClick={onDrillInto}
            >
              →
            </button>
          ) : null}
        </div>
      ) : (
        <div className="section-heading">
          <strong>자료 상세</strong>
        </div>
      )}
      {focusItem ? (
        focusItem.resource_type === "gmail_thread" ? (
          <GmailDetailViewer
            state={gmailDetail}
            onRetry={onRetryGmailDetail}
            onDownloadAttachment={onDownloadGmailAttachment}
            formatMailboxIdentity={formatMailboxIdentity}
          />
        ) : focusItem.resource_type === "task" ? (
          <TaskDetailViewer state={taskDetail} onRetry={onRetryTaskDetail} />
        ) : focusItem.resource_type === "calendar_event" ? (
          <CalendarDetailViewer state={calendarDetail} onRetry={onRetryCalendarDetail} />
        ) : (
          <>
            <h2>{presentResource(focusItem).title ?? "제목 없음"}</h2>
            {presentResource(focusItem).secondary ? <p>{presentResource(focusItem).secondary}</p> : null}
            {metadataEntries.length > 0 ? (
              <dl className="metadata-list">
                {metadataEntries.map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="muted">현재 목록에서 제공된 상세 정보가 없습니다.</p>
            )}
          </>
        )
      ) : (
        <p className="muted">{emptyMessage}</p>
      )}
    </section>
  );
}

function TaskDetailViewer({ state, onRetry }: { state: TaskDetailState; onRetry: () => void }): JSX.Element {
  if (state.status === "loading") return <div className="viewer-state" role="status">태스크 상세를 불러오는 중입니다.</div>;
  if (state.status === "error") return <DetailError message={state.error ?? "태스크 상세를 불러오지 못했습니다."} onRetry={onRetry} />;
  if (state.status !== "ready" || !state.detail) return <div className="viewer-state">태스크를 선택해 주세요.</div>;
  const detail = state.detail;
  return (
    <article>
      <h2>{detail.title || "제목 없음"}</h2>
      <dl className="metadata-list">
        <DetailEntry label="상태" value={detail.task_status === "completed" ? "완료" : "미완료"} />
        <DetailEntry label="예정일" value={formatTaskDetailDate(detail.scheduled_date)} />
        <DetailEntry label="완료 시각" value={formatResourceDetailDate(detail.completed_at)} />
        <DetailEntry label="노트" value={detail.notes} />
      </dl>
    </article>
  );
}

function CalendarDetailViewer({ state, onRetry }: { state: CalendarDetailState; onRetry: () => void }): JSX.Element {
  if (state.status === "loading") return <div className="viewer-state" role="status">일정 상세를 불러오는 중입니다.</div>;
  if (state.status === "error") return <DetailError message={state.error ?? "일정 상세를 불러오지 못했습니다."} onRetry={onRetry} />;
  if (state.status !== "ready" || !state.detail) return <div className="viewer-state">일정을 선택해 주세요.</div>;
  const detail = state.detail;
  return (
    <article>
      <h2>{detail.title || "제목 없음"}</h2>
      <dl className="metadata-list">
        <DetailEntry label="시작 시간" value={formatResourceDetailDate(detail.start)} />
        <DetailEntry label="종료 시간" value={formatResourceDetailDate(detail.end)} />
        <DetailEntry label="시간대" value={detail.timezone} />
        <DetailEntry label="참석자" value={detail.attendees.length ? detail.attendees.join(", ") : null} />
        <DetailEntry label="장소" value={detail.location} />
        <DetailEntry label="설명" value={detail.description} />
      </dl>
    </article>
  );
}

function DetailEntry({ label, value }: { label: string; value: string | null }): JSX.Element | null {
  if (!value) return null;
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function DetailError({ message, onRetry }: { message: string; onRetry: () => void }): JSX.Element {
  return <div className="viewer-state" role="alert"><p>{message}</p><button className="button-secondary" type="button" onClick={onRetry}>다시 시도</button></div>;
}

function formatTaskDetailDate(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatResourceDetailDate(value);
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return `${date.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" })} (${date.toLocaleDateString("ko-KR", { weekday: "short" })})`;
}

function formatResourceDetailDate(value: string | null): string | null {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatTaskDetailDate(value);
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function GmailDetailViewer({
  state,
  onRetry,
  onDownloadAttachment,
  formatMailboxIdentity,
}: {
  state: GmailDetailState;
  onRetry: () => void;
  onDownloadAttachment: (messageId: string, attachmentId: string) => void;
  formatMailboxIdentity: (name: string | null, email: string | null) => string | null;
}): JSX.Element {
  if (state.status === "loading") {
    return (
      <div className="viewer-state" role="status">
        메일 내용을 불러오는 중입니다.
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="viewer-state" role="alert">
        <p>{state.error ?? "메일 내용을 불러오지 못했습니다."}</p>
        <button className="button-secondary" type="button" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    );
  }
  if (state.status !== "ready" || !state.detail) {
    return <div className="viewer-state">메일 내용을 선택해 주세요.</div>;
  }

  const detail = state.detail;
  const sender = formatMailboxIdentity(detail.sender_name, detail.sender_email);
  const receivedAt = formatDetailDate(detail.received_at);
  return (
    <article className="gmail-detail">
      <header className="gmail-detail-header">
        <div className="gmail-detail-sender">
          {sender ? <strong>{sender}</strong> : <strong className="muted">보낸 사람 정보가 없습니다.</strong>}
          <div className="gmail-detail-meta">
            {detail.recipients.length > 0 ? <span>받는 사람 {detail.recipients.join(", ")}</span> : null}
            {detail.cc.length > 0 ? <span>참조 {detail.cc.join(", ")}</span> : null}
            {receivedAt ? <time>{receivedAt}</time> : null}
          </div>
        </div>
        {detail.subject ? <h2>{detail.subject}</h2> : null}
      </header>
      {detail.body ? (
        <div className="gmail-detail-body">{detail.body}</div>
      ) : (
        <p className="viewer-empty">표시할 메일 내용이 없습니다.</p>
      )}
      <AttachmentList messageId={detail.message_id} attachments={detail.attachments} onDownload={onDownloadAttachment} />
    </article>
  );
}

function formatDetailDate(value: string | null): string | null {
  const date = parsedResourceDate(value);
  return (
    date?.toLocaleString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }) ?? null
  );
}

function parsedResourceDate(value: string | null): Date | null {
  if (!value) return null;
  const milliseconds = /^\d{12,}$/.test(value) ? Number(value) : Date.parse(value);
  if (!Number.isFinite(milliseconds)) return null;
  const date = new Date(milliseconds);
  return Number.isNaN(date.getTime()) ? null : date;
}

function safeResourceLink(url: string): string {
  if (!hasCanonicalResourceUrl(url)) return "https://github.com/issues";
  return new URL(url).toString();
}

function hasCanonicalResourceUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const allowedHosts = new Set(["mail.google.com", "tasks.google.com", "calendar.google.com", "github.com"]);
    return parsed.protocol === "https:" && allowedHosts.has(parsed.host);
  } catch {
    return false;
  }
}
