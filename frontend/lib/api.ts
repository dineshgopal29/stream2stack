const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080"

export interface Video {
  id: string
  youtube_id: string
  title: string
  channel_name: string
  published_at: string
  thumbnail_url: string
  transcript?: string
  created_at: string
}

export interface Newsletter {
  id: string
  title: string
  content_md: string
  content_html?: string
  status: "draft" | "sent"
  created_at: string
  sent_at?: string
  video_count?: number
}

export interface UserSettings {
  user_id: string
  email_frequency: "daily" | "weekly" | "monthly"
  topics: string[]
  playlist_urls: string[]
  recipient_email: string
}

export interface IngestResponse {
  videos: Video[]
  message: string
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = "ApiError"
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text()
    let message: string
    try {
      const json = JSON.parse(text)
      message = json.detail || json.message || text || `HTTP ${res.status}`
    } catch {
      message = text || `HTTP ${res.status}`
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

export async function ingestVideos(
  urls: string[],
  playlistUrl?: string
): Promise<IngestResponse> {
  const body: { urls?: string[]; playlist_url?: string } = {}
  if (urls.length > 0) body.urls = urls
  if (playlistUrl) body.playlist_url = playlistUrl

  const res = await fetch(`${API_URL}/videos/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return handleResponse<IngestResponse>(res)
}

export interface GenerateOptions {
  recipientEmail?: string
  autoSelect?: boolean
  description?: string
  sourceUrls?: string[]
  force?: boolean
}

export async function generateNewsletter(
  userId: string,
  options: GenerateOptions = {}
): Promise<Newsletter> {
  const { recipientEmail, autoSelect = true, description, sourceUrls, force } = options
  const body: Record<string, unknown> = {
    user_id: userId,
    auto_select: autoSelect,
  }
  if (recipientEmail) body.recipient_email = recipientEmail
  if (description?.trim()) body.description = description.trim()
  if (sourceUrls && sourceUrls.length > 0) body.source_urls = sourceUrls
  if (force) body.force = true

  const res = await fetch(`${API_URL}/newsletters/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  return handleResponse<Newsletter>(res)
}

export async function getNewsletters(userId: string): Promise<Newsletter[]> {
  const res = await fetch(`${API_URL}/newsletters?user_id=${userId}`)
  return handleResponse<Newsletter[]>(res)
}

export async function getNewsletter(id: string): Promise<Newsletter> {
  const res = await fetch(`${API_URL}/newsletters/${id}`)
  return handleResponse<Newsletter>(res)
}

export async function deleteNewsletter(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/newsletters/${id}`, { method: "DELETE" })
  if (!res.ok && res.status !== 204) {
    const text = await res.text()
    try {
      const json = JSON.parse(text)
      throw new Error(json.detail || json.message || text || `HTTP ${res.status}`)
    } catch (e) {
      if (e instanceof SyntaxError) throw new Error(text || `HTTP ${res.status}`)
      throw e
    }
  }
}

export async function sendNewsletter(
  id: string,
  recipientEmail: string
): Promise<void> {
  const res = await fetch(`${API_URL}/newsletters/${id}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipient_email: recipientEmail }),
  })
  return handleResponse<void>(res)
}

export async function getVideos(userId?: string): Promise<Video[]> {
  const url = userId
    ? `${API_URL}/videos?user_id=${userId}`
    : `${API_URL}/videos`
  const res = await fetch(url)
  return handleResponse<Video[]>(res)
}

// ---------------------------------------------------------------------------
// Usage & Metering
// ---------------------------------------------------------------------------

export interface QuotaResource {
  used: number
  limit: number | null   // null = unlimited
  pct: number | null
}

export interface UsageSummary {
  period: string          // "YYYY-MM"
  plan: string            // "free" | "pro" | "team" | "enterprise"
  quotas: {
    newsletters: QuotaResource
    videos: QuotaResource
    emails: QuotaResource
    scrapes: QuotaResource
    llm_tokens: QuotaResource
  }
  cost_usd: {
    accrued: number
  }
}

export interface OperationCost {
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  call_count: number
}

export interface UsageCost {
  period: string
  by_operation: Record<string, OperationCost>
  totals: {
    cost_usd: number
    total_tokens: number
    call_count: number
  }
}

export async function getUsageSummary(userId: string): Promise<UsageSummary> {
  const res = await fetch(`${API_URL}/usage/summary?user_id=${userId}`)
  return handleResponse<UsageSummary>(res)
}

export async function getUsageCost(
  userId: string,
  period?: string
): Promise<UsageCost> {
  const params = new URLSearchParams({ user_id: userId })
  if (period) params.set("period", period)
  const res = await fetch(`${API_URL}/usage/cost?${params}`)
  return handleResponse<UsageCost>(res)
}

export async function getSettings(userId: string): Promise<UserSettings> {
  const res = await fetch(`${API_URL}/settings/${userId}`)
  return handleResponse<UserSettings>(res)
}

export async function updateSettings(
  userId: string,
  settings: Partial<UserSettings>
): Promise<UserSettings> {
  const res = await fetch(`${API_URL}/settings/${userId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  })
  return handleResponse<UserSettings>(res)
}

// ---------------------------------------------------------------------------
// Wiki Knowledge Base
// ---------------------------------------------------------------------------

export interface WikiPage {
  title: string
  slug: string
  type: string           // "concept" | "tool" | "pattern"
  content: string
  source_ids: string[]
  source_hash: string
  compiled_at: string
  schema_version: number
  backlinks: string[]
}

export interface WikiStats {
  total: number
  by_type: Record<string, number>
  wiki_root: string
}

export interface WikiCompileResult {
  compiled: number
  skipped: number
  errors: number
  pages_written: number
  total_terms: number | null
  message: string | null
}

export async function getWikiPages(type?: string): Promise<WikiPage[]> {
  const url = type
    ? `${API_URL}/wiki/pages?type=${encodeURIComponent(type)}`
    : `${API_URL}/wiki/pages`
  const res = await fetch(url)
  return handleResponse<WikiPage[]>(res)
}

export async function getWikiPage(type: string, slug: string): Promise<WikiPage> {
  const res = await fetch(`${API_URL}/wiki/pages/${encodeURIComponent(type)}/${encodeURIComponent(slug)}`)
  return handleResponse<WikiPage>(res)
}

export async function getWikiStats(): Promise<WikiStats> {
  const res = await fetch(`${API_URL}/wiki/stats`)
  return handleResponse<WikiStats>(res)
}

export async function compileWiki(force = false): Promise<WikiCompileResult> {
  const res = await fetch(`${API_URL}/wiki/compile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo-user-id", force }),
  })
  return handleResponse<WikiCompileResult>(res)
}
