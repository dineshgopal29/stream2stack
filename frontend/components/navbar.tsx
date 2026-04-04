"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { Zap } from "lucide-react"

const navLinks = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/input", label: "Input" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
]

export function Navbar() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-16 max-w-screen-2xl items-center">
        {/* Brand */}
        <Link
          href="/dashboard"
          className="mr-8 flex items-center gap-2 font-bold text-lg tracking-tight"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Zap className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="hidden sm:inline-block">Stream2Stack</span>
        </Link>

        {/* Navigation */}
        <nav className="flex items-center gap-1 text-sm">
          {navLinks.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "rounded-md px-3 py-2 font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                pathname === href || pathname.startsWith(href + "/")
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  )
}
