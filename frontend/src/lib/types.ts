export type CommunicationStyle = "Direct" | "Friendly" | "Very explicit";
export type LanguageOption = "en" | "multi";
export type JobStatus =
  | "QUEUED"
  | "NORMALIZE_AUDIO"
  | "TRANSCRIBE"
  | "REDACT"
  | "ANALYZE"
  | "VERIFY"
  | "INDEX"
  | "RENDER_PDF"
  | "READY"
  | "FAILED";

export type Preferences = {
  communication_style: CommunicationStyle;
  sensory: string[];
  processing: string[];
  support: string[];
};

export type AnalyzeRequestBase = {
  autism_mode: boolean;
  preferences: Preferences;
  language: LanguageOption;
};

export type AnalyzeFromTranscriptPayload = AnalyzeRequestBase & {
  transcript: string;
};

export type AnalyzeFromAudioPayload = AnalyzeRequestBase;

export type IntentTimelineSegment = {
  start: string;
  end: string;
  speaker: string;
  text: string;
  intents: string[];
  confidence: number;
};

export type ChecklistItem = {
  step: string;
  who: string;
  when: string;
};

export type MedicationItem = {
  name: string;
  dose: string;
  frequency: string;
  purpose: string;
  notes: string;
};

export type TestReferralItem = {
  item: string;
  purpose: string;
  when: string;
};

export type AccommodationCard = {
  summary: string;
  communication: string[];
  sensory: string[];
  processing: string[];
  support: string[];
};

export type SocialScriptItem = {
  situation: string;
  script: string;
};

export type AnalysisResult = {
  standard_summary: string;
  autism_friendly_summary: string;
  intent_summary: string[];
  intent_timeline: IntentTimelineSegment[];
  next_steps_checklist: ChecklistItem[];
  medications: MedicationItem[];
  tests_and_referrals: TestReferralItem[];
  red_flags: string[];
  questions_to_ask: string[];
  accommodation_card: AccommodationCard;
  social_scripts: SocialScriptItem[];
  uncertainties: string[];
  safety_note: string;
};

export type JobEnqueueResponse = {
  job_id: string;
  status: JobStatus;
};

export type JobResponse = {
  job_id: string;
  status: JobStatus;
  progress: number;
  stage_times: Record<string, string>;
  error: string | null;
  transcript_redacted: string | null;
  result_json: AnalysisResult | null;
  pdf_path_or_url: string | null;
};

export type HealthResponse = {
  status: string;
  ffmpeg_available: boolean;
  use_qdrant: boolean;
  worker_running: boolean;
};

export type ChatSourceType = "current_transcript" | "current_result" | "prior_visit" | "site_context";
export type ChatMessageStatus = "draft" | "refining" | "final" | "failed";

export type ChatUsedSource = {
  source_type: ChatSourceType;
  chunk_id: string;
  visit_id: string;
  quote: string;
};

export type ChatStartResponse = {
  chat_session_id: string;
};

export type ChatUIContext = {
  page: string;
  session_mode: "audio" | "demo";
  status_message: string;
  has_audio_ready: boolean;
  job_status: JobStatus | null;
  active_result_tab: string | null;
};

export type ChatStartPayload = {
  job_id?: string | null;
};

export type ChatMessagePayload = {
  chat_session_id: string;
  job_id?: string | null;
  message: string;
  autism_mode: boolean;
  include_prior_visits: boolean;
  ui_context: ChatUIContext;
};

export type ChatMessageResponse = {
  answer: string;
  used_sources: ChatUsedSource[];
  follow_up_suggestions: string[];
  safety_flag: boolean;
  delivery_note?: string | null;
};

export type ChatMessageStartResponse = {
  assistant_message_id: number;
  status: ChatMessageStatus;
  answer: string;
  used_sources: ChatUsedSource[];
  follow_up_suggestions: string[];
  safety_flag: boolean;
  delivery_note?: string | null;
};

export type ChatHistoryItem = {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  updated_at: string;
  status: ChatMessageStatus;
  used_sources: ChatUsedSource[];
  follow_up_suggestions: string[];
  safety_flag: boolean;
  delivery_note?: string | null;
};

export type ChatHistoryResponse = {
  chat_session_id: string;
  job_id: string | null;
  messages: ChatHistoryItem[];
};

export type ChatStreamEvent = {
  type: "draft_created" | "message_updated" | "message_finalized" | "message_failed";
  chat_session_id: string;
  message_id: number;
  status: ChatMessageStatus;
  answer: string;
  used_sources: ChatUsedSource[];
  follow_up_suggestions: string[];
  safety_flag: boolean;
  delivery_note?: string | null;
};
