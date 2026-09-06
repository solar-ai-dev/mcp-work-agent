import { useMemo, useState } from "react";
import type { ResourceItem } from "../../api/contract";
import type { GitHubIssuesController } from "./github_controller";

type Props = {
  github: GitHubIssuesController;
  repository: string | null | undefined;
  onOpenSettings?: () => void;
  selectedResourceIds: string[];
  focusedResourceId: string | null;
  onToggleResource: (resourceId: string) => void;
  onFocusResource: (item: ResourceItem) => void;
};

export function GitHubPanel({ github, repository, onOpenSettings, selectedResourceIds, focusedResourceId, onToggleResource, onFocusResource }: Props): JSX.Element {
  const [filter, setFilter] = useState("");
  const visibleItems = useMemo(() => {
    const query = filter.trim().toLocaleLowerCase("ko-KR");
    if (!query) return github.items;
    return github.items.filter((item) => [item.title, item.metadata.description, item.metadata.labels?.join(" "), item.metadata.assignees?.join(" ")]
      .some((value) => value?.toLocaleLowerCase("ko-KR").includes(query)));
  }, [filter, github.items]);

  if (!repository) {
    return (
      <div className="info-card">
        <p>탐색할 GitHub Repository를 설정해 주세요.</p>
        <button className="button-primary" type="button" onClick={onOpenSettings}>설정 열기</button>
      </div>
    );
  }

  return (
    <>
      <div className="resource-search-row">
        <label className="resource-search">
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="10.5" cy="10.5" r="5.75" /><path d="m15 15 4.25 4.25" /></svg>
          <input aria-label="GitHub Issue 검색" placeholder="Issue 검색" value={filter} onChange={(event) => setFilter(event.target.value)} />
        </label>
        <select aria-label="GitHub Issue 상태" value={github.issueState} onChange={(event) => github.setIssueState(event.target.value as "OPEN" | "CLOSED" | "ALL")}>
          <option value="OPEN">열림</option>
          <option value="CLOSED">닫힘</option>
          <option value="ALL">전체</option>
        </select>
      </div>
      <p className="muted">{repository}</p>
      {github.loading ? <div className="resource-load-status" aria-live="polite"><p className="muted">GitHub Issues를 불러오는 중입니다.</p></div> : null}
      {github.error ? <p className="status-bad" role="alert">{github.error}</p> : null}
      {!github.loading && !github.error && github.loaded && visibleItems.length === 0 ? <p className="muted">표시할 Issue가 없습니다.</p> : null}
      <div className="resource-content">
        <ul className="resource-list" aria-label="GitHub Issues">
          {visibleItems.map((item) => {
            const selected = selectedResourceIds.includes(item.resource_id);
            const focused = focusedResourceId === item.resource_id;
            return (
              <li key={item.resource_id} className={`resource-item ${selected ? "selected" : ""} ${focused ? "focused" : ""}`}>
                <label className="resource-select-control" title="선택 요청에 포함">
                  <input type="checkbox" aria-label={`${item.title || "제목 없음"} 선택`} checked={selected} onChange={() => onToggleResource(item.resource_id)} />
                </label>
                <button className="resource-summary" type="button" aria-pressed={focused} onClick={() => onFocusResource(item)}>
                  <span className="row-mail-meta"><span className="row-sender">#{item.metadata.issue_number}</span><span className="row-meta">{item.metadata.issue_state === "CLOSED" ? "닫힘" : "열림"}</span></span>
                  <strong className="row-title">{item.title || "제목 없음"}</strong>
                  {item.metadata.description ? <span className="row-snippet">{item.metadata.description}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
