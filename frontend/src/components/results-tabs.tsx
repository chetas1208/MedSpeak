"use client";

import type { ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import type { JobResponse } from "@/lib/types";

export type ResultTabKey = "summary" | "intents" | "checklist" | "accommodations" | "scripts" | "transcript";

const tabs: { key: ResultTabKey; label: string }[] = [
  { key: "summary", label: "Summaries" },
  { key: "intents", label: "Intent View" },
  { key: "checklist", label: "Next Steps" },
  { key: "accommodations", label: "Accommodation Card" },
  { key: "scripts", label: "Scripts" },
  { key: "transcript", label: "Transcript" },
];

function SectionCard({
  title,
  subtitle,
  children,
  tint = "white",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  tint?: "white" | "teal" | "gold";
}) {
  const tone =
    tint === "teal"
      ? "border-[color:var(--border-strong)] bg-[var(--surface-muted)]"
      : tint === "gold"
        ? "border-[color:var(--border)] bg-[var(--surface-gold)]"
        : "border-[color:var(--border)] bg-[var(--surface-strong)]";

  return (
    <section className={`rounded-[28px] border p-5 shadow-[var(--shadow-soft)] ${tone}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h3>
          {subtitle ? <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{subtitle}</p> : null}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function BulletList({ items, tone = "white" }: { items: string[]; tone?: "white" | "teal" | "gold" }) {
  const itemTone =
    tone === "teal"
      ? "border-[color:var(--border-strong)] bg-[var(--surface-strong)]"
      : tone === "gold"
        ? "border-[color:var(--border)] bg-[var(--surface-strong)]"
        : "border-[color:var(--border)] bg-[var(--surface-soft)]";

  return (
    <ul className="space-y-3">
      {items.map((item, index) => (
        <li
          key={`${item}-${index}`}
          className={`rounded-2xl border px-4 py-3 text-sm leading-6 text-[var(--text-secondary)] ${itemTone}`}
        >
          {item}
        </li>
      ))}
    </ul>
  );
}

export function ResultsTabs({
  job,
  activeTab,
  onActiveTabChange,
}: {
  job: JobResponse;
  activeTab: ResultTabKey;
  onActiveTabChange: (tab: ResultTabKey) => void;
}) {
  const result = job.result_json;

  if (!result) {
    return null;
  }

  const content = (() => {
    switch (activeTab) {
      case "summary":
        return (
          <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
            <SectionCard
              title="What happened"
              subtitle="A grounded plain-language recap generated only from the recorded discussion."
            >
              <p className="whitespace-pre-line text-sm leading-7 text-[var(--text-secondary)]">{result.standard_summary}</p>
            </SectionCard>
            <SectionCard
              title="Autism-friendly summary"
              subtitle="Short, literal language with explicit steps and no vague timing."
              tint="teal"
            >
              <p className="whitespace-pre-line text-sm leading-7 text-[var(--text-primary)]">{result.autism_friendly_summary}</p>
            </SectionCard>
            <SectionCard title="Intent summary" subtitle="What each part of the visit was trying to accomplish." tint="gold">
              <BulletList items={result.intent_summary} tone="gold" />
            </SectionCard>
            <div className="grid gap-5">
              <SectionCard title="Questions to ask next" subtitle="Follow-up questions to bring into the next appointment.">
                <BulletList items={result.questions_to_ask} />
              </SectionCard>
              <SectionCard title="Safety note" subtitle="MedSpeak keeps this grounded to the visit record only." tint="teal">
                <p className="text-sm leading-7 text-[var(--text-primary)]">{result.safety_note}</p>
              </SectionCard>
            </div>
            <div className="grid gap-5 lg:col-span-2 lg:grid-cols-2">
              <SectionCard title="Red flags" subtitle="Only if stated in the visit record.">
                <BulletList items={result.red_flags} />
              </SectionCard>
              <SectionCard title="Uncertainties" subtitle="Anything that was unclear, unstated, or could not be verified.">
                <BulletList items={result.uncertainties} />
              </SectionCard>
            </div>
          </div>
        );
      case "intents":
        return (
          <div className="space-y-5">
            <SectionCard title="Intent timeline" subtitle="A segment-by-segment view of what was happening in the conversation." tint="teal">
              <div className="space-y-3">
                {result.intent_timeline.map((segment, index) => (
                  <article
                    key={`${segment.start}-${segment.end}-${index}`}
                    className="rounded-[24px] border border-[color:var(--border-strong)] bg-[var(--surface-strong)] px-4 py-4 shadow-[var(--shadow-soft)]"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--brand-teal-deep)]">
                          {segment.start} - {segment.end}
                        </p>
                        <p className="mt-1 text-sm font-semibold text-[var(--text-primary)]">{segment.speaker}</p>
                      </div>
                      <span className="rounded-full bg-[var(--surface-gold)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[#8a6a1d]">
                        Confidence {segment.confidence.toFixed(2)}
                      </span>
                    </div>
                    <p className="mt-3 whitespace-pre-line text-sm leading-7 text-[var(--text-secondary)]">{segment.text}</p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {segment.intents.map((intent) => (
                        <span
                          key={`${segment.start}-${segment.end}-${intent}`}
                          className="rounded-full border border-[color:var(--border-strong)] bg-[var(--surface-muted)] px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--brand-teal-deep)]"
                        >
                          {intent}
                        </span>
                      ))}
                    </div>
                  </article>
                ))}
              </div>
            </SectionCard>
          </div>
        );
      case "checklist":
        return (
          <div className="grid gap-5 xl:grid-cols-[0.88fr_1.12fr]">
            <SectionCard title="Next steps" subtitle="Concrete handoff items from the visit." tint="teal">
              <div className="space-y-3">
                {result.next_steps_checklist.map((item, index) => (
                  <article key={`step-${index}`} className="rounded-[24px] border border-[color:var(--border-strong)] bg-[var(--surface-strong)] px-4 py-4">
                    <p className="text-base font-semibold text-[var(--text-primary)]">{item.step}</p>
                    <p className="mt-2 text-sm text-[var(--text-secondary)]">Who: {item.who}</p>
                    <p className="text-sm text-[var(--text-secondary)]">When: {item.when}</p>
                  </article>
                ))}
              </div>
            </SectionCard>
            <div className="grid gap-5">
              <SectionCard title="Medications" subtitle="Only what the visit explicitly stated.">
                <div className="space-y-3">
                  {result.medications.map((item, index) => (
                    <article key={`med-${index}`} className="rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-soft)] px-4 py-4">
                      <p className="text-base font-semibold text-[var(--text-primary)]">{item.name}</p>
                      <p className="mt-2 text-sm text-[var(--text-secondary)]">Dose: {item.dose}</p>
                      <p className="text-sm text-[var(--text-secondary)]">Frequency: {item.frequency}</p>
                      <p className="text-sm text-[var(--text-secondary)]">Purpose: {item.purpose}</p>
                      <p className="text-sm text-[var(--text-secondary)]">Notes: {item.notes}</p>
                    </article>
                  ))}
                </div>
              </SectionCard>
              <SectionCard title="Tests and referrals" subtitle="Orders or follow-up items explicitly mentioned in the record." tint="gold">
                <div className="space-y-3">
                  {result.tests_and_referrals.map((item, index) => (
                    <article key={`test-${index}`} className="rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-4">
                      <p className="text-base font-semibold text-[var(--text-primary)]">{item.item}</p>
                      <p className="mt-2 text-sm text-[var(--text-secondary)]">Purpose: {item.purpose}</p>
                      <p className="text-sm text-[var(--text-secondary)]">When: {item.when}</p>
                    </article>
                  ))}
                </div>
              </SectionCard>
            </div>
          </div>
        );
      case "accommodations":
        return (
          <div className="grid gap-5 xl:grid-cols-[1.06fr_0.94fr]">
            <SectionCard
              title="Accommodation card"
              subtitle="A quick support snapshot you can show or reuse before the next visit."
              tint="teal"
            >
              <p className="text-sm leading-7 text-[var(--text-primary)]">{result.accommodation_card.summary}</p>
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <SectionCard title="Communication">
                  <BulletList items={result.accommodation_card.communication} />
                </SectionCard>
                <SectionCard title="Sensory">
                  <BulletList items={result.accommodation_card.sensory} />
                </SectionCard>
                <SectionCard title="Processing">
                  <BulletList items={result.accommodation_card.processing} />
                </SectionCard>
                <SectionCard title="Support">
                  <BulletList items={result.accommodation_card.support} />
                </SectionCard>
              </div>
            </SectionCard>
            <SectionCard title="Quick visit snapshot" subtitle="A compact view of the recorded intent flow.">
              <div className="space-y-3">
                {result.intent_timeline.map((segment, index) => (
                  <article key={`snapshot-${index}`} className="rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-soft)] px-4 py-4">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--brand-teal-deep)]">
                      {segment.start} - {segment.end}
                    </p>
                    <p className="mt-2 text-sm font-semibold text-[var(--text-primary)]">{segment.intents.join(", ")}</p>
                    <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">{segment.text}</p>
                  </article>
                ))}
              </div>
            </SectionCard>
          </div>
        );
      case "scripts":
        return (
          <div className="grid gap-5 lg:grid-cols-2">
            {result.social_scripts.map((item, index) => (
              <SectionCard
                key={`script-${index}`}
                title={item.situation}
                subtitle="A reusable literal script for support or clarification."
                tint={index % 2 === 0 ? "gold" : "teal"}
              >
                <p className="whitespace-pre-line text-sm leading-7 text-[var(--text-secondary)]">{item.script}</p>
              </SectionCard>
            ))}
          </div>
        );
      case "transcript":
        return (
          <SectionCard title="Returned transcript" subtitle="Transcript returned by the backend for review and grounded chat.">
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-contrast)] px-4 py-5 text-sm leading-7 text-slate-100">
              {job.transcript_redacted ?? "Transcript not available."}
            </pre>
          </SectionCard>
        );
    }
  })();

  return (
    <section className="space-y-6 rounded-[34px] border border-[color:var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-medium)] backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="flex items-start gap-4">
          <BrandMark alt="MedSpeak logo" size={54} />
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.26em] text-[var(--brand-teal-deep)]">MedSpeak visit report</p>
            <h2 className="mt-2 text-3xl font-semibold text-[var(--text-primary)]">Analysis Results</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">Job ID: {job.job_id}</p>
          </div>
        </div>
        {job.pdf_path_or_url ? (
          <a
            className="inline-flex min-h-14 items-center justify-center gap-3 rounded-full border border-[color:var(--border-strong)] bg-[linear-gradient(135deg,var(--brand-gold),#f7d78e)] px-7 py-3 text-sm font-semibold text-[var(--surface-contrast)] shadow-[var(--shadow-medium)] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-strong)]"
            href={job.pdf_path_or_url}
            rel="noreferrer"
            target="_blank"
          >
            <span className="rounded-full bg-white/60 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-[var(--surface-contrast)]">
              PDF
            </span>
            Download MedSpeak Report
          </a>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${
              activeTab === tab.key
                ? "bg-[var(--surface-contrast)] text-white shadow-[var(--shadow-soft)]"
                : "bg-[var(--surface-soft)] text-[var(--text-secondary)] hover:bg-[var(--surface-gold)] hover:text-[var(--text-primary)]"
            }`}
            onClick={() => onActiveTabChange(tab.key)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      {content}
    </section>
  );
}
