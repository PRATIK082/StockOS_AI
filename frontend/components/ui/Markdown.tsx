"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

export default function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children: cell }) => (
            <div className="my-3 overflow-x-auto rounded-md border border-border">
              <table className="w-full text-left text-sm">{cell}</table>
            </div>
          ),
          thead: ({ children: cell }) => (
            <thead className="border-b border-border bg-muted/40 text-xs uppercase tracking-wide">{cell}</thead>
          ),
          th: ({ children: cell }) => (
            <th className="px-3 py-2 font-semibold text-muted-foreground">{cell}</th>
          ),
          td: ({ children: cell }) => <td className="border-t border-border/50 px-3 py-1.5">{cell}</td>,
          tr: ({ children: cell }) => <tr className="hover:bg-muted/30">{cell}</tr>,
          hr: () => <hr className="my-4 border-border" />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}