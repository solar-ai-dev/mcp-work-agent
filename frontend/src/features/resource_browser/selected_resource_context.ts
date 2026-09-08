import type { ResourceItem } from "../../api/contract";

export type SelectedResourceContext = {
  items: ResourceItem[];
  resourceIds: string[];
  selectionHandles: string[];
  labels: string[];
};

export function isSameResourceIdentity(left: ResourceItem, right: ResourceItem): boolean {
  return left.source === right.source
    && left.resource_type === right.resource_type
    && left.resource_id === right.resource_id
    && (left.parent_id ?? null) === (right.parent_id ?? null);
}

export function buildSelectedResourceContext(
  items: ResourceItem[],
  labelFor: (item: ResourceItem) => string = (item) => item.title,
): SelectedResourceContext {
  const selectedByIdentity = new Map<string, ResourceItem>();
  for (const item of items) {
    const identity = [item.source, item.resource_type, item.parent_id ?? "", item.resource_id]
      .join("\u0000");
    const handle = item.selection_handle.trim();
    if (!handle || (!selectedByIdentity.has(identity) && selectedByIdentity.size >= 20)) continue;
    selectedByIdentity.set(identity, { ...item, selection_handle: handle });
  }
  const selected: ResourceItem[] = [];
  const seenHandles = new Set<string>();
  for (const item of selectedByIdentity.values()) {
    if (seenHandles.has(item.selection_handle)) continue;
    seenHandles.add(item.selection_handle);
    selected.push(item);
  }
  return {
    items: selected,
    resourceIds: selected.map((item) => item.resource_id),
    selectionHandles: selected.map((item) => item.selection_handle),
    labels: selected.map(labelFor).filter((label) => label.trim().length > 0),
  };
}
