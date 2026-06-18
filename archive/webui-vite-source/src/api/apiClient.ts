const BASE_KEY = 'seam-webui-api-url';
const TOKEN_KEY = 'seam-webui-api-token';
const DEFAULT_BASE_URL = 'http://127.0.0.1:8765';

export interface HealthResponse {
  status: string;
}

export interface StatsResponse {
  total_records: number;
  [key: string]: unknown;
}

export interface CompilePayload {
  text: string;
  persist?: boolean;
  source_ref?: string;
  ns?: string;
  scope?: string;
}

export interface CompileResponse {
  records: unknown[];
  persist?: object;
}

export interface SearchResponse {
  candidates: SearchCandidate[];
}

export interface SearchCandidate {
  record: {
    id: string;
    text?: string;
    kind?: string;
    [key: string]: unknown;
  };
  score: number;
  [key: string]: unknown;
}

export interface ContextPayload {
  query: string;
  budget?: number;
  scope?: string | null;
  lens?: string;
  pack_budget?: number;
  mode?: string;
}

export interface ContextResponse {
  query: string;
  candidates: SearchCandidate[];
  pack: object;
}

export interface PersistPayload {
  records: unknown[];
}

export interface LosslessCompressPayload {
  text: string;
  codec?: string;
  transform?: string;
  tokenizer?: string;
  min_token_savings?: number;
  include_machine_text?: boolean;
}

export interface LosslessCompressResponse {
  passed: boolean;
  roundtrip_match: boolean;
  meets_target: boolean;
  artifact: {
    original_tokens: number;
    machine_tokens: number;
    token_savings_ratio: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

function getStoredValue(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function getSessionValue(key: string): string | null {
  try {
    globalThis.localStorage?.removeItem(key);
    return globalThis.sessionStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function getClient() {
  const baseUrl = (getStoredValue(BASE_KEY) || DEFAULT_BASE_URL).replace(/\/$/, '');
  const token = getSessionValue(TOKEN_KEY) || '';
  return { baseUrl, token };
}

async function _fetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { baseUrl, token } = getClient();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (init.headers) {
    const extra = init.headers as Record<string, string>;
    Object.assign(headers, extra);
  }
  const url = `${baseUrl}${path}`;
  try {
    const res = await fetch(url, { ...init, headers });
    return res;
  } catch (err) {
    if (err instanceof TypeError) {
      const networkErr = new Error('Disconnected') as Error & { code?: string };
      networkErr.code = 'DISCONNECTED';
      throw networkErr;
    }
    throw err;
  }
}

async function assertOk(res: Response, label: string): Promise<void> {
  if (res.status === 401) {
    const err = new Error('Unauthorized') as Error & { code?: string };
    err.code = 'UNAUTHORIZED';
    throw err;
  }
  if (!res.ok) throw new Error(`${label} error ${res.status}: ${await res.text()}`);
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await _fetch('/health');
  await assertOk(res, 'Health');
  return (await res.json()) as HealthResponse;
}

export async function fetchStats(): Promise<StatsResponse> {
  const res = await _fetch('/stats');
  await assertOk(res, 'Stats');
  return (await res.json()) as StatsResponse;
}

export async function fetchCompile(payload: CompilePayload): Promise<CompileResponse> {
  const res = await _fetch('/compile', { method: 'POST', body: JSON.stringify(payload) });
  await assertOk(res, 'Compile');
  return (await res.json()) as CompileResponse;
}

export async function fetchSearch(query: string, budget = 5, scope?: string | null, lens = 'general'): Promise<SearchResponse> {
  const params = new URLSearchParams({ query, budget: String(budget), lens });
  if (scope) params.set('scope', scope);
  const res = await _fetch(`/search?${params.toString()}`);
  await assertOk(res, 'Search');
  return (await res.json()) as SearchResponse;
}

export async function fetchContext(payload: ContextPayload): Promise<ContextResponse> {
  const res = await _fetch('/context', { method: 'POST', body: JSON.stringify(payload) });
  await assertOk(res, 'Context');
  return (await res.json()) as ContextResponse;
}

export async function fetchPersist(payload: PersistPayload): Promise<object> {
  const res = await _fetch('/persist', { method: 'POST', body: JSON.stringify(payload) });
  await assertOk(res, 'Persist');
  return (await res.json()) as object;
}

export async function fetchLosslessCompress(payload: LosslessCompressPayload): Promise<LosslessCompressResponse> {
  const res = await _fetch('/lossless-compress', { method: 'POST', body: JSON.stringify(payload) });
  await assertOk(res, 'Compress');
  return (await res.json()) as LosslessCompressResponse;
}
