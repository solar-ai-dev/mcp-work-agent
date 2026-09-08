import { requestJson } from "../../../api/client";

export type RuntimeMode = "AUTO" | "LOCAL_GPU" | "API_LLM";
export type SelectableRuntimeMode = Exclude<RuntimeMode, "AUTO">;

export function updateRuntimeMode(commandId: string, requestedMode: SelectableRuntimeMode): Promise<{ schema_version: 1; requested_mode: SelectableRuntimeMode; actual_runtime: "LOCAL_GPU" | "API_LLM" | null; fallback_reason: string | null }> {
  return requestJson("/api/v1/runtime/mode", { method: "POST", body: { schema_version: 1, command_id: commandId, requested_mode: requestedMode } });
}
