import { requestJson } from "../../../api/client";
import type { SettingsView } from "./get_settings";

export type SettingsPatch = Partial<
  Omit<SettingsView, "schema_version" | "default_github_repository" | "selected_github_repositories" | "google_resource_account_id" | "preferred_llm_mode">
> & {
  default_github_repository?: string | null;
  selected_github_repositories?: string[];
  preferred_llm_mode?: "LOCAL_GPU" | "API_LLM";
};

export function updateSettings(commandId: string, settingsPatch: SettingsPatch): Promise<SettingsView> {
  return requestJson("/api/v1/settings", {
    method: "PUT",
    body: { schema_version: 1, command_id: commandId, settings_patch: { schema_version: 1, ...settingsPatch } },
  });
}
