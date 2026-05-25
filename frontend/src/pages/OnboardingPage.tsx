import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, SlidersHorizontal } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { OnboardingWizard } from "../components/OnboardingWizard";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import {
    completeOnboarding,
    getOnboardingOptions,
    previewOnboardingPreferences,
    type OnboardingPreferencesPayload,
    type OnboardingPreviewResponse,
} from "../lib/api";
import { useExperience } from "../state/experience";


export function OnboardingPage() {
    const navigate = useNavigate();
    const { userIdHash, sessionId } = useExperience();
    const optionsQuery = useQuery({ queryKey: ["onboarding-options"], queryFn: getOnboardingOptions });
    const previewMutation = useMutation<OnboardingPreviewResponse, Error, OnboardingPreferencesPayload>({
        mutationFn: (payload) => previewOnboardingPreferences({ ...payload, user_id_hash: userIdHash || undefined }),
    });
    const completeMutation = useMutation({
        mutationFn: (payload: OnboardingPreferencesPayload) =>
            completeOnboarding({
                ...payload,
                user_id_hash: userIdHash || "",
                session_id: sessionId,
            }),
        onSuccess: () => navigate("/", { replace: true }),
    });

    function skipOnboarding() {
        navigate("/", { replace: true });
    }

    if (optionsQuery.isLoading) {
        return <LoadingState title="Loading onboarding" message="Preparing catalog-backed preference options." />;
    }

    if (optionsQuery.error instanceof Error) {
        return <ErrorState title="Onboarding unavailable" message={optionsQuery.error.message} />;
    }

    const options = optionsQuery.data;
    if (!options || !options.enabled) {
        return (
            <section className="space-y-5">
                <header className="panel p-6">
                    <StatusBadge tone="amber">Optional onboarding</StatusBadge>
                    <h1 className="mt-3 text-2xl font-medium text-[var(--ink-strong)]">Onboarding is disabled</h1>
                    <p className="mt-2 text-sm text-[var(--ink-soft)]">
                        The existing demo shopper selector and recommendation flow remain available.
                    </p>
                </header>
                <EmptyState
                    title="Preference onboarding is off"
                    message={options?.message || "Set ENABLE_ONBOARDING=true to enable this optional flow."}
                    action={
                        <button className="action-button action-button-primary" type="button" onClick={skipOnboarding}>
                            Continue to recommendations
                        </button>
                    }
                />
            </section>
        );
    }

    return (
        <section className="space-y-5">
            <header className="panel p-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <SlidersHorizontal className="h-5 w-5 text-[var(--sky)]" />
                            <p className="soft-label">Cold-user setup</p>
                        </div>
                        <h1 className="mt-3 text-2xl font-medium text-[var(--ink-strong)]">Choose your starter preferences</h1>
                        <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">
                            This is not a perfect-profile shortcut. It captures explicit starter preferences and optional real
                            catalog seed items so the normal behavior pipeline can learn from them.
                        </p>
                    </div>
                    <StatusBadge tone="mint">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Read-only preview first
                    </StatusBadge>
                </div>
            </header>

            <OnboardingWizard
                options={options}
                preview={previewMutation.data}
                isPreviewing={previewMutation.isPending}
                isCompleting={completeMutation.isPending}
                onPreview={(payload) => previewMutation.mutate(payload)}
                onComplete={(payload) => completeMutation.mutate(payload)}
                onSkip={skipOnboarding}
            />

            {previewMutation.error ? (
                <ErrorState title="Preview failed" message={previewMutation.error.message} />
            ) : null}
            {completeMutation.error instanceof Error ? (
                <ErrorState title="Onboarding save failed" message={completeMutation.error.message} />
            ) : null}
            {completeMutation.isSuccess ? (
                <div className="feed-refresh-status">
                    <CheckCircle2 className="h-4 w-4 text-[var(--mint)]" />
                    Onboarding saved; redirecting to recommendations.
                </div>
            ) : null}
        </section>
    );
}
