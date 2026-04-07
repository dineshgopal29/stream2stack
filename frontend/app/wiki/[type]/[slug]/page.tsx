"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { getWikiPage, type WikiPage } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/use-toast"
import { ArrowLeft, Clock, Film } from "lucide-react"

const TYPE_COLORS: Record<string, string> = {
  concept: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  tool: "bg-green-500/10 text-green-500 border-green-500/20",
  pattern: "bg-purple-500/10 text-purple-500 border-purple-500/20",
}

// The [type] URL segment is plural (concepts/tools/patterns) but the API expects singular.
function normaliseType(raw: string): string {
  return raw.endsWith("s") ? raw.slice(0, -1) : raw
}

export default function WikiDetailPage() {
  const params = useParams<{ type: string; slug: string }>()
  const router = useRouter()
  const { toast } = useToast()
  const [page, setPage] = useState<WikiPage | null>(null)
  const [loading, setLoading] = useState(true)

  const pageType = normaliseType(params.type)

  useEffect(() => {
    getWikiPage(pageType, params.slug)
      .then(setPage)
      .catch(() => {
        toast({ title: "Page not found", variant: "destructive" })
        router.push("/wiki")
      })
      .finally(() => setLoading(false))
  }, [pageType, params.slug])

  if (loading) {
    return (
      <div className="container mx-auto max-w-3xl py-8 px-4 space-y-4">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!page) return null

  const compiledDate = page.compiled_at
    ? new Date(page.compiled_at).toLocaleDateString()
    : "Unknown"

  return (
    <div className="container mx-auto max-w-3xl py-8 px-4">
      {/* Back */}
      <Link href="/wiki">
        <Button variant="ghost" size="sm" className="gap-2 mb-6 -ml-2">
          <ArrowLeft className="h-4 w-4" />
          Wiki
        </Button>
      </Link>

      {/* Header */}
      <div className="mb-6">
        <Badge
          variant="outline"
          className={`mb-3 capitalize ${TYPE_COLORS[page.type] ?? ""}`}
        >
          {page.type}
        </Badge>
        <h1 className="text-4xl font-bold mb-3">{page.title}</h1>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <Film className="h-3.5 w-3.5" />
            {page.source_ids.length} source video{page.source_ids.length !== 1 ? "s" : ""}
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            Compiled {compiledDate}
          </span>
        </div>
      </div>

      {/* Content */}
      <article className="prose prose-invert prose-sm max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith("/wiki/")) {
                return (
                  <Link href={href} className="text-primary hover:underline">
                    {children}
                  </Link>
                )
              }
              return (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              )
            },
          }}
        >
          {page.content}
        </ReactMarkdown>
      </article>

      {/* Backlinks */}
      {page.backlinks.length > 0 && (
        <div className="mt-8 pt-6 border-t border-border">
          <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
            Related Concepts
          </h3>
          <div className="flex flex-wrap gap-2">
            {page.backlinks.map(link => {
              const slug = link.toLowerCase().replace(/\s+/g, "-").replace(/[^\w-]/g, "")
              return (
                <Link key={link} href={`/wiki/concepts/${slug}`}>
                  <Badge variant="secondary" className="hover:bg-accent cursor-pointer">
                    {link}
                  </Badge>
                </Link>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
