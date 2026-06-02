// Typed client for the debug-UI JSON API. Same-origin in production.

export interface ThreadBrief {
  thread_id: string;
  subject: string;
  working_group: string;
  date_range: string;
  status: string;
  consensus_state: string | null;
  summary_brief: string;
  archive_url: string | null;
}

export interface KeyPosition {
  position: string;
  holder: string;
  context: string;
}

export interface ThreadDraftRef {
  draft_name: string;
  versions_referenced: string[] | null;
  datatracker_url: string | null;
}

export interface ThreadDetail {
  thread_id: string;
  subject: string;
  working_group: string;
  status: string;
  consensus_state: string | null;
  summary: string | null;
  key_positions: KeyPosition[];
  participants: string[];
  archive_url: string | null;
  drafts: ThreadDraftRef[];
}

export interface Draft {
  draft_name: string;
  title: string | null;
  status: string | null;
  current_version: string | null;
  thread_count: number;
  datatracker_url: string | null;
}

export interface Cost {
  total_usd: number;
  ceiling_usd: number;
  by_stage: Record<string, number>;
}

export interface Batch {
  id: number;
  batch_id: string | null;
  stage: string;
  status: string;
  item_count: number;
  submitted_at: string | null;
  retrieved_at: string | null;
}

async function getJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return (await resp.json()) as T;
}

export const api = {
  threads: (params: Record<string, string> = {}) =>
    getJSON<ThreadBrief[]>(`/api/threads?${new URLSearchParams(params)}`),
  thread: (id: string) => getJSON<ThreadDetail>(`/api/threads/${encodeURIComponent(id)}`),
  drafts: () => getJSON<Draft[]>("/api/drafts"),
  cost: () => getJSON<Cost>("/api/cost"),
  batches: () => getJSON<Batch[]>("/api/batches"),
  retrigger: (stage: string) => fetch(`/api/retrigger/${stage}`, { method: "POST" }),
};
