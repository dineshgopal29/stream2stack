"use client"

import { useEffect, useState } from "react"
import { useParams, useRouter } from "next/navigation"
import Link from "next/link"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  getNewsletter,
  getSettings,
  sendNewsletter,
  deleteNewsletter,
  type Newsletter,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
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
import { useToast } from "@/components/ui/use-toast"
import {
  ArrowLeft,
  Download,
  Send,
  Calendar,
  Loader2,
  CheckCircle2,
  Trash2,
} from "lucide-react"

const DEMO_USER_ID = "demo-user-id"

function NewsletterSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Skeleton className="h-9 w-3/4" />
        <Skeleton className="h-4 w-48" />
      </div>
      <Separator />
      <div className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    </div>
  )
}

export default function NewsletterPage() {
  const params = useParams()
  const router = useRouter()
  const { toast } = useToast()
  const id = params.id as string

  const [newsletter, setNewsletter] = useState<Newsletter | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [sendDialogOpen, setSendDialogOpen] = useState(false)
  const [sendEmail, setSendEmail] = useState("")
  const [isSending, setIsSending] = useState(false)

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  useEffect(() => {
    async function fetchData() {
      try {
        const [data, settings] = await Promise.all([
          getNewsletter(id),
          getSettings(DEMO_USER_ID).catch(() => null),
        ])
        setNewsletter(data)
        if (settings?.recipient_email) {
          setSendEmail(settings.recipient_email)
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load newsletter"
        )
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [id])

  function downloadMarkdown() {
    if (!newsletter) return
    const blob = new Blob([newsletter.content_md], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${newsletter.title
      .replace(/[^a-z0-9]/gi, "-")
      .toLowerCase()}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  async function handleSend() {
    if (!sendEmail.trim()) {
      toast({
        title: "Email required",
        description: "Please enter a recipient email address.",
        variant: "destructive",
      })
      return
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailRegex.test(sendEmail.trim())) {
      toast({
        title: "Invalid email",
        description: "Please enter a valid email address.",
        variant: "destructive",
      })
      return
    }

    setIsSending(true)
    try {
      await sendNewsletter(id, sendEmail.trim())

      setNewsletter((prev) =>
        prev
          ? { ...prev, status: "sent" as const, sent_at: new Date().toISOString() }
          : prev
      )

      toast({
        title: "Newsletter sent!",
        description: `Sent to ${sendEmail.trim()}.`,
      })
      setSendDialogOpen(false)
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
    setIsDeleting(true)
    try {
      await deleteNewsletter(id)
      toast({ title: "Newsletter deleted." })
      router.push("/history")
    } catch (err) {
      toast({
        title: "Delete failed",
        description: err instanceof Error ? err.message : "An error occurred.",
        variant: "destructive",
      })
      setIsDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  return (
    <div className="container max-w-screen-md py-8 space-y-6">
      {/* Back link */}
      <Link
        href="/history"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to History
      </Link>

      {loading ? (
        <NewsletterSkeleton />
      ) : error ? (
        <div className="py-16 text-center">
          <p className="text-muted-foreground">{error}</p>
          <Link href="/history" className="mt-4 inline-block">
            <Button variant="outline" size="sm">
              Back to History
            </Button>
          </Link>
        </div>
      ) : newsletter ? (
        <>
          {/* Header */}
          <div className="space-y-3">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <h1 className="text-3xl font-bold tracking-tight flex-1">
                {newsletter.title}
              </h1>
              <Badge
                variant={newsletter.status === "sent" ? "success" : "secondary"}
                className="flex-shrink-0"
              >
                {newsletter.status === "sent" ? (
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                ) : null}
                {newsletter.status}
              </Badge>
            </div>

            <div className="flex items-center gap-4 text-sm text-muted-foreground flex-wrap">
              <div className="flex items-center gap-1.5">
                <Calendar className="h-4 w-4" />
                <span>
                  {new Date(newsletter.created_at).toLocaleDateString("en-US", {
                    weekday: "long",
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  })}
                </span>
              </div>
              {newsletter.sent_at && (
                <div className="flex items-center gap-1.5">
                  <Send className="h-4 w-4" />
                  <span>
                    Sent {new Date(newsletter.sent_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 pt-1 flex-wrap">
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={downloadMarkdown}
              >
                <Download className="h-4 w-4" />
                Download .md
              </Button>
              {newsletter.status === "draft" && (
                <Button
                  size="sm"
                  className="gap-2"
                  onClick={() => setSendDialogOpen(true)}
                >
                  <Send className="h-4 w-4" />
                  Send via Email
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                className="gap-2 text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setDeleteDialogOpen(true)}
              >
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
            </div>
          </div>

          <Separator />

          {/* Newsletter Content */}
          <article className="prose max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {newsletter.content_md}
            </ReactMarkdown>
          </article>
        </>
      ) : null}

      {/* Send Dialog */}
      <Dialog open={sendDialogOpen} onOpenChange={setSendDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send Newsletter</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Enter the email address to send this newsletter to.
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
                onClick={() => setSendDialogOpen(false)}
                disabled={isSending}
              >
                Cancel
              </Button>
              <Button
                onClick={handleSend}
                disabled={isSending || !sendEmail.trim()}
                className="gap-2"
              >
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
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
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
              {isDeleting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              {isDeleting ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
