import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CalendarContainer, ResourceItem, TaskListContainer } from "../../api/contract";
import { listCalendars, listTaskLists } from "./api/list_resources";
import { CalendarPanel } from "./calendar_panel";
import { GmailPanel } from "./gmail_panel";
import { GitHubPanel } from "./github_panel";
import { TasksPanel } from "./tasks_panel";
import { useCalendar } from "./calendar_controller";
import { useGmail } from "./gmail_controller";
import { useGitHubIssues } from "./github_controller";
import { useTasks } from "./tasks_controller";
import { buildSelectedResourceContext, type SelectedResourceContext } from "./selected_resource_context";

export type ResourceSource = "gmail" | "tasks" | "calendar" | "github";

export type ResourceBrowserProjection = {
  activeSource: ResourceSource | null;
  focusedItem: ResourceItem | null;
  selectedContext: SelectedResourceContext;
  composerPrompt: string;
  emptyMessage: string;
  focusedItemSelected: boolean;
  toggleFocusedSelection: () => void;
  openFocusedContainer: () => void;
};

type Props = {
  scopeKey: string;
  googleAccountId: string | null | undefined;
  githubAccountId: string | null | undefined;
  googleConnected: boolean;
  githubConnected: boolean;
  githubRepository: string | null | undefined;
  onOpenSettings?: () => void;
  timezone: string;
  onProjectionChange: (projection: ResourceBrowserProjection) => void;
};

const PAGE_SIZE = 20;

