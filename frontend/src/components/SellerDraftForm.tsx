import { Eye, PackagePlus, ShieldCheck } from "lucide-react";
import { useState } from "react";

import type { SellerDraftPayload } from "../lib/api";


type SellerDraftFormProps = {
    disabled?: boolean;
    isCreating: boolean;
    onCreate: (payload: SellerDraftPayload) => void;
};


export function SellerDraftForm({ disabled = false, isCreating, onCreate }: SellerDraftFormProps) {
    const [title, setTitle] = useState("");
    const [description, setDescription] = useState("");
    const [brand, setBrand] = useState("");
    const [categoryId, setCategoryId] = useState("");
    const [featuresText, setFeaturesText] = useState("");
    const [priceVnd, setPriceVnd] = useState("");
    const [priceBucket, setPriceBucket] = useState("unknown");
    const [imageUrl, setImageUrl] = useState("");

    function submit() {
        onCreate({
            seller_id: "seller_demo_001",
            title,
            description,
            brand,
            category_id: categoryId,
            features: featuresText.split(/\r?\n/).map((feature) => feature.trim()).filter(Boolean),
            price_vnd: priceVnd ? Number(priceVnd) : null,
            price_bucket: priceBucket,
            image_url: imageUrl || null,
            attributes: {},
        });
    }

    return (
        <section className="panel p-6">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <p className="soft-label">Seller draft staging</p>
                    <h2 className="mt-2 text-2xl font-medium text-[var(--ink-strong)]">Create product draft</h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
                        Creating a draft writes only to `seller_product_drafts`. Index preview and catalog write are separate steps.
                    </p>
                </div>
                <div className="flex items-center gap-2 rounded-lg bg-[var(--surface-muted)] px-3 py-2 text-xs font-semibold text-[var(--ink-soft)]">
                    <ShieldCheck className="h-4 w-4 text-[var(--mint)]" />
                    staged only
                </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Product title
                    <input className="form-input" value={title} onChange={(event) => setTitle(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Brand
                    <input className="form-input" value={brand} onChange={(event) => setBrand(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Category ID
                    <input className="form-input" value={categoryId} onChange={(event) => setCategoryId(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Price VND
                    <input className="form-input" type="number" value={priceVnd} onChange={(event) => setPriceVnd(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Price bucket
                    <select className="form-select" value={priceBucket} onChange={(event) => setPriceBucket(event.target.value)}>
                        <option value="unknown">Unknown / derive from price</option>
                        <option value="under_100k">Under 100k</option>
                        <option value="100k_300k">100k to 300k</option>
                        <option value="300k_700k">300k to 700k</option>
                        <option value="700k_1500k">700k to 1.5m</option>
                        <option value="over_1500k">Over 1.5m</option>
                    </select>
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Image URL
                    <input className="form-input" value={imageUrl} onChange={(event) => setImageUrl(event.target.value)} />
                </label>
            </div>

            <label className="mt-4 block space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                Description
                <textarea className="form-input min-h-28" value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label className="mt-4 block space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                Features (one per line)
                <textarea className="form-input min-h-24" value={featuresText} onChange={(event) => setFeaturesText(event.target.value)} />
            </label>

            <div className="mt-5 flex flex-wrap gap-3">
                <button className="action-button action-button-primary" disabled={isCreating || disabled} type="button" onClick={submit}>
                    <PackagePlus className="h-4 w-4" />
                    {isCreating ? "Creating..." : "Create draft"}
                </button>
                <div className="flex items-center gap-2 text-xs text-[var(--ink-soft)]">
                    <Eye className="h-4 w-4" />
                    {disabled ? "Seller or admin token required before seller draft writes." : "Preview and approve are not automatic."}
                </div>
            </div>
        </section>
    );
}

