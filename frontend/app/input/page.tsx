"use client"

import { useState, useEffect } from "react"
import Image from "next/image"
import Link from "next/link"
import {
  ingestVideos,
  generateNewsletter,
  getSettings,
  ApiError,
  type Video,
  type Newsletter,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useToast } from "@/components/ui/use-toast"
import {
  Loader2,
  Youtube,
  ListVideo,
  CheckCircle2,
  ArrowRight,
  Mail,
  Sparkles,
  Plus,
  X,
  Link as LinkIcon,
} from "lucide-react"

const DEMO_USER_ID = "demo-user-id"

function VideoCardSkeleton() {
  return (
    <div className="flex gap-3 p-3 rounded-lg border border-border/50 bg-card">
      <Skeleton className="h-16 w-28 rounded flex-shrink-0" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-3 w-32" />
        <Skeleton className="h-3 w-24" />
      </div>
    </div>
  )
}

function VideoCard({ video }: { video: Video }) {
  return (
    <div className="flex gap-3 p-3 rounded-lg border border-border/50 bg-card hover:bg-accent/30 transition-colors">
      {video.thumbnail_url ? (
        <div className="relative h-16 w-28 flex-shrink-0 rounded overflow-hidden bg-muted">
          <Image
            src={video.thumbnail_url}
            alt={video.title}
            fill
            className="object-cover"
          />
        </div>
      ) : (
        <div className="h-16 w-28 flex-shrink-0 rounded bg-muted flex items-center justify-center">
          <Youtube className="h-6 w-6 text-muted-foreground" />
        </div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium line-clamp-2">{video.title}</p>
        <p className="text-xs text-muted-foreground mt-1">{video.channel_name}</p>
        {video.published_at && (
          <p className="text-xs text-muted-foreground mt-0.5">
            {new Date(video.published_at).toLocaleDateString("en-US", {
              year: "numeric",
              month: "short",
              day: "numeric",
            })}
          </p>
        )}
      </div>
    </div>
  )
}

export default function InputPage() {
  const { toast } = useToast()

  // Ingest state
  const [videoUrls, setVideoUrls] = useState("")
  const [playlistUrl, setPlaylistUrl] = useState("")
  const [isIngesting, setIsIngesting] = useState(false)
  const [ingestedVideos, setIngestedVideos] = useState<Video[]>([])
  const [ingestComplete, setIngestComplete] = useState(false)

  // Auto-populate recipient email from saved settings
  useEffect(() => {
    getSettings(DEMO_USER_ID)
      .then((s) => { if (s.recipient_email) setRecipientEmail(s.recipient_email) })
      .catch(() => {})
  }, [])

  // Newsletter generation state
  const [recipientEmail, setRecipientEmail] = useState("")
  const [description, setDescription] = useState("")
  const [sourceUrls, setSourceUrls] = useState<string[]>([])
  const [sourceUrlInput, setSourceUrlInput] = useState("")
  const [isGenerating, setIsGenerating] = useState(false)
  const [generatedNewsletter, setGeneratedNewsletter] =
    useState<Newsletter | null>(null)

  async function handleIngest(mode: "urls" | "playlist") {
    const urls =
      mode === "urls"
        ? videoUrls
            .split("\n")
            .map((u) => u.trim())
            .filter(Boolean)
        : []
    const playlist = mode === "playlist" ? playlistUrl.trim() : undefined

    if (urls.length === 0 && !playlist) {
      toast({
        title: "No input provided",
        description:
          mode === "urls"
            ? "Please enter at least one YouTube URL."
            : "Please enter a playlist URL.",
        variant: "destructive",
      })
      return
    }

    setIsIngesting(true)
    try {
      const result = await ingestVideos(urls, playlist)
      setIngestedVideos(result.videos)
      setIngestComplete(true)
      toast({
        title: "Videos ingested!",
        description: `Successfully processed ${result.videos.length} video${result.videos.length !== 1 ? "s" : ""}.`,
      })
    } catch (err) {
      toast({
        title: "Ingestion failed",
        description:
          err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsIngesting(false)
    }
  }

  function handleAddSourceUrl() {
    const url = sourceUrlInput.trim()
    if (!url) return
    if (!/^https?:\/\/.+/.test(url)) {
      toast({
        title: "Invalid URL",
        description: "Only http:// and https:// URLs are supported.",
        variant: "destructive",
      })
      return
    }
    if (sourceUrls.includes(url)) {
      setSourceUrlInput("")
      return
    }
    setSourceUrls((prev) => [...prev, url])
    setSourceUrlInput("")
  }

  async function handleGenerateNewsletter() {
    if (recipientEmail.trim()) {
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
      if (!emailRegex.test(recipientEmail.trim())) {
        toast({
          title: "Invalid email",
          description: "Please enter a valid email address or leave it blank.",
          variant: "destructive",
        })
        return
      }
    }

    setIsGenerating(true)
    const opts = {
      recipientEmail: recipientEmail.trim() || undefined,
      autoSelect: true,
      description: description.trim() || undefined,
      sourceUrls: sourceUrls.length > 0 ? sourceUrls : undefined,
    }
    try {
      let newsletter: Newsletter
      try {
        newsletter = await generateNewsletter(DEMO_USER_ID, opts)
      } catch (err) {
        // 409 = all videos already processed — retry with force=true
        if (err instanceof ApiError && err.status === 409) {
          toast({
            title: "Re-using processed videos",
            description: "All videos were already processed — regenerating from existing content.",
          })
          newsletter = await generateNewsletter(DEMO_USER_ID, { ...opts, force: true })
        } else {
          throw err
        }
      }
      setGeneratedNewsletter(newsletter)
      toast({
        title: "Newsletter generated!",
        description: "Your newsletter has been created successfully.",
      })
    } catch (err) {
      toast({
        title: "Generation failed",
        description:
          err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsGenerating(false)
    }
  }

  function handleReset() {
    setVideoUrls("")
    setPlaylistUrl("")
    setIngestedVideos([])
    setIngestComplete(false)
    setGeneratedNewsletter(null)
    setRecipientEmail("")
    setDescription("")
    setSourceUrls([])
    setSourceUrlInput("")
  }

  return (
    <div className="container max-w-screen-lg py-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Ingest Videos</h1>
        <p className="text-muted-foreground mt-1">
          Add YouTube videos or a playlist, then generate a newsletter.
        </p>
      </div>

      {/* Step 1: Ingest */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
              1
            </div>
            <CardTitle className="text-lg">Add Videos</CardTitle>
          </div>
          <CardDescription>
            Enter YouTube video URLs or a playlist URL to ingest.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="urls">
            <TabsList className="mb-6">
              <TabsTrigger value="urls" className="gap-2">
                <Youtube className="h-4 w-4" />
                Video URLs
              </TabsTrigger>
              <TabsTrigger value="playlist" className="gap-2">
                <ListVideo className="h-4 w-4" />
                Playlist URL
              </TabsTrigger>
            </TabsList>

            <TabsContent value="urls" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="video-urls">YouTube Video URLs</Label>
                <Textarea
                  id="video-urls"
                  placeholder={`https://youtube.com/watch?v=abc123\nhttps://youtube.com/watch?v=def456\nhttps://youtube.com/watch?v=ghi789`}
                  value={videoUrls}
                  onChange={(e) => setVideoUrls(e.target.value)}
                  rows={6}
                  disabled={isIngesting || ingestComplete}
                  className="font-mono text-xs resize-none"
                />
                <p className="text-xs text-muted-foreground">
                  One URL per line. Supports youtube.com/watch and youtu.be
                  links.
                </p>
              </div>
              <Button
                onClick={() => handleIngest("urls")}
                disabled={isIngesting || ingestComplete || !videoUrls.trim()}
                className="gap-2"
              >
                {isIngesting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Youtube className="h-4 w-4" />
                )}
                {isIngesting ? "Ingesting..." : "Ingest Videos"}
              </Button>
            </TabsContent>

            <TabsContent value="playlist" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="playlist-url">YouTube Playlist URL</Label>
                <Input
                  id="playlist-url"
                  placeholder="https://youtube.com/playlist?list=PLxxx..."
                  value={playlistUrl}
                  onChange={(e) => setPlaylistUrl(e.target.value)}
                  disabled={isIngesting || ingestComplete}
                />
                <p className="text-xs text-muted-foreground">
                  All videos in the playlist will be ingested and processed.
                </p>
              </div>
              <Button
                onClick={() => handleIngest("playlist")}
                disabled={isIngesting || ingestComplete || !playlistUrl.trim()}
                className="gap-2"
              >
                {isIngesting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ListVideo className="h-4 w-4" />
                )}
                {isIngesting ? "Ingesting..." : "Ingest Playlist"}
              </Button>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Loading skeleton for videos */}
      {isIngesting && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Processing Videos...</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <VideoCardSkeleton key={i} />
            ))}
          </CardContent>
        </Card>
      )}

      {/* Step 2: Ingested Videos */}
      {ingestComplete && ingestedVideos.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                <CardTitle className="text-lg">
                  {ingestedVideos.length} Video
                  {ingestedVideos.length !== 1 ? "s" : ""} Ingested
                </CardTitle>
              </div>
              <Badge variant="success">Ready</Badge>
            </div>
          </CardHeader>
          <CardContent className="grid gap-3 max-h-80 overflow-y-auto">
            {ingestedVideos.map((video) => (
              <VideoCard key={video.id} video={video} />
            ))}
          </CardContent>
        </Card>
      )}

      {/* Step 3: Generate Newsletter */}
      {ingestComplete && !generatedNewsletter && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                2
              </div>
              <CardTitle className="text-lg">Generate Newsletter</CardTitle>
            </div>
            <CardDescription>
              Enter a recipient email and we&apos;ll generate a newsletter from
              the ingested videos.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {/* Recipient email (optional) */}
            <div className="space-y-2">
              <Label htmlFor="recipient-email">
                Recipient Email{" "}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Input
                id="recipient-email"
                type="email"
                placeholder="you@example.com"
                value={recipientEmail}
                onChange={(e) => setRecipientEmail(e.target.value)}
                disabled={isGenerating}
              />
              <p className="text-xs text-muted-foreground">
                Leave blank to save as a draft without sending.
              </p>
            </div>

            {/* Description / post angle (optional) */}
            <div className="space-y-2">
              <Label htmlFor="description">
                Post Angle{" "}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Textarea
                id="description"
                placeholder="e.g. Focus on production pitfalls, write for a beginner audience, highlight security best practices…"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isGenerating}
                className="resize-none text-sm"
              />
              <p className="text-xs text-muted-foreground">
                Describe the angle or intent — the AI will shape the post accordingly.
              </p>
            </div>

            {/* Source URLs (optional) */}
            <div className="space-y-2">
              <Label>
                Reference URLs{" "}
                <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <div className="flex gap-2">
                <Input
                  placeholder="https://example.com/article"
                  value={sourceUrlInput}
                  onChange={(e) => setSourceUrlInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      handleAddSourceUrl()
                    }
                  }}
                  disabled={isGenerating}
                  className="text-sm"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={handleAddSourceUrl}
                  disabled={isGenerating || !sourceUrlInput.trim()}
                  title="Add URL"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                The app will crawl these pages and use them as additional context (http/https only).
              </p>
              {sourceUrls.length > 0 && (
                <ul className="space-y-1.5 mt-2">
                  {sourceUrls.map((url) => (
                    <li
                      key={url}
                      className="flex items-center gap-2 text-xs rounded-md border border-border/60 bg-muted/40 px-3 py-1.5"
                    >
                      <LinkIcon className="h-3 w-3 text-muted-foreground flex-shrink-0" />
                      <span className="flex-1 truncate text-muted-foreground">{url}</span>
                      <button
                        onClick={() =>
                          setSourceUrls((prev) => prev.filter((u) => u !== url))
                        }
                        disabled={isGenerating}
                        className="text-muted-foreground hover:text-foreground disabled:opacity-50"
                        title="Remove"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <Button
              onClick={handleGenerateNewsletter}
              disabled={isGenerating}
              className="gap-2"
            >
              {isGenerating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {isGenerating ? "Generating..." : "Generate Newsletter"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Success */}
      {generatedNewsletter && (
        <Card className="border-emerald-500/30 bg-emerald-500/5">
          <CardContent className="py-8">
            <div className="flex flex-col items-center text-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20">
                <CheckCircle2 className="h-6 w-6 text-emerald-400" />
              </div>
              <div>
                <h3 className="text-lg font-semibold">Newsletter Created!</h3>
                <p className="text-muted-foreground text-sm mt-1">
                  {generatedNewsletter.title}
                </p>
              </div>
              <div className="flex flex-col sm:flex-row gap-3">
                <Link href={`/newsletter/${generatedNewsletter.id}`}>
                  <Button className="gap-2">
                    View Newsletter
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </Link>
                <Button variant="outline" className="gap-2" onClick={handleReset}>
                  <Mail className="h-4 w-4" />
                  Start New
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