export function ResourceSidebar({ scopeKey, googleAccountId, githubAccountId, googleConnected, githubConnected, githubRepository, timezone, onProjectionChange, onOpenSettings }: Props): JSX.Element {
  const visibleSources = useMemo<ResourceSource[]>(() => [
    ...(googleConnected ? ["gmail", "calendar", "tasks"] as ResourceSource[] : []),
    ...(githubConnected ? ["github"] as ResourceSource[] : []),
  ], [githubConnected, googleConnected]);
  const [source, setSource] = useState<ResourceSource | null>(() => visibleSources[0] ?? null);
  const [filter, setFilter] = useState("");
  const [focusedItem, setFocusedItem] = useState<ResourceItem | null>(null);
  const [selectedItems, setSelectedItems] = useState<ResourceItem[]>([]);
  const [parentId, setParentId] = useState<string | null>(null);
  const [taskLists, setTaskLists] = useState<TaskListContainer[]>([]);
  const [calendars, setCalendars] = useState<CalendarContainer[]>([]);
  const [calendarsError, setCalendarsError] = useState<string | null>(null);
  const [calendarsLoading, setCalendarsLoading] = useState(false);
  const [taskListsNext, setTaskListsNext] = useState<string | null>(null);
  const [taskListsLoading, setTaskListsLoading] = useState(false);
  const [taskListsError, setTaskListsError] = useState<string | null>(null);
  const taskListsGeneration = useRef(0);
  const previousScopeKey = useRef(scopeKey);
  const gmail = useGmail({ accountId: googleAccountId, active: source === "gmail" });
  const tasks = useTasks({ accountId: googleAccountId, parentId, active: source === "tasks", filter });
  const calendar = useCalendar({ accountId: googleAccountId, calendarId: parentId, active: googleConnected && source === "calendar" && parentId !== null, timezone });
  const github = useGitHubIssues({ accountId: githubAccountId, repository: githubRepository, active: source === "github" });
  const { reset: resetGmail, loadCount: loadGmailCount, loadPage: loadGmailPage } = gmail;
  const { reset: resetTasks, preload: preloadTasks, loadCompleted: loadCompletedTasks, loadPage: loadTasksPage } = tasks;
  const { reset: resetCalendar } = calendar;
  const { reset: resetGitHub } = github;
  const selectedContext = useMemo(
    () => buildSelectedResourceContext(selectedItems, (item) => presentResource(item).title ?? "제목 없음"),
    [selectedItems],
  );
  const focusedItemSelected = focusedItem !== null && selectedContext.selectionHandles.includes(focusedItem.selection_handle);

  const loadTaskLists = useCallback(async (continuation: string | null = null): Promise<void> => {
    const generation = ++taskListsGeneration.current;
    setTaskListsLoading(true); setTaskListsError(null);
    try {
      const response = await listTaskLists(continuation);
      if (generation !== taskListsGeneration.current) return;
      setTaskLists((current) => [...new Map([...(continuation ? current : []), ...response.items].map((item) => [item.tasklist_id, item])).values()]);
      setTaskListsNext(response.next_page_token);
    } catch {
      if (generation === taskListsGeneration.current) setTaskListsError("태스크 목록을 불러오지 못했습니다. 연결 상태를 확인한 뒤 새로고침하세요.");
    } finally {
      if (generation === taskListsGeneration.current) setTaskListsLoading(false);
    }
  }, []);

  useEffect(() => {
    setTaskLists([]); setTaskListsNext(null); setTaskListsError(null);
    if (googleConnected && source === "tasks") void loadTaskLists();
    return () => { taskListsGeneration.current += 1; };
  }, [googleAccountId, googleConnected, loadTaskLists, scopeKey, source]);

  useEffect(() => {
    let disposed = false;
    setCalendars([]); setCalendarsError(null);
    if (!googleConnected || source !== "calendar") return;
    setCalendarsLoading(true);
    void (async () => {
      const items: CalendarContainer[] = [];
      const seen = new Set<string>();
      let cursor: string | null = null;
      for (let page = 0; page < 100; page += 1) {
        const result = await listCalendars(cursor);
        items.push(...result.items);
        cursor = result.next_page_token;
        if (!cursor) {
          if (!disposed) { setCalendars(items); setParentId((current) => current && items.some((item) => item.calendar_id === current) ? current : items[0]?.calendar_id ?? null); }
          return;
        }
        if (seen.has(cursor)) break;
        seen.add(cursor);
      }
      throw new Error("calendar inventory incomplete");
    })().catch(() => { if (!disposed) setCalendarsError("캘린더 목록을 확인하지 못했습니다. 설정에서 자료 선택과 연결 상태를 확인하세요."); }).finally(() => { if (!disposed) setCalendarsLoading(false); });
    return () => { disposed = true; };
  }, [googleAccountId, googleConnected, scopeKey, source]);

  const toggleItem = useCallback((item: ResourceItem): void => {
    setSelectedItems((current) => current.some((selected) => selected.selection_handle === item.selection_handle)
      ? current.filter((selected) => selected.selection_handle !== item.selection_handle)
      : [...current, item]);
  }, []);
  const toggleByResourceId = useCallback((resourceId: string, items: ResourceItem[]): void => {
    const item = items.find((candidate) => candidate.resource_id === resourceId);
    if (item) toggleItem(item);
  }, [toggleItem]);
  const toggleFocusedSelection = useCallback((): void => {
    if (focusedItem) toggleItem(focusedItem);
  }, [focusedItem, toggleItem]);
  const openFocusedContainer = useCallback((): void => {
    if (focusedItem?.parent_id) setParentId(focusedItem.parent_id);
  }, [focusedItem]);

  useEffect(() => {
    setSource((current) => current && visibleSources.includes(current) ? current : visibleSources[0] ?? null);
  }, [visibleSources]);

  useEffect(() => {
    if (previousScopeKey.current === scopeKey) return;
    previousScopeKey.current = scopeKey;
    resetGmail();
    resetTasks();
    resetCalendar();
    resetGitHub();
    setSelectedItems([]);
    setFocusedItem(null);
    setParentId(null);
  }, [resetCalendar, resetGitHub, resetGmail, resetTasks, scopeKey]);

  useEffect(() => {
    if (!googleConnected) return;
    void loadGmailCount();
    void preloadTasks();
    void loadCompletedTasks();
  }, [googleConnected, loadCompletedTasks, loadGmailCount, preloadTasks]);

  useEffect(() => {
    if (!googleConnected || source !== "gmail") return;
    if (!gmail.loaded && !gmail.loading && gmail.error === null) void loadGmailPage(gmail.pageIndex);
    else if (gmail.loaded && !gmail.countLoading) void loadGmailCount();
  }, [googleConnected, gmail.countLoading, gmail.error, gmail.loaded, gmail.loading, gmail.pageIndex, loadGmailCount, loadGmailPage, source]);

  useEffect(() => {
    if (!googleConnected || source !== "tasks") return;
    if (!tasks.loaded && !tasks.loading && tasks.error === null) void loadTasksPage(tasks.pageIndex);
  }, [googleConnected, loadTasksPage, source, tasks.error, tasks.loaded, tasks.loading, tasks.pageIndex]);

  useEffect(() => {
    if (source === "gmail" && !gmail.loaded) return;
    onProjectionChange({
      activeSource: source,
      focusedItem,
      selectedContext,
      composerPrompt: composerPrompt(source),
      emptyMessage: emptyMessage(source),
      focusedItemSelected,
      toggleFocusedSelection,
      openFocusedContainer,
    });
  }, [focusedItem, focusedItemSelected, gmail.loaded, onProjectionChange, openFocusedContainer, selectedContext, source, toggleFocusedSelection]);

  const visibleTaskItems = useMemo(() => {
    if (source !== "tasks") return [];
    const items = filter.trim()
      ? tasks.items.filter((item) => Object.values(presentResource(item)).filter(Boolean).some((value) => value!.toLocaleLowerCase("ko-KR").includes(filter.trim().toLocaleLowerCase("ko-KR"))))
      : tasks.items;
    return items.slice(tasks.pageIndex * PAGE_SIZE, (tasks.pageIndex + 1) * PAGE_SIZE);
  }, [filter, source, tasks.items, tasks.pageIndex]);
  const taskSections = useMemo(() => source === "tasks" && tasks.sort === "scheduled_date" ? groupTasksByScheduledDate(visibleTaskItems) : null, [source, tasks.sort, visibleTaskItems]);

  return (
    <aside className="panel resource-panel">
      <div className="panel-body">
        <div className="resource-tabbar">
          <div className="resource-tabs" role="tablist" aria-label="자료 종류">
            {visibleSources.map((tab) => <button key={tab} className={`resource-tab ${source === tab ? "selected" : ""}`} type="button" role="tab" aria-selected={source === tab} onClick={() => { setFilter(""); setSource(tab); setParentId(null); setFocusedItem(null); setSelectedItems([]); }}><span className="resource-tab-icon" aria-hidden="true">{tabIcon(tab)}</span><span className="resource-tab-label">{tabLabel(tab)}</span>{tab !== "calendar" ? <span className="resource-tab-count">{formatCount(tab === "gmail" ? gmail.count : tab === "tasks" ? tasks.count : github.loaded ? { value: github.items.length, exact: github.items.length < 100 } : null)}</span> : null}</button>)}
          </div>
          <button className="icon-button" type="button" disabled={source === null} aria-label="현재 목록 새로고침" title="새로고침" onClick={() => { if (source === "gmail") void gmail.refresh(); else if (source === "tasks") void tasks.refresh(); else if (source === "calendar") void calendar.refresh(); else if (source === "github") void github.refresh(); }}>↻</button>
        </div>
        {source === null ? <div className="info-card"><p>연결된 Connector의 자료가 여기에 표시됩니다.</p><button className="button-primary" type="button" onClick={onOpenSettings}>Connector 설정 열기</button></div> : null}
        {googleConnected && source === "calendar" ? <div className="resource-search-row">
          <label>캘린더<select aria-label="조회할 캘린더" value={parentId ?? ""} disabled={calendarsLoading} onChange={(event) => { setParentId(event.target.value || null); setFocusedItem(null); }}><option value="">캘린더 선택</option>{calendars.map((item) => <option key={item.calendar_id} value={item.calendar_id}>{item.title}</option>)}</select></label>
          {calendarsLoading ? <span role="status">캘린더 확인 중…</span> : null}
          {calendarsError ? <p role="alert">{calendarsError}</p> : null}
          {!calendarsLoading && !calendarsError && !calendars.length ? <p>설정에서 사용할 캘린더를 선택하세요.</p> : null}
        </div> : null}
        {googleConnected && source === "tasks" ? <div className="resource-search-row">
          <label>태스크 목록<select aria-label="조회할 태스크 목록" value={parentId ?? ""} onChange={(event) => { setParentId(event.target.value || null); setFocusedItem(null); setFilter(""); }}>
            <option value="">선택 범위의 첫 목록</option>
            {parentId && !taskLists.some((item) => item.tasklist_id === parentId) ? <option value={parentId}>선택한 목록 (접근 확인 필요)</option> : null}
            {taskLists.map((item) => <option key={item.tasklist_id} value={item.tasklist_id}>{item.title}</option>)}
          </select></label>
          <button className="icon-button" type="button" disabled={taskListsLoading} aria-label="태스크 목록 새로고침" onClick={() => void loadTaskLists()}>↻</button>
          {taskListsNext ? <button type="button" disabled={taskListsLoading} onClick={() => void loadTaskLists(taskListsNext)}>목록 더 불러오기</button> : null}
          {taskListsLoading ? <span role="status">목록 불러오는 중…</span> : null}
          {taskListsError ? <p role="alert">{taskListsError}</p> : null}
          {!taskListsLoading && !taskListsError && taskLists.length === 0 ? <p>사용 가능한 태스크 목록이 없습니다.</p> : null}
        </div> : null}
        {googleConnected && source === "gmail" ? <GmailPanel gmail={gmail} selection={{ selectedResourceIds: selectedContext.resourceIds, focusedResourceId: focusedItem?.resource_id ?? null, onToggleResource: (resourceId) => toggleByResourceId(resourceId, gmail.items), onFocusResource: setFocusedItem }} pagination={{ pageIndexes: pageIndexes(gmail.pageIndex, gmail.totalCount, gmail.items.length), hasNextPage: gmail.pageIndex + 1 < pageCount(gmail.totalCount, gmail.items.length) || (gmail.totalCount === null && gmail.nextPageToken !== null), onGoToPage: (pageIndex) => void gmail.loadPage(pageIndex) }} presentResource={presentResource} /> : null}
        {googleConnected && source === "tasks" ? <TasksPanel tasks={tasks} filter={filter} onFilterChange={setFilter} selection={{ selectedResourceIds: selectedContext.resourceIds, focusedResourceId: focusedItem?.resource_id ?? null, onToggleResource: (resourceId) => toggleByResourceId(resourceId, tasks.items), onFocusResource: setFocusedItem }} visibleItems={visibleTaskItems} sections={taskSections} pageIndexes={pageIndexes(tasks.pageIndex, tasks.totalCount, tasks.items.length)} hasNextPage={tasks.pageIndex + 1 < pageCount(tasks.totalCount, tasks.items.length) || (tasks.totalCount === null && tasks.nextPageToken !== null)} presentResource={presentResource} pastDays={pastScheduledDays} formatCompletedAt={(item) => formatCompletedTaskDate(item.metadata.completed_at ?? null, timezone)} /> : null}
        {googleConnected && source === "calendar" ? <CalendarPanel calendar={calendar} timezone={timezone} filter={filter} onFilterChange={setFilter} onFocusEvent={setFocusedItem} /> : null}
        {githubConnected && source === "github" ? <GitHubPanel github={github} repository={githubRepository} onOpenSettings={onOpenSettings} selectedResourceIds={selectedContext.resourceIds} focusedResourceId={focusedItem?.resource_id ?? null} onToggleResource={(resourceId) => toggleByResourceId(resourceId, github.items)} onFocusResource={setFocusedItem} /> : null}
      </div>
    </aside>
  );
}

