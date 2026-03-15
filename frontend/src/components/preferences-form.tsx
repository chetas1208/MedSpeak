"use client";

import { processingOptions, sensoryOptions, supportOptions } from "@/lib/constants";
import type { LanguageOption, Preferences } from "@/lib/types";

type PreferencesFormProps = {
  autismMode: boolean;
  language: LanguageOption;
  preferences: Preferences;
  onAutismModeChange: (value: boolean) => void;
  onLanguageChange: (value: LanguageOption) => void;
  onPreferencesChange: (value: Preferences) => void;
};

function CheckboxGrid({
  label,
  options,
  values,
  onToggle,
}: {
  label: string;
  options: readonly { value: string; label: string }[];
  values: string[];
  onToggle: (nextValue: string) => void;
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm font-semibold text-slate-700">{label}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => {
          const checked = values.includes(option.value);
          return (
            <label
              key={option.value}
              className={`flex cursor-pointer items-center gap-3 rounded-2xl border px-3 py-3 text-sm transition ${
                checked
                  ? "border-[color:var(--border-strong)] bg-[var(--surface-muted)] text-[var(--text-primary)] shadow-[inset_0_0_0_1px_rgba(47,171,173,0.12)]"
                  : "border-[color:var(--border)] bg-[var(--surface-strong)] text-[var(--text-secondary)] hover:bg-[var(--surface-gold)]"
              }`}
            >
              <input
                checked={checked}
                className="h-4 w-4 accent-[var(--brand-teal)]"
                type="checkbox"
                onChange={() => onToggle(option.value)}
              />
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

export function PreferencesForm({
  autismMode,
  language,
  preferences,
  onAutismModeChange,
  onLanguageChange,
  onPreferencesChange,
}: PreferencesFormProps) {
  const toggleArrayValue = (key: "sensory" | "processing" | "support", option: string) => {
    const current = preferences[key];
    const nextValues = current.includes(option)
      ? current.filter((value) => value !== option)
      : [...current, option];

    onPreferencesChange({
      ...preferences,
      [key]: nextValues,
    });
  };

  return (
    <section className="space-y-6 rounded-[32px] border border-[color:var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-medium)] backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.26em] text-[var(--brand-teal-deep)]">Preferences</p>
          <h2 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Autism Mode Preferences</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
            Tune the summary tone and accommodation card before analysis.
          </p>
        </div>
        <label className="flex items-center gap-3 rounded-full border border-[color:var(--border-strong)] bg-[var(--surface-muted)] px-4 py-2 text-sm font-medium text-[var(--text-primary)]">
          <input
            checked={autismMode}
            className="h-4 w-4 accent-[var(--brand-teal)]"
            type="checkbox"
            onChange={(event) => onAutismModeChange(event.target.checked)}
          />
          Autism Mode
        </label>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-2">
          <span className="text-sm font-semibold text-[var(--text-secondary)]">Communication style</span>
          <select
            className="w-full rounded-2xl border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none ring-0 transition focus:border-[color:var(--border-strong)]"
            value={preferences.communication_style}
            onChange={(event) =>
              onPreferencesChange({
                ...preferences,
                communication_style: event.target.value as Preferences["communication_style"],
              })
            }
          >
            <option value="Direct">Direct</option>
            <option value="Friendly">Friendly</option>
            <option value="Very explicit">Very explicit</option>
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-semibold text-[var(--text-secondary)]">Language mode</span>
          <select
            className="w-full rounded-2xl border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-3 text-sm text-[var(--text-primary)] outline-none ring-0 transition focus:border-[color:var(--border-strong)]"
            value={language}
            onChange={(event) => onLanguageChange(event.target.value as LanguageOption)}
          >
            <option value="en">English</option>
            <option value="multi">Multi-language</option>
          </select>
        </label>
      </div>

      <CheckboxGrid
        label="Sensory supports"
        options={sensoryOptions}
        values={preferences.sensory}
        onToggle={(value) => toggleArrayValue("sensory", value)}
      />
      <CheckboxGrid
        label="Processing supports"
        options={processingOptions}
        values={preferences.processing}
        onToggle={(value) => toggleArrayValue("processing", value)}
      />
      <CheckboxGrid
        label="Support options"
        options={supportOptions}
        values={preferences.support}
        onToggle={(value) => toggleArrayValue("support", value)}
      />
    </section>
  );
}
