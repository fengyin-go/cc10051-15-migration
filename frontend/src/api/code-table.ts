import { request } from './client'

/** 码表版本化接口封装：与后端 /api/code-tables 对齐。 */

export type RejectedLine = {
  index: number
  raw: string
  reason: string
}

export type CodeEntry = {
  code: string
  value: string
}

export type CodeTableDataset = {
  id: number
  数据集编码: string
  数据集名称: string
  entry_format: string
  status: string
  current_version: string | null
  entry_count: number
  rejected_count: number
  migration_report: {
    source_format: string
    converted: number
    rejected: RejectedLine[]
  }
  created_at: string
}

export type CodeTableVersion = {
  id: number
  dataset_code: string
  dataset_name: string
  version_no: string
  entry_format: string
  source_format: string
  entry_count: number
  legacy_compatible: boolean
  status: string
  entries: CodeEntry[]
  migration_report: {
    source_format: string
    converted: number
    rejected: RejectedLine[]
  }
  published_at: string
}

export type CodeTableClaim = {
  id: number
  batch_no: string
  dataset_code: string
  version_no: string
  entry_format: string
  runtime_mode: string
  entry_count: number
  claimed_at: string
}

export type ClaimResult = {
  ok: boolean
  blocked?: boolean
  reason?: string
  message: string
  batch_no?: string
  dataset_code?: string
  version_no?: string
  blocked_version?: string
  entry_format?: string
  runtime_mode?: string
  entries?: CodeEntry[]
  payload?: string
  reused?: boolean
  incompatible_entries?: CodeEntry[]
}

async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return (await response.json()) as T
}

async function get<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error('码表接口读取失败')
  return (await response.json()) as T
}

export const codeTableApi = {
  runtime: () => get<{ ok: boolean; runtime_mode: string }>('/api/code-tables/runtime'),
  switchRuntime: (mode: string, reason: string) =>
    post<{ ok: boolean; message: string; runtime_mode: string }>('/api/code-tables/runtime/switch', {
      mode,
      reason,
    }),
  datasets: () => get<{ ok: boolean; items: CodeTableDataset[] }>('/api/code-tables/datasets'),
  register: (payload: {
    dataset_code: string
    dataset_name: string
    entry_format: string
    entry_text: string
  }) => post<{ ok: boolean; message: string; dataset?: CodeTableDataset }>('/api/code-tables/register', payload),
  publish: (dataset_code: string) =>
    post<{ ok: boolean; blocked?: boolean; message: string }>('/api/code-tables/publish', { dataset_code }),
  rollback: (dataset_code: string, target_version: string, reason: string) =>
    post<{ ok: boolean; message: string; current_version?: string }>('/api/code-tables/rollback', {
      dataset_code,
      target_version,
      reason,
    }),
  versions: (dataset_code: string) =>
    get<{ ok: boolean; items: CodeTableVersion[] }>(`/api/code-tables/versions/${encodeURIComponent(dataset_code)}`),
  rejections: (dataset_code: string, version_no: string) =>
    get<{
      ok: boolean
      converted: number
      rejected: RejectedLine[]
    }>(`/api/code-tables/versions/${encodeURIComponent(dataset_code)}/${encodeURIComponent(version_no)}/rejections`),
  claim: (dataset_code: string, batch_no: string) =>
    post<ClaimResult>('/api/code-tables/claim', { dataset_code, batch_no }),
  normalize: (batch_no: string, raw_value: string) =>
    post<{
      ok: boolean
      blocked?: boolean
      message?: string
      raw?: string
      normalized?: string
      mapped?: boolean
      version_no?: string
    }>('/api/code-tables/normalize', { batch_no, raw_value }),
  recompute: (batch_no: string) =>
    get<{
      ok: boolean
      message?: string
      version_no?: string
      all_consistent?: boolean
      reruns?: { raw: string; original: string; recomputed: string; consistent: boolean }[]
    }>(`/api/code-tables/recompute/${encodeURIComponent(batch_no)}`),
  claims: () => get<{ ok: boolean; items: CodeTableClaim[] }>('/api/code-tables/claims'),
}
