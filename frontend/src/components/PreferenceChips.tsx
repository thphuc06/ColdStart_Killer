import { Check } from "lucide-react";

import type { OnboardingOption } from "../lib/api";


type PreferenceChipsProps = {
    label: string;
    options: OnboardingOption[];
    selected: string[];
    onChange: (selected: string[]) => void;
};


export function PreferenceChips({ label, options, selected, onChange }: PreferenceChipsProps) {
    const selectedSet = new Set(selected);

    function toggle(optionId: string) {
        if (selectedSet.has(optionId)) {
            onChange(selected.filter((value) => value !== optionId));
            return;
        }
        onChange([...selected, optionId]);
    }

    return (
        <section>
            <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-sm font-medium text-[var(--ink-strong)]">{label}</h3>
                <span className="text-xs text-[var(--ink-soft)]">{selected.length} selected</span>
            </div>
            <div className="flex flex-wrap gap-2">
                {options.map((option) => {
                    const isSelected = selectedSet.has(option.id);
                    return (
                        <button
                            key={option.id}
                            aria-pressed={isSelected}
                            className={`chip ${isSelected ? "badge-sky" : ""}`}
                            type="button"
                            onClick={() => toggle(option.id)}
                        >
                            {isSelected ? <Check className="h-3.5 w-3.5" /> : null}
                            {option.label}
                            {typeof option.count === "number" ? <span className="text-[var(--ink-muted)]">({option.count})</span> : null}
                        </button>
                    );
                })}
            </div>
        </section>
    );
}
