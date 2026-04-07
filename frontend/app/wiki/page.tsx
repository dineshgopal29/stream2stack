"use client"

import { useEffect, useState, useMemo } from "react"
import Link from "next/link"
import { getWikiPages, getWikiStats, compileWiki, type WikiPage, type WikiStats } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/use-toast"
import { RefreshCw, BookOpen, Wrench, Layers } from "lucide-react"

const PAGE_TYPES = ["concept", "tool", "pattern"] as const
type PageType = typeof PAGE_TYPES[number]

const TYPE_LABELS: Record<PageType, string> = {
  concept: "Concepts",
  tool: "Tools",
  pattern: "Patterns",
}

const TYPE_ICONS: Record<PageType, React.ReactNode> = {
  concept: <BookOpen className="h-4 w-4" />,
  tool: <Wrench className="h-4 w-4" />,
  pattern: <Layers className="h-4 w-4" />,
}

export default function WikiBrowsePage() {
  const [pages, setPages] = useState<WikiPage[]>([])
  const [stats, setStats] = useState<WikiStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [compiling, setCompiling] = useState(false)
  const [search, setSearch] = useState("")
  const { toast } = useToast()

  useEffect(() => {
    Promise.all([getWikiPages(), getWikiStats()])
      .then(([p, s]) => { setPages(p); setStats(s) })
      .catch(() => toast({ title: "Failed to load wiki", variant: "destructive" }))
      .finally(() => setLoading(false))
  }, [])

  const grouped = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = q ? pages.filter(p => p.title.toLowerCase().includes(q)) : pages
    return Object.fromEntries(
      PAGE_TYPES.map(t => [t, filtered.filter(p => p.type === t)])
    ) as Record<PageType, WikiPage[]>
  }, [pages, search])

  async function handleCompile() {
    setCompiling(true)
    try {
      const result = await compileWiki(false)
      toast({
        title: "Wiki compiled",
        description: `${result.compiled} compiled · ${result.skipped} skipped · ${result.errors} errors`,
      })
      const [p, s] = await Promise.all([getWikiPages(), getWikiStats()])
      setPages(p)
      setStats(s)
    } catch {
      toast({ title: "Compile failed", variant: "destructive" })
    } finally {
      setCompiling(false)
    }
  }

  return (
    <div className="container mx-auto max-w-4xl py-8 px-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">Wiki Knowledge Base</h1>
          {stats && (
            <p className="text-muted-foreground mt-1 text-sm">
              {stats.by_type.concept ?? 0} concepts ·{" "}
              {stats.by_type.tool ?? 0} tools ·{" "}
              {stats.by_type.pattern ?? 0} patterns
            </p>
          )}
        </div>
        <Button onClick={handleCompile} disabled={compiling} variant="outline" className="gap-2">
          <RefreshCw className={`h-4 w-4 ${compiling ? "animate-spin" : ""}`} />
          {compiling ? "Compiling…" : "Recompile Wiki"}
        </Button>
      </div>

      {/* Search */}
      <Input
        placeholder="Search pages…"
        value={search}
        onChange={e => setSearch(e.target.value)}
        className="mb-6"
      />

      {/* Tabs */}
      <Tabs defaultValue="concept">
        <TabsList className="mb-4">
          {PAGE_TYPES.map(t => (
            <TabsTrigger key={t} value={t} className="gap-2">
              {TYPE_ICONS[t]}
              {TYPE_LABELS[t]}
              <Badge variant="secondary" className="ml-1">
                {loading ? "—" : grouped[t].length}
              </Badge>
            </TabsTrigger>
          ))}
        </TabsList>

        {PAGE_TYPES.map(t => (
          <TabsContent key={t} value={t}>
            {loading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-16 w-full rounded-lg" />
                ))}
              </div>
            ) : grouped[t].length === 0 ? (
              <div className="text-center py-16 text-muted-foreground">
                {search
                  ? `No ${TYPE_LABELS[t].toLowerCase()} match "${search}"`
                  : `No ${TYPE_LABELS[t].toLowerCase()} compiled yet. Click Recompile Wiki to generate pages.`}
              </div>
            ) : (
              <div className="space-y-2">
                {grouped[t].map(page => (
                  <Link key={page.slug} href={`/wiki/${page.type}s/${page.slug}`}>
                    <Card className="hover:bg-accent/50 transition-colors cursor-pointer">
                      <CardHeader className="py-3 px-4">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-base font-medium">{page.title}</CardTitle>
                          <span className="text-xs text-muted-foreground">
                            {page.source_ids.length} source{page.source_ids.length !== 1 ? "s" : ""}
                          </span>
                        </div>
                      </CardHeader>
                    </Card>
                  </Link>
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
