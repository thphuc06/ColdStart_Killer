import type { ReactNode } from "react";


type StatusTone = "mint" | "sky" | "amber" | "rose" | "violet" | "neutral";

type StatusBadgeProps = {
    children: ReactNode;
    tone?: StatusTone;
};


const toneClass: Record<StatusTone, string> = {
    mint: "badge-mint",
    sky: "badge-sky",
    amber: "badge-amber",
    rose: "badge-rose",
    violet: "badge-violet",
    neutral: "",
};


export function StatusBadge({ children, tone = "neutral" }: StatusBadgeProps) {
    return <span className={`status-badge ${toneClass[tone]}`}>{children}</span>;
}
