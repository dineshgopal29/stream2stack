"use client"

import { useEffect, useState, KeyboardEvent } from "react"
import {
  getSettings,
  updateSettings,
  getUsageSummary,
  getUsageCost,
  type UserSettings,
  type UsageSummary,
  type UsageCost,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import { useToast } from "@/components/ui/use-toast"
import {
  Mail,
  Tag,
  ListVideo,
  Save,
  Loader2,
  X,
  Plus,
  Zap,
  BarChart3,
  DollarSign,
  RefreshCw,
} from "lucide-react"

const DEMO_USER_ID = "demo-user-id"

const DEFAULT_SETTINGS: UserSettings = {
  user_id: DEMO_USER_ID,
  email_frequency: "weekly",
  topics: [],
  playlist_urls: [],
  recipient_email: "",
}

// ---------------------------------------------------------------------------
// Plan badge
// ---------------------------------------------------------------------------

const PLAN_META: Record<string, { label: string; color: string }> = {
  free:       { label: "Free",       color: "bg-zinc-600 text-zinc-100" },
  pro:        { label: "Pro",        color: "bg-indigo-600 text-indigo-100" },
  team:       { label: "Team",       color: "bg-violet-600 text-violet-100" },
  enterprise: { label: "Enterprise", color: "bg-amber-600 text-amber-100" },
}

function PlanBadge({ plan }: { plan: string }) {
  const meta = PLAN_META[plan] ?? { label: plan, color: "bg-zinc-600 text-zinc-100" }
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${meta.color}`}>
      {meta.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Quota meter
// ---------------------------------------------------------------------------

function QuotaMeter({
  label,
  used,
  limit,
  pct,
}: {
  label: string
  used: number
  limit: number | null
  pct: number | null
}) {
  const isUnlimited = limit === null
  const barPct = isUnlimited ? 0 : Math.min(pct ?? 0, 100)
  const barColor =
    barPct >= 100 ? "bg-red-500" :
    barPct >= 80  ? "bg-amber-500" :
    "bg-indigo-500"

  function fmt(n: number) {
    return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M`
         : n >= 1_000     ? `${(n / 1_000).toFixed(0)}K`
         : String(n)
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono text-xs">
          {isUnlimited ? (
            <span className="text-muted-foreground">Unlimited</span>
          ) : (
            <>
              <span className={barPct >= 80 ? "text-amber-400 font-semibold" : ""}>
                {fmt(used)}
              </span>
              <span className="text-muted-foreground"> / {fmt(limit!)}</span>
            </>
          )}
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        {!isUnlimited && (
          <div
            className={`h-full rounded-full transition-all ${barColor}`}
            style={{ width: `${barPct}%` }}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skeletons
// ---------------------------------------------------------------------------

function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-64" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-48" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function UsageSkeleton() {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader><Skeleton className="h-5 w-32" /></CardHeader>
        <CardContent className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="space-y-1.5">
              <div className="flex justify-between">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-16" />
              </div>
              <Skeleton className="h-2 w-full rounded-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Usage tab content
// ---------------------------------------------------------------------------

function UsageTab({ userId }: { userId: string }) {
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [cost, setCost] = useState<UsageCost | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const { toast } = useToast()

  async function load(quiet = false) {
    if (!quiet) setLoading(true)
    else setRefreshing(true)
    try {
      const [s, c] = await Promise.all([
        getUsageSummary(userId),
        getUsageCost(userId),
      ])
      setSummary(s)
      setCost(c)
    } catch (err) {
      if (!quiet) {
        toast({
          title: "Could not load usage",
          description: err instanceof Error ? err.message : "Unknown error",
          variant: "destructive",
        })
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { load() }, [userId])

  if (loading) return <UsageSkeleton />

  const plan = summary?.plan ?? "free"
  const upgradeUrl = "https://stream2stack.com/pricing"

  // Format period "2026-04" → "April 2026"
  function fmtPeriod(p: string) {
    const [year, month] = p.split("-")
    return new Date(Number(year), Number(month) - 1).toLocaleDateString("en-US", {
      month: "long", year: "numeric",
    })
  }

  // Operation name prettifier
  function fmtOp(op: string) {
    return op.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  }

  return (
    <div className="space-y-6">
      {/* Plan + period header */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Zap className="h-5 w-5 text-muted-foreground" />
              <CardTitle>Current Plan</CardTitle>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => load(true)}
              disabled={refreshing}
              title="Refresh usage"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            </Button>
          </div>
          <CardDescription>
            {summary ? fmtPeriod(summary.period) : "—"} billing period
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <PlanBadge plan={plan} />
          {plan === "free" && (
            <Button size="sm" asChild>
              <a href={upgradeUrl} target="_blank" rel="noreferrer">
                Upgrade plan
              </a>
            </Button>
          )}
        </CardContent>
      </Card>

      {/* Quota meters */}
      {summary && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5 text-muted-foreground" />
              <CardTitle>Quota Usage</CardTitle>
            </div>
            <CardDescription>
              Resets on the 1st of each month.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <QuotaMeter
              label="Newsletters generated"
              {...summary.quotas.newsletters}
            />
            <QuotaMeter
              label="Videos ingested"
              {...summary.quotas.videos}
            />
            <QuotaMeter
              label="Emails sent"
              {...summary.quotas.emails}
            />
            <QuotaMeter
              label="Web pages scraped"
              {...summary.quotas.scrapes}
            />
            <QuotaMeter
              label="LLM tokens"
              {...summary.quotas.llm_tokens}
            />
          </CardContent>
        </Card>
      )}

      {/* Cost breakdown */}
      {cost && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <DollarSign className="h-5 w-5 text-muted-foreground" />
              <CardTitle>AI Cost Breakdown</CardTitle>
            </div>
            <CardDescription>
              Estimated spend on LLM calls this billing period.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Per-operation table */}
            {Object.keys(cost.by_operation).length > 0 ? (
              <div className="rounded-md border border-border/50 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 bg-muted/40">
                      <th className="text-left px-3 py-2 text-xs text-muted-foreground font-medium uppercase tracking-wide">
                        Operation
                      </th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground font-medium uppercase tracking-wide">
                        Calls
                      </th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground font-medium uppercase tracking-wide">
                        Tokens
                      </th>
                      <th className="text-right px-3 py-2 text-xs text-muted-foreground font-medium uppercase tracking-wide">
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(cost.by_operation).map(([op, data]) => (
                      <tr key={op} className="border-b border-border/30 last:border-0">
                        <td className="px-3 py-2 text-muted-foreground">
                          {fmtOp(op)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          {data.call_count}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          {data.total_tokens.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          ${data.cost_usd.toFixed(4)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No AI usage recorded this period.
              </p>
            )}

            {/* Totals */}
            <div className="flex items-center justify-between rounded-md bg-muted/30 px-4 py-3">
              <span className="text-sm font-medium">Total this period</span>
              <span className="font-mono text-lg font-semibold">
                ${cost.totals.cost_usd.toFixed(4)}
              </span>
            </div>

            <p className="text-xs text-muted-foreground">
              Costs are estimates based on published model pricing. Actual
              charges depend on your API provider billing.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main settings page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const { toast } = useToast()

  const [settings, setSettings] = useState<UserSettings>(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)

  const [topicInput, setTopicInput] = useState("")
  const [playlistInput, setPlaylistInput] = useState("")

  useEffect(() => {
    async function fetchSettings() {
      try {
        const data = await getSettings(DEMO_USER_ID)
        setSettings(data)
      } catch {
        setSettings(DEFAULT_SETTINGS)
      } finally {
        setLoading(false)
      }
    }
    fetchSettings()
  }, [])

  async function handleSave() {
    setIsSaving(true)
    try {
      const updated = await updateSettings(DEMO_USER_ID, settings)
      setSettings(updated)
      toast({ title: "Settings saved", description: "Your preferences have been updated." })
    } catch (err) {
      toast({
        title: "Save failed",
        description: err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsSaving(false)
    }
  }

  function addTopic() {
    const topic = topicInput.trim()
    if (!topic) return
    if (settings.topics.includes(topic)) {
      toast({ title: "Topic already added", description: `"${topic}" is already in your list.`, variant: "destructive" })
      return
    }
    setSettings((prev) => ({ ...prev, topics: [...prev.topics, topic] }))
    setTopicInput("")
  }

  function removeTopic(topic: string) {
    setSettings((prev) => ({ ...prev, topics: prev.topics.filter((t) => t !== topic) }))
  }

  function handleTopicKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addTopic() }
  }

  function addPlaylistUrl() {
    const url = playlistInput.trim()
    if (!url) return
    if (settings.playlist_urls.includes(url)) {
      toast({ title: "Playlist already added", description: "This URL is already in your list.", variant: "destructive" })
      return
    }
    if (!url.includes("youtube.com") && !url.includes("youtu.be")) {
      toast({ title: "Invalid URL", description: "Please enter a valid YouTube playlist URL.", variant: "destructive" })
      return
    }
    setSettings((prev) => ({ ...prev, playlist_urls: [...prev.playlist_urls, url] }))
    setPlaylistInput("")
  }

  function removePlaylistUrl(url: string) {
    setSettings((prev) => ({ ...prev, playlist_urls: prev.playlist_urls.filter((u) => u !== url) }))
  }

  function handlePlaylistKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); addPlaylistUrl() }
  }

  if (loading) {
    return (
      <div className="container max-w-screen-md py-8 space-y-6">
        <div>
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-4 w-64 mt-2" />
        </div>
        <SettingsSkeleton />
      </div>
    )
  }

  return (
    <div className="container max-w-screen-md py-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1">
          Manage your preferences, monitored content, and usage.
        </p>
      </div>

      <Tabs defaultValue="preferences">
        <TabsList className="mb-6">
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="usage">Usage &amp; Billing</TabsTrigger>
        </TabsList>

        {/* ── Preferences tab ── */}
        <TabsContent value="preferences" className="space-y-6 mt-0">

          {/* Email Settings */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Mail className="h-5 w-5 text-muted-foreground" />
                <CardTitle>Email Settings</CardTitle>
              </div>
              <CardDescription>
                Configure where and how often newsletters are delivered.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <Label htmlFor="recipient-email">Recipient Email</Label>
                <Input
                  id="recipient-email"
                  type="email"
                  placeholder="you@example.com"
                  value={settings.recipient_email}
                  onChange={(e) =>
                    setSettings((prev) => ({ ...prev, recipient_email: e.target.value }))
                  }
                />
                <p className="text-xs text-muted-foreground">
                  Newsletters will be delivered to this address.
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="email-frequency">Delivery Frequency</Label>
                <Select
                  value={settings.email_frequency}
                  onValueChange={(value: "daily" | "weekly" | "monthly") =>
                    setSettings((prev) => ({ ...prev, email_frequency: value }))
                  }
                >
                  <SelectTrigger id="email-frequency" className="w-48">
                    <SelectValue placeholder="Select frequency" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="daily">Daily</SelectItem>
                    <SelectItem value="weekly">Weekly</SelectItem>
                    <SelectItem value="monthly">Monthly</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  How often to automatically generate and send newsletters.
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Topics of Interest */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Tag className="h-5 w-5 text-muted-foreground" />
                <CardTitle>Topics of Interest</CardTitle>
              </div>
              <CardDescription>
                Topics help filter and prioritize relevant content in your newsletters.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="e.g. machine learning, web development..."
                  value={topicInput}
                  onChange={(e) => setTopicInput(e.target.value)}
                  onKeyDown={handleTopicKeyDown}
                  className="flex-1"
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={addTopic}
                  disabled={!topicInput.trim()}
                  title="Add topic"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>

              {settings.topics.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {settings.topics.map((topic) => (
                    <Badge key={topic} variant="secondary" className="gap-1 pr-1 cursor-default">
                      {topic}
                      <button
                        onClick={() => removeTopic(topic)}
                        className="ml-1 rounded-full hover:bg-foreground/10 p-0.5 transition-colors"
                        title={`Remove ${topic}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No topics added yet. Press Enter or click + to add one.
                </p>
              )}
            </CardContent>
          </Card>

          {/* Monitored Playlists */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <ListVideo className="h-5 w-5 text-muted-foreground" />
                <CardTitle>Monitored Playlists</CardTitle>
              </div>
              <CardDescription>
                YouTube playlists to automatically monitor and pull new videos from.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex gap-2">
                <Input
                  placeholder="https://youtube.com/playlist?list=PLxxx..."
                  value={playlistInput}
                  onChange={(e) => setPlaylistInput(e.target.value)}
                  onKeyDown={handlePlaylistKeyDown}
                  className="flex-1 font-mono text-xs"
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={addPlaylistUrl}
                  disabled={!playlistInput.trim()}
                  title="Add playlist"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>

              {settings.playlist_urls.length > 0 ? (
                <div className="space-y-2">
                  {settings.playlist_urls.map((url) => (
                    <div
                      key={url}
                      className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/30 px-3 py-2"
                    >
                      <ListVideo className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                      <span className="text-xs font-mono flex-1 truncate">{url}</span>
                      <button
                        onClick={() => removePlaylistUrl(url)}
                        className="rounded p-0.5 hover:bg-foreground/10 transition-colors flex-shrink-0"
                        title="Remove playlist"
                      >
                        <X className="h-3.5 w-3.5 text-muted-foreground" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No playlists monitored. Add a YouTube playlist URL above.
                </p>
              )}
            </CardContent>
          </Card>

          <Separator />

          <div className="flex justify-end">
            <Button onClick={handleSave} disabled={isSaving} className="gap-2">
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isSaving ? "Saving..." : "Save Settings"}
            </Button>
          </div>
        </TabsContent>

        {/* ── Usage & Billing tab ── */}
        <TabsContent value="usage" className="mt-0">
          <UsageTab userId={DEMO_USER_ID} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
