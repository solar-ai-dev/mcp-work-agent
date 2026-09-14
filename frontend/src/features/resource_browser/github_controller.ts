import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import type { ResourceItem } from "../../api/contract";
import { listResources } from "./api/list_resources";

export type GitHubIssueState = "OPEN" | "CLOSED" | "ALL";

export function useGitHubIssues({
  accountId,
  repository,
  active,
}: {
  accountId: string | null | undefined;
  repository: string | null | undefined;
  active: boolean;
}) {
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [issueState, setIssueStateValue] = useState<GitHubIssueState>("OPEN");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const load = useCallback(async (): Promise<void> => {
    if (!accountId || !repository) return;
    const generation = ++generationRef.current;
    setLoading(true);
    setError(null);
    try {
      const response = await listResources({ source: "github", repository, issueState });
      if (generation !== generationRef.current) return;
      setItems(response.items);
      setLoaded(true);
    } catch (loadError) {
      if (generation !== generationRef.current) return;
      setError(loadError instanceof ApiClientError ? loadError.message : "GitHub Issues를 불러오지 못했습니다.");
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [accountId, issueState, repository]);

  const reset = useCallback((): void => {
    generationRef.current += 1;
    setItems([]);
    setLoaded(false);
    setLoading(false);
    setError(null);
  }, []);

  useEffect(() => {
    reset();
  }, [accountId, repository, reset]);

  useEffect(() => {
    if (active && repository && !loaded && !loading && error === null) void load();
  }, [active, error, load, loaded, loading, repository]);

  function setIssueState(next: GitHubIssueState): void {
    generationRef.current += 1;
    setIssueStateValue(next);
    setItems([]);
    setLoaded(false);
    setLoading(false);
    setError(null);
  }

  return { items, issueState, setIssueState, loaded, loading, error, refresh: load, reset };
}

export type GitHubIssuesController = ReturnType<typeof useGitHubIssues>;
