import { requestJson } from "../../../api/client";

export type RepositoryItem = { repository: string; repository_id: number; private: boolean };
export type RepositoryPage = {
  schema_version: 1;
  account_id: string;
  items: RepositoryItem[];
  next_cursor: string | null;
};

export function listRepositories(cursor?: string): Promise<RepositoryPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return requestJson(`/api/v1/connections/github/repositories${query}`);
}
