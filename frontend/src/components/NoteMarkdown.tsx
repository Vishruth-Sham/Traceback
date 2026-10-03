"use client";

import { useEffect, useRef, useState } from "react";
import { marked } from "marked";

export function NoteMarkdown({ content }: { content: string }) {
  const root = useRef<HTMLDivElement>(null);
  const [html, setHtml] = useState("");

  useEffect(() => {
    let active = true;
    void import("dompurify").then(({ default: DOMPurify }) => {
      if (!active) return;
      // Markdown can contain raw HTML. Sanitize before it reaches the DOM.
      setHtml(DOMPurify.sanitize(marked.parse(content || "*Nothing here yet — switch to Edit to start writing.*") as string));
    });
    return () => { active = false; };
  }, [content]);

  useEffect(() => {
    if (!html || !root.current) return;
    const blocks = root.current.querySelectorAll<HTMLElement>("pre code.language-mermaid");
    if (!blocks.length) return;
    let active = true;
    void Promise.all([import("mermaid"), import("dompurify")]).then(async ([{ default: mermaid }, { default: DOMPurify }]) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", flowchart: { htmlLabels: false } });
      for (const [index, code] of Array.from(blocks).entries()) {
        if (!active) return;
        const container = document.createElement("div");
        container.className = "note-mermaid";
        container.setAttribute("role", "img");
        container.setAttribute("aria-label", "Mermaid diagram");
        try {
          const { svg } = await mermaid.render(`note-mermaid-${crypto.randomUUID()}-${index}`, code.textContent ?? "");
          if (!active) return;
          container.innerHTML = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });
          code.parentElement?.replaceWith(container);
        } catch {
          // Preserve the source fence when a diagram is invalid.
        }
      }
    });
    return () => { active = false; };
  }, [html]);

  return (
    <div
      ref={root}
      className="note-markdown text-[13.5px] text-ink [&_a]:text-accent-navy [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:font-serif [&_h1]:text-[17px] [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:font-serif [&_h2]:text-[15.5px] [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-3 [&_h3]:font-serif [&_h3]:text-[14.5px] [&_h3]:font-semibold [&_li]:mb-1 [&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:mb-3 [&_strong]:font-semibold [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-5"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