export function presentResource(item: ResourceItem): { title: string | null; secondary: string | null; snippet: string | null; time: string | null } {
  const metadata = item.metadata;
  const title = item.title.trim() || null;
  if (item.source === "calendar") return { title, secondary: calendarRange(metadata.start ?? null, metadata.end ?? null), snippet: null, time: null };
  if (item.source === "tasks") return { title, secondary: null, snippet: null, time: formatTaskDate(metadata.scheduled_date ?? null) };
  if (item.source === "github") return { title, secondary: metadata.repository ? `${metadata.repository} #${metadata.issue_number}` : item.subtitle ?? null, snippet: metadata.description ?? null, time: metadata.issue_state === "CLOSED" ? "닫힘" : "열림" };
  const sender = text(item.sender_name) ?? text(metadata.sender_name);
  const email = text(item.sender_email) ?? text(metadata.sender_email);
  return { title, secondary: mailbox(sender, email), snippet: text(item.snippet) ?? text(metadata.snippet), time: sidebarDate(text(item.received_at) ?? text(metadata.received_at)) };
}

function pageCount(total: number | null, loaded: number): number { return Math.ceil((total ?? loaded) / PAGE_SIZE); }
function pageIndexes(current: number, total: number | null, loaded: number): number[] { const count = pageCount(total, loaded); const first = Math.max(0, Math.min(current - 2, count - 5)); return Array.from({ length: Math.min(5, count) }, (_, index) => first + index); }
function formatCount(count: { value: number; exact: boolean } | null): string { return count === null ? "" : `${count.value}${count.exact ? "" : "+"}`; }
function tabLabel(source: ResourceSource): string { return { gmail: "메일", tasks: "태스크", calendar: "캘린더", github: "GitHub Issues" }[source]; }
function tabIcon(source: ResourceSource): string { return { gmail: "✉", tasks: "✓", calendar: "▦", github: "#" }[source]; }
function composerPrompt(source: ResourceSource | null): string { return source === "tasks" ? "선택한 태스크에 대해 질문하거나 업무를 요청하세요..." : source === "calendar" ? "선택한 일정에 대해 질문하거나 업무를 요청하세요..." : source === "github" ? "선택한 GitHub Issue에 대해 질문하거나 업무를 요청하세요..." : source === "gmail" ? "선택한 메일에 대해 질문하거나 업무를 요청하세요..." : "자료를 연결하거나 자연어로 업무를 요청하세요..."; }
function emptyMessage(source: ResourceSource | null): string { return source === "tasks" ? "왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다." : source === "calendar" ? "왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다." : source === "github" ? "왼쪽 목록에서 GitHub Issue를 선택하면 상세 내용을 확인할 수 있습니다." : source === "gmail" ? "왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다." : "Connector를 연결하면 왼쪽에서 자료를 탐색할 수 있습니다."; }
function text(value: unknown): string | null { if (typeof value !== "string" && typeof value !== "number") return null; return String(value).trim() || null; }
function mailbox(name: string | null, email: string | null): string | null { return name && email && name !== email ? `${name} <${email}>` : name ?? (email ? `<${email}>` : null); }
function parsedDate(value: string | null): Date | null { if (!value) return null; const milliseconds = /^\d{12,}$/.test(value) ? Number(value) : Date.parse(value); if (!Number.isFinite(milliseconds)) return null; const date = new Date(milliseconds); return Number.isNaN(date.getTime()) ? null : date; }
function sidebarDate(value: string | null, now = new Date()): string | null { const date = parsedDate(value); if (!date) return null; const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86_400_000); if (days === 0) return date.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true }); if (days === 1) return "어제"; return date.toLocaleDateString("ko-KR", date.getFullYear() === now.getFullYear() ? { month: "long", day: "numeric" } : { year: "numeric", month: "2-digit", day: "2-digit" }); }
function calendarRange(start: string | null, end: string | null): string | null { const startDate = parsedDate(start); const endDate = parsedDate(end); if (/^\d{4}-\d{2}-\d{2}$/.test(start ?? "")) return start ? `${formatTaskDate(start)} · 하루 종일` : null; if (startDate && endDate) return `${startDate.toLocaleString("ko-KR")} - ${endDate.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true })}`; return startDate?.toLocaleString("ko-KR") ?? endDate?.toLocaleString("ko-KR") ?? null; }
function formatTaskDate(value: string | null): string | null { if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null; const [year, month, day] = value.split("-").map(Number); const date = new Date(year, month - 1, day); return `${date.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} (${date.toLocaleDateString("ko-KR", { weekday: "short" })})`; }
function formatCompletedTaskDate(value: string | null, timezone: string): string | null { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString("ko-KR", { timeZone: timezone, month: "long", day: "numeric", weekday: "short" }) : null; }
function localDate(value: Date): string { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`; }
function scheduledDate(item: ResourceItem): string | null { const value = item.metadata.scheduled_date; return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null; }
function pastScheduledDays(item: ResourceItem, now = new Date()): number | null { const scheduled = scheduledDate(item); if (!scheduled || item.metadata.task_status === "completed") return null; const [year, month, day] = scheduled.split("-").map(Number); const scheduledDay = Date.UTC(year, month - 1, day); const [todayYear, todayMonth, todayDay] = localDate(now).split("-").map(Number); const difference = (Date.UTC(todayYear, todayMonth - 1, todayDay) - scheduledDay) / 86_400_000; return difference > 0 ? difference : null; }
function groupTasksByScheduledDate(items: ResourceItem[], now = new Date()): Array<{ key: string; label: string; items: ResourceItem[] }> { const today = localDate(now); const tomorrow = localDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)); return items.reduce<Array<{ key: string; label: string; items: ResourceItem[] }>>((sections, item) => { const date = scheduledDate(item); const status = item.metadata.task_status; const key = !date ? "no-date" : date < today && status !== "completed" ? "past" : date === today ? "today" : date === tomorrow ? "tomorrow" : `date:${date}`; const label = key === "past" ? "지난 날짜" : key === "today" ? "오늘" : key === "tomorrow" ? "내일" : key === "no-date" ? "날짜 없음" : formatTaskDate(date) ?? "날짜 없음"; const previous = sections.at(-1); if (previous?.key === key) previous.items.push(item); else sections.push({ key, label, items: [item] }); return sections; }, []); }
