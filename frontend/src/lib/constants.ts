import type { JobStatus, Preferences } from "@/lib/types";

export const sensoryOptions = [
  { value: "dim_lights", label: "Dim lights" },
  { value: "quiet_room", label: "Quiet room" },
  { value: "explain_touch", label: "Explain before touch" },
  { value: "short_waiting", label: "Short waiting time" },
] as const;

export const processingOptions = [
  { value: "extra_time", label: "Extra processing time" },
  { value: "written_steps", label: "Written next steps" },
  { value: "confirm_understanding", label: "Confirm understanding" },
] as const;

export const supportOptions = [
  { value: "caregiver_allowed", label: "Caregiver allowed" },
  { value: "breaks_allowed", label: "Breaks allowed" },
] as const;

export const defaultPreferences: Preferences = {
  communication_style: "Very explicit",
  sensory: ["quiet_room", "explain_touch"],
  processing: ["extra_time", "written_steps", "confirm_understanding"],
  support: ["caregiver_allowed", "breaks_allowed"],
};

export const demoTranscriptPath = "/demo-transcript.txt";

export const jobStageOrder: JobStatus[] = [
  "QUEUED",
  "NORMALIZE_AUDIO",
  "TRANSCRIBE",
  "REDACT",
  "ANALYZE",
  "VERIFY",
  "INDEX",
  "RENDER_PDF",
  "READY",
];

export const jobStageLabels: Record<JobStatus, string> = {
  QUEUED: "Queued",
  NORMALIZE_AUDIO: "Normalizing Audio",
  TRANSCRIBE: "Transcribing",
  REDACT: "Redacting",
  ANALYZE: "Analyzing",
  VERIFY: "Verifying",
  INDEX: "Indexing",
  RENDER_PDF: "Rendering PDF",
  READY: "Ready",
  FAILED: "Failed",
};
