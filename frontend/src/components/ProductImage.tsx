import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";


type ProductImageProps = {
    src?: string | null;
    fallbackSrc?: string | null;
    alt: string;
    className?: string;
    loading?: "eager" | "lazy";
};


export function ProductImage({ src, fallbackSrc, alt, className, loading = "lazy" }: ProductImageProps) {
    const [currentSrc, setCurrentSrc] = useState<string | null>(src || fallbackSrc || null);

    useEffect(() => {
        setCurrentSrc(src || fallbackSrc || null);
    }, [fallbackSrc, src]);

    if (!currentSrc) {
        return (
            <div className="flex h-full items-center justify-center text-[var(--ink-muted)]">
                <Sparkles className="h-8 w-8" />
            </div>
        );
    }

    return (
        <img
            alt={alt}
            className={className || "h-full w-full object-contain"}
            loading={loading}
            src={currentSrc}
            onError={() => setCurrentSrc(currentSrc !== fallbackSrc && fallbackSrc ? fallbackSrc : null)}
        />
    );
}
