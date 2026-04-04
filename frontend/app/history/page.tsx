"use client"

import { useEffect, useState, useMemo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import Link from "next/link"
import {
  getNewsletters,
  getSettings,
  sendNewsletter,
  deleteNewsletter,
  type Newsletter,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Label } from "@/components/ui/label"
import { useToast } from "@/components/ui/use-toast"
import {
  Download,
  Send,
  Eye,
  Search,
  FileText,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  Calendar,
  Trash2,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"

const DEMO_USER_ID = "demo-user-id"
const PAGE_SIZE = 10

function NewsletterSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 space-y-2">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-1/3" />
          </div>
          <Skeleton className="h-6 w-16 rounded-full" />
        </div>
      </CardHeader>
    </Card>
  )
}

function downloadMarkdown(newsletter: Newsletter) {
  const blob = new Blob([newsletter.content_md], { type: "text/markdown" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${newsletter.title.replace(/[^a-z0-9]/gi, "-").toLowerCase()}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

interface SendDialogState {
  open: boolean
  newsletterId: string
  newsletterTitle: string
}

export default function HistoryPage() {
  const { toast } = useToast()

  const [newsletters, setNewsletters] = useState<Newsletter[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [page, setPage] = useState(0)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [savedEmail, setSavedEmail] = useState("")

  const [viewDialog, setViewDialog] = useState<{
    open: boolean
    newsletter: Newsletter | null
  }>({ open: false, newsletter: null })

  const [sendDialog, setSendDialog] = useState<SendDialogState>({
    open: false,
    newsletterId: "",
    newsletterTitle: "",
  })
  const [sendEmail, setSendEmail] = useState("")
  const [isSending, setIsSending] = useState(false)

  const [deleteDialogId, setDeleteDialogId] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  useEffect(() => {
    async function fetchData() {
      try {
        const [data, settings] = await Promise.all([
          getNewsletters(DEMO_USER_ID),
          getSettings(DEMO_USER_ID).catch(() => null),
        ])
        const sorted = data.sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        )
        setNewsletters(sorted)
        if (settings?.recipient_email) {
          setSavedEmail(settings.recipient_email)
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load newsletters"
        )
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  const filteredNewsletters = useMemo(() => {
    if (!searchQuery.trim()) return newsletters
    const q = searchQuery.toLowerCase()
    return newsletters.filter((n) => n.title.toLowerCase().includes(q))
  }, [newsletters, searchQuery])

  const totalPages = Math.ceil(filteredNewsletters.length / PAGE_SIZE)
  const pagedNewsletters = filteredNewsletters.slice(
    page * PAGE_SIZE,
    page * PAGE_SIZE + PAGE_SIZE
  )

  // Reset to page 0 when search changes
  useEffect(() => {
    setPage(0)
  }, [searchQuery])

  function openSendDialog(newsletter: Newsletter) {
    setSendEmail(savedEmail)
    setSendDialog({
      open: true,
      newsletterId: newsletter.id,
      newsletterTitle: newsletter.title,
    })
  }

  async function handleSend() {
    if (!sendEmail.trim()) {
      toast({
        title: "Email required",
        description: "Please enter a recipient email.",
        variant: "destructive",
      })
      return
    }

    setIsSending(true)
    try {
      await sendNewsletter(sendDialog.newsletterId, sendEmail.trim())

      setNewsletters((prev) =>
        prev.map((n) =>
          n.id === sendDialog.newsletterId
            ? { ...n, status: "sent" as const, sent_at: new Date().toISOString() }
            : n
        )
      )

      toast({
        title: "Newsletter sent!",
        description: `Sent to ${sendEmail.trim()}.`,
      })

      setSendDialog({ open: false, newsletterId: "", newsletterTitle: "" })
      setSendEmail("")
    } catch (err) {
      toast({
        title: "Send failed",
        description: err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsSending(false)
    }
  }

  async function handleDelete() {
    if (!deleteDialogId) return
    setIsDeleting(true)
    try {
      await deleteNewsletter(deleteDialogId)
      setNewsletters((prev) => prev.filter((n) => n.id !== deleteDialogId))
      toast({ title: "Newsletter deleted." })
    } catch (err) {
      toast({
        title: "Delete failed",
        description: err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
    } finally {
      setIsDeleting(false)
      setDeleteDialogId(null)
    }
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  return (
    <div className="container max-w-screen-lg py-8 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">History</h1>
          <p className="text-muted-foreground mt-1">
            All generated newsletters
          </p>
        </div>
        <Link href="/input">
          <Button className="gap-2">
            <Plus className="h-4 w-4" />
            New Newsletter
          </Button>
        </Link>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search newsletters..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Content */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <NewsletterSkeleton key={i} />
          ))}
        </div>
      ) : error ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground text-sm">{error}</p>
            <p className="text-xs text-muted-foreground mt-1">
              Make sure the backend is running.
            </p>
          </CardContent>
        </Card>
      ) : filteredNewsletters.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <FileText className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
            <p className="font-medium text-muted-foreground">
              {searchQuery ? "No newsletters match your search" : "No newsletters yet"}
            </p>
            {!searchQuery && (
              <>
                <p className="text-sm text-muted-foreground mt-1 mb-4">
                  Generate your first newsletter from YouTube content.
                </p>
                <Link href="/input">
                  <Button size="sm">
                    <Plus className="h-4 w-4 mr-1" />
                    Get Started
                  </Button>
                </Link>
              </>
            )}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="space-y-3">
            {pagedNewsletters.map((newsletter) => (
              <Card key={newsletter.id} className="overflow-hidden">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-sm truncate">
                          {newsletter.title}
                        </h3>
                        <Badge
                          variant={
                            newsletter.status === "sent" ? "success" : "secondary"
                          }
                          className="flex-shrink-0"
                        >
                          {newsletter.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
                        <Calendar className="h-3 w-3" />
                        <span>
                          {new Date(newsletter.created_at).toLocaleDateString(
                            "en-US",
                            {
                              year: "numeric",
                              month: "long",
                              day: "numeric",
                            }
                          )}
                        </span>
                        {newsletter.sent_at && (
                          <span className="text-muted-foreground/60">
                            · Sent{" "}
                            {new Date(newsletter.sent_at).toLocaleDateString()}
                          </span>
                        )}
                        {newsletter.video_count !== undefined && (
                          <span className="text-muted-foreground/60">
                            · {newsletter.video_count} video
                            {newsletter.video_count !== 1 ? "s" : ""}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="View full newsletter"
                        onClick={() =>
                          setViewDialog({ open: true, newsletter })
                        }
                      >
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title="Download as .md"
                        onClick={() => downloadMarkdown(newsletter)}
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                      {newsletter.status === "draft" && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          title="Send newsletter"
                          onClick={() => openSendDialog(newsletter)}
                        >
                          <Send className="h-4 w-4" />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:text-destructive hover:bg-destructive/10"
                        title="Delete newsletter"
                        onClick={() => setDeleteDialogId(newsletter.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        title={
                          expandedId === newsletter.id ? "Collapse" : "Expand"
                        }
                        onClick={() => toggleExpand(newsletter.id)}
                      >
                        {expandedId === newsletter.id ? (
                          <ChevronUp className="h-4 w-4" />
                        ) : (
                          <ChevronDown className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                  </div>
                </CardHeader>

                {/* Expanded preview */}
                {expandedId === newsletter.id && (
                  <CardContent className="pt-0 border-t border-border/50">
                    <div className="prose prose-sm max-w-none mt-4 max-h-64 overflow-y-auto">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {newsletter.content_md}
                      </ReactMarkdown>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <Link href={`/newsletter/${newsletter.id}`}>
                        <Button variant="outline" size="sm" className="gap-1.5">
                          <Eye className="h-3.5 w-3.5" />
                          View Full
                        </Button>
                      </Link>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => downloadMarkdown(newsletter)}
                      >
                        <Download className="h-3.5 w-3.5" />
                        Download .md
                      </Button>
                    </div>
                  </CardContent>
                )}
              </Card>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-2">
              <p className="text-sm text-muted-foreground">
                Page {page + 1} of {totalPages} · {filteredNewsletters.length} newsletters
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => p - 1)}
                  className="gap-1"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage((p) => p + 1)}
                  className="gap-1"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* View Dialog */}
      <Dialog
        open={viewDialog.open}
        onOpenChange={(open) =>
          setViewDialog((prev) => ({ ...prev, open }))
        }
      >
        <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{viewDialog.newsletter?.title}</DialogTitle>
          </DialogHeader>
          {viewDialog.newsletter && (
            <>
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {viewDialog.newsletter.content_md}
                </ReactMarkdown>
              </div>
              <div className="flex gap-2 mt-2 pt-4 border-t border-border">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => downloadMarkdown(viewDialog.newsletter!)}
                >
                  <Download className="h-3.5 w-3.5" />
                  Download .md
                </Button>
                <Link href={`/newsletter/${viewDialog.newsletter.id}`}>
                  <Button size="sm" className="gap-1.5">
                    <Eye className="h-3.5 w-3.5" />
                    Full View
                  </Button>
                </Link>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Send Dialog */}
      <Dialog
        open={sendDialog.open}
        onOpenChange={(open) =>
          setSendDialog((prev) => ({ ...prev, open }))
        }
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send Newsletter</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Send &ldquo;{sendDialog.newsletterTitle}&rdquo; to an email address.
            </p>
            <div className="space-y-2">
              <Label htmlFor="send-email">Recipient Email</Label>
              <Input
                id="send-email"
                type="email"
                placeholder="recipient@example.com"
                value={sendEmail}
                onChange={(e) => setSendEmail(e.target.value)}
                disabled={isSending}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSend()
                }}
              />
            </div>
            <div className="flex gap-2 justify-end">
              <Button
                variant="outline"
                onClick={() =>
                  setSendDialog({
                    open: false,
                    newsletterId: "",
                    newsletterTitle: "",
                  })
                }
                disabled={isSending}
              >
                Cancel
              </Button>
              <Button onClick={handleSend} disabled={isSending || !sendEmail.trim()} className="gap-2">
                {isSending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {isSending ? "Sending..." : "Send"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteDialogId}
        onOpenChange={(open) => { if (!open) setDeleteDialogId(null) }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete newsletter?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The newsletter will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isDeleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 gap-2"
            >
              {isDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              {isDeleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
