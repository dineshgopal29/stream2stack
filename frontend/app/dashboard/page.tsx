"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { getNewsletters, getVideos, type Newsletter, type Video } from "@/lib/api"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  FileText,
  Video as VideoIcon,
  TrendingUp,
  Plus,
  ArrowRight,
  Mail,
} from "lucide-react"

const DEMO_USER_ID = "demo-user-id"

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-4 w-4 rounded-full" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-16 mb-1" />
        <Skeleton className="h-3 w-32" />
      </CardContent>
    </Card>
  )
}

function NewsletterRowSkeleton() {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border/50 last:border-0">
      <div className="space-y-1.5">
        <Skeleton className="h-4 w-64" />
        <Skeleton className="h-3 w-32" />
      </div>
      <Skeleton className="h-6 w-16 rounded-full" />
    </div>
  )
}

export default function DashboardPage() {
  const [newsletters, setNewsletters] = useState<Newsletter[]>([])
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchData() {
      try {
        const [newsletterData, videoData] = await Promise.all([
          getNewsletters(DEMO_USER_ID),
          getVideos(DEMO_USER_ID),
        ])
        setNewsletters(newsletterData)
        setVideos(videoData)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load data")
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  // Compute stats
  const totalNewsletters = newsletters.length
  const totalVideos = videos.length

  const oneWeekAgo = new Date()
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 7)
  const videosThisWeek = videos.filter(
    (v) => new Date(v.created_at) > oneWeekAgo
  ).length

  const recentNewsletters = newsletters
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 5)

  return (
    <div className="container max-w-screen-xl py-8 space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground mt-1">
            Overview of your Stream2Stack activity
          </p>
        </div>
        <Link href="/input">
          <Button className="gap-2">
            <Plus className="h-4 w-4" />
            Generate Newsletter
          </Button>
        </Link>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {loading ? (
          <>
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
          </>
        ) : (
          <>
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Total Videos
                </CardTitle>
                <VideoIcon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{totalVideos}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  Videos ingested into your library
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Newsletters Generated
                </CardTitle>
                <FileText className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{totalNewsletters}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  Total newsletters created
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Videos This Week
                </CardTitle>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{videosThisWeek}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  Added in the last 7 days
                </p>
              </CardContent>
            </Card>
          </>
        )}
      </div>

      {/* Recent Newsletters */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Recent Newsletters</CardTitle>
            <CardDescription>Your last 5 generated newsletters</CardDescription>
          </div>
          <Link href="/history">
            <Button variant="ghost" size="sm" className="gap-1 text-xs">
              View all
              <ArrowRight className="h-3 w-3" />
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div>
              {Array.from({ length: 3 }).map((_, i) => (
                <NewsletterRowSkeleton key={i} />
              ))}
            </div>
          ) : error ? (
            <div className="py-8 text-center text-muted-foreground">
              <p className="text-sm">{error}</p>
              <p className="text-xs mt-1">Make sure the backend is running.</p>
            </div>
          ) : recentNewsletters.length === 0 ? (
            <div className="py-12 text-center">
              <Mail className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <p className="text-muted-foreground font-medium">
                No newsletters yet
              </p>
              <p className="text-sm text-muted-foreground mt-1 mb-4">
                Ingest some videos and generate your first newsletter.
              </p>
              <Link href="/input">
                <Button size="sm">
                  <Plus className="h-4 w-4 mr-1" />
                  Get Started
                </Button>
              </Link>
            </div>
          ) : (
            <div>
              {recentNewsletters.map((newsletter) => (
                <Link
                  key={newsletter.id}
                  href={`/newsletter/${newsletter.id}`}
                  className="flex items-center justify-between py-3 border-b border-border/50 last:border-0 hover:bg-accent/30 -mx-6 px-6 transition-colors rounded-sm"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm truncate pr-4">
                      {newsletter.title}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {new Date(newsletter.created_at).toLocaleDateString(
                        "en-US",
                        {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                        }
                      )}
                    </p>
                  </div>
                  <Badge
                    variant={
                      newsletter.status === "sent" ? "success" : "secondary"
                    }
                  >
                    {newsletter.status}
                  </Badge>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Quick actions */}
      {!loading && !error && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-8 text-center">
              <VideoIcon className="h-8 w-8 text-muted-foreground mb-3" />
              <p className="font-medium text-sm mb-1">Add Videos</p>
              <p className="text-xs text-muted-foreground mb-4">
                Paste YouTube URLs or a playlist link
              </p>
              <Link href="/input">
                <Button variant="outline" size="sm">
                  Go to Input
                </Button>
              </Link>
            </CardContent>
          </Card>

          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-8 text-center">
              <FileText className="h-8 w-8 text-muted-foreground mb-3" />
              <p className="font-medium text-sm mb-1">Browse History</p>
              <p className="text-xs text-muted-foreground mb-4">
                View, download, or send past newsletters
              </p>
              <Link href="/history">
                <Button variant="outline" size="sm">
                  View History
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
