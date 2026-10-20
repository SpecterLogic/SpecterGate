import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { MoreHorizontal } from "lucide-react";

/** Portal keeps row actions outside the table's scrolling/clipping container. */
export default function ActionMenu({ children }: { children: ReactNode }) {
  const anchor = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  useEffect(() => {
    if (!position) return;
    const close = (e: MouseEvent) => {
      if (!menu.current?.contains(e.target as Node) && !anchor.current?.contains(e.target as Node)) setPosition(null);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setPosition(null); anchor.current?.focus(); } };
    const scroll = () => setPosition(null);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", scroll);
    window.addEventListener("scroll", scroll, true);
    menu.current?.querySelector("button")?.focus();
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", scroll);
      window.removeEventListener("scroll", scroll, true);
    };
  }, [position]);
  return <>
    <button ref={anchor} type="button" className="icon-btn" title="عملیات بیشتر" aria-haspopup="menu" aria-expanded={!!position} onClick={() => {
      if (position) { setPosition(null); return; }
      const rect = anchor.current!.getBoundingClientRect();
      setPosition({ top: Math.max(8, Math.min(rect.bottom + 5, window.innerHeight - 260)), left: Math.max(8, Math.min(rect.left, window.innerWidth - 208)) });
    }}><MoreHorizontal size={18} /></button>
    {position && createPortal(<div ref={menu} className="action-menu-pop action-menu-portal" role="menu" style={position} onClick={() => setPosition(null)}>{children}</div>, document.body)}
  </>;
}
