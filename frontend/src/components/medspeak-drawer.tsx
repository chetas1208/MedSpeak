"use client";

import { startTransition, useEffect, useEffectEvent, useMemo, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { getChatHistory, getChatStreamUrl, startChat, startRealtimeChatMessage } from "@/lib/api";
import type { ChatHistoryItem, ChatStreamEvent, ChatUIContext, JobStatus } from "@/lib/types";

const sourceTone: Record<string, string> = {
  current_transcript: "border-[color:var(--border-strong)] bg-[var(--surface-muted)] text-[var(--text-primary)]",
  current_result: "border-[color:var(--border)] bg-[var(--surface-gold)] text-[var(--text-primary)]",
  prior_visit: "border-[color:var(--border)] bg-[var(--surface-soft)] text-[var(--text-secondary)]",
  site_context: "border-[color:var(--border)] bg-[var(--surface-strong)] text-[var(--text-secondary)]",
};

type MedSpeakDrawerProps = {
  autismMode: boolean;
  jobId: string | null;
  jobStatus: JobStatus | null;
  mode: "audio" | "demo";
  statusMessage: string;
  hasAudioReady: boolean;
  activeResultTab: string | null;
};

const chatSessionStorageKey = "medspeak-chat-session-id";

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

function buildUiContext({
  mode,
  statusMessage,
  hasAudioReady,
  jobStatus,
  activeResultTab,
}: Omit<MedSpeakDrawerProps, "autismMode" | "jobId">): ChatUIContext {
  return {
    page: "home",
    session_mode: mode,
    status_message: statusMessage,
    has_audio_ready: hasAudioReady,
    job_status: jobStatus,
    active_result_tab: activeResultTab,
  };
}

function createOptimisticUserMessage(content: string): ChatHistoryItem {
  const now = new Date().toISOString();
  return {
    message_id: -Date.now(),
    role: "user",
    content,
    created_at: now,
    updated_at: now,
    status: "final",
    used_sources: [],
    follow_up_suggestions: [],
    safety_flag: false,
    delivery_note: null,
  };
}

function createAssistantDraftMessage(
  response: Awaited<ReturnType<typeof startRealtimeChatMessage>>,
): ChatHistoryItem {
  const now = new Date().toISOString();
  return {
    message_id: response.assistant_message_id,
    role: "assistant",
    content: response.answer,
    created_at: now,
    updated_at: now,
    status: response.status,
    used_sources: response.used_sources,
    follow_up_suggestions: response.follow_up_suggestions,
    safety_flag: response.safety_flag,
    delivery_note: response.delivery_note ?? null,
  };
}

function upsertMessage(messages: ChatHistoryItem[], nextMessage: ChatHistoryItem): ChatHistoryItem[] {
  const index = messages.findIndex((item) => item.message_id === nextMessage.message_id);
  if (index === -1) {
    return [...messages, nextMessage];
  }
  const updated = [...messages];
  updated[index] = {
    ...updated[index],
    ...nextMessage,
  };
  return updated;
}

function statusPillTone(status: ChatHistoryItem["status"]): string {
  if (status === "draft") {
    return "border-[color:var(--border-strong)] bg-[var(--surface-muted)] text-[var(--brand-teal-deep)]";
  }
  if (status === "refining") {
    return "border-amber-200 bg-amber-50 text-amber-800";
  }
  if (status === "failed") {
    return "border-rose-200 bg-rose-50 text-rose-700";
  }
  return "border-[color:var(--border)] bg-[var(--surface-soft)] text-[var(--text-secondary)]";
}

export function MedSpeakDrawer({
  autismMode,
  jobId,
  jobStatus,
  mode,
  statusMessage,
  hasAudioReady,
  activeResultTab,
}: MedSpeakDrawerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [chatSessionId, setChatSessionId] = useState<string | null>(() => {
    if (typeof window === "undefined") {
      return null;
    }
    return window.sessionStorage.getItem(chatSessionStorageKey);
  });
  const [messages, setMessages] = useState<ChatHistoryItem[]>([]);
  const [draft, setDraft] = useState("");
  const [includePriorVisits, setIncludePriorVisits] = useState(true);
  const [isBooting, setIsBooting] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bootVersion, setBootVersion] = useState(0);
  const [pollFallback, setPollFallback] = useState(false);
  const [streamVersion, setStreamVersion] = useState(0);

  const uiContext = useMemo(
    () =>
      buildUiContext({
        mode,
        statusMessage,
        hasAudioReady,
        jobStatus,
        activeResultTab,
      }),
    [activeResultTab, hasAudioReady, jobStatus, mode, statusMessage],
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const hasAutoOpened = window.sessionStorage.getItem("medspeak-chat-opened");
    if (!hasAutoOpened && window.innerWidth >= 1280) {
      setIsOpen(true);
      window.sessionStorage.setItem("medspeak-chat-opened", "1");
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (chatSessionId) {
      window.sessionStorage.setItem(chatSessionStorageKey, chatSessionId);
      return;
    }
    window.sessionStorage.removeItem(chatSessionStorageKey);
  }, [chatSessionId]);

  const syncHistory = useEffectEvent(async (sessionId: string) => {
    try {
      const history = await getChatHistory(sessionId);
      startTransition(() => {
        setMessages(history.messages);
      });
      setError(null);
    } catch (historyError) {
      const message = formatError(historyError);
      if (message.includes("Chat session not found")) {
        if (typeof window !== "undefined") {
          window.sessionStorage.removeItem(chatSessionStorageKey);
        }
        startTransition(() => {
          setChatSessionId(null);
          setMessages([]);
        });
        setBootVersion((current) => current + 1);
        return;
      }
      setError(message);
    }
  });

  const applyStreamEvent = useEffectEvent((streamEvent: ChatStreamEvent) => {
    const now = new Date().toISOString();
    const nextMessage: ChatHistoryItem = {
      message_id: streamEvent.message_id,
      role: "assistant",
      content: streamEvent.answer,
      created_at: now,
      updated_at: now,
      status: streamEvent.status,
      used_sources: streamEvent.used_sources,
      follow_up_suggestions: streamEvent.follow_up_suggestions,
      safety_flag: streamEvent.safety_flag,
      delivery_note: streamEvent.delivery_note ?? null,
    };
    startTransition(() => {
      setMessages((current) => upsertMessage(current, nextMessage));
    });
    if (streamEvent.type === "message_failed" || streamEvent.type === "message_finalized") {
      void syncHistory(streamEvent.chat_session_id);
    }
  });

  useEffect(() => {
    if (chatSessionId) {
      return;
    }

    let cancelled = false;
    setIsBooting(true);
    setError(null);

    const boot = async () => {
      try {
        const started = await startChat(jobId ? { job_id: jobId } : {});
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setChatSessionId(started.chat_session_id);
          setMessages([]);
        });
      } catch (bootError) {
        if (!cancelled) {
          setError(formatError(bootError));
        }
      } finally {
        if (!cancelled) {
          setIsBooting(false);
        }
      }
    };

    void boot();
    return () => {
      cancelled = true;
    };
  }, [bootVersion, chatSessionId, jobId]);

  useEffect(() => {
    if (!chatSessionId) {
      return;
    }
    void syncHistory(chatSessionId);
  }, [chatSessionId]);

  useEffect(() => {
    if (!chatSessionId) {
      return;
    }

    let retryTimer: number | null = null;
    const stream = new EventSource(getChatStreamUrl(chatSessionId));
    const handleEvent = (rawEvent: Event) => {
      const messageEvent = rawEvent as MessageEvent<string>;
      try {
        const payload = JSON.parse(messageEvent.data) as ChatStreamEvent;
        setPollFallback(false);
        applyStreamEvent(payload);
      } catch (streamError) {
        console.error("Failed to parse MedSpeak chat stream event.", streamError);
      }
    };

    const eventNames: ChatStreamEvent["type"][] = [
      "draft_created",
      "message_updated",
      "message_finalized",
      "message_failed",
    ];
    for (const eventName of eventNames) {
      stream.addEventListener(eventName, handleEvent);
    }
    stream.onopen = () => {
      setPollFallback(false);
    };
    stream.onerror = () => {
      stream.close();
      setPollFallback(true);
      retryTimer = window.setTimeout(() => {
        setStreamVersion((current) => current + 1);
      }, 2500);
    };

    return () => {
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      for (const eventName of eventNames) {
        stream.removeEventListener(eventName, handleEvent);
      }
      stream.close();
    };
  }, [chatSessionId, streamVersion]);

  const hasPendingAssistantMessage = messages.some(
    (message) => message.role === "assistant" && message.status !== "final" && message.status !== "failed",
  );

  useEffect(() => {
    if (!pollFallback || !chatSessionId) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void syncHistory(chatSessionId);
    }, hasPendingAssistantMessage ? 1500 : 2500);
    return () => {
      window.clearInterval(intervalId);
    };
  }, [chatSessionId, hasPendingAssistantMessage, pollFallback]);

  const canInteract = Boolean(chatSessionId) && !isBooting;
  const inputPlaceholder = !chatSessionId
    ? error
      ? "MedSpeak could not connect. Use Retry chat to reconnect."
      : "Connecting to MedSpeak..."
    : jobId
      ? "Ask what happened, how to explain it simply, or what changed since a prior visit."
      : "Ask how the workflow works, what the status means, or how to upload and analyze a visit.";

  const submitMessage = async (message: string) => {
    if (!chatSessionId || !message.trim() || isSending) {
      return;
    }

    const trimmed = message.trim();
    const optimisticUserMessage = createOptimisticUserMessage(trimmed);

    startTransition(() => {
      setMessages((current) => [...current, optimisticUserMessage]);
      setDraft("");
    });
    setIsSending(true);
    setError(null);

    try {
      const response = await startRealtimeChatMessage({
        chat_session_id: chatSessionId,
        job_id: jobId,
        message: trimmed,
        autism_mode: autismMode,
        include_prior_visits: includePriorVisits,
        ui_context: uiContext,
      });
      const assistantMessage = createAssistantDraftMessage(response);
      startTransition(() => {
        setMessages((current) => [...current, assistantMessage]);
      });
      void syncHistory(chatSessionId);
    } catch (sendError) {
      setError(formatError(sendError));
      startTransition(() => {
        setMessages((current) => current.filter((item) => item.message_id !== optimisticUserMessage.message_id));
      });
    } finally {
      setIsSending(false);
    }
  };

  return (
    <>
      <button
        aria-controls="medspeak-chat"
        aria-expanded={isOpen}
        aria-label="Open MedSpeak chat"
        className="fixed bottom-5 right-5 z-40 inline-flex h-[76px] w-[76px] items-center justify-center rounded-full border border-[color:var(--border-strong)] bg-[var(--surface)] p-2 shadow-[var(--shadow-strong)] transition hover:-translate-y-1 hover:shadow-[var(--shadow-strong)]"
        onClick={() => setIsOpen((current) => !current)}
        title="Ask MedSpeak"
        type="button"
      >
        <span className="sr-only">Open MedSpeak chat</span>
        <BrandMark alt="MedSpeak chat" size={58} />
      </button>

      <aside
        aria-hidden={!isOpen}
        className={`fixed inset-y-0 right-0 z-50 flex w-full max-w-[460px] flex-col border-l border-[color:var(--border)] bg-[linear-gradient(180deg,var(--background-strong),var(--background))] shadow-[-28px_0_80px_rgba(0,0,0,0.18)] transition-transform duration-300 sm:w-[460px] ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
        id="medspeak-chat"
      >
        <div className="border-b border-[color:var(--border)] px-5 py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <BrandMark alt="MedSpeak logo" size={58} />
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--brand-teal-deep)]">Ask MedSpeak</p>
                <h2 className="mt-2 text-xl font-semibold text-[var(--text-primary)]">Grounded help from the start</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                  I can explain your visit, organize next steps, and help with this website. I answer only from the visit record and the visible app context.
                </p>
              </div>
            </div>
            <button
              className="rounded-full border border-[color:var(--border)] bg-[var(--surface-strong)] px-3 py-2 text-sm text-[var(--text-secondary)] transition hover:bg-[var(--surface-soft)]"
              onClick={() => setIsOpen(false)}
              type="button"
            >
              Close
            </button>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <span className="rounded-full border border-[color:var(--border-strong)] bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-semibold text-[var(--brand-teal-deep)]">
              {jobId ? `Visit attached${jobStatus ? `: ${jobStatus}` : ""}` : "Website context active"}
            </span>
            <span className="rounded-full border border-[color:var(--border)] bg-[var(--surface-gold)] px-3 py-1.5 text-xs font-semibold text-[#8a6a1d]">
              {mode === "audio" ? "Audio workflow" : "Demo transcript"}
            </span>
          </div>

          <label className="mt-4 flex items-center gap-3 text-sm text-[var(--text-secondary)]">
            <input
              checked={includePriorVisits}
              className="h-4 w-4 rounded border-slate-300 text-[var(--brand-teal)] focus:ring-[var(--brand-teal)]"
              onChange={(event) => setIncludePriorVisits(event.target.checked)}
              type="checkbox"
            />
            Use prior visits for context
          </label>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {isBooting ? (
            <div className="rounded-[28px] border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-4 text-sm text-[var(--text-secondary)]">
              Loading MedSpeak.
            </div>
          ) : null}

          {error ? (
            <div className="rounded-[28px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span>{error}</span>
                {!chatSessionId ? (
                  <button
                    className="rounded-full border border-rose-300 bg-white px-3 py-1.5 text-xs font-semibold text-rose-700 transition hover:bg-rose-100"
                    onClick={() => {
                      setError(null);
                      setBootVersion((current) => current + 1);
                    }}
                    type="button"
                  >
                    Retry chat
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}

          {messages.length === 0 ? (
            <article className="rounded-[30px] border border-dashed border-[color:var(--border-strong)] bg-[var(--surface-strong)] px-5 py-5">
              <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[var(--brand-teal-deep)]">Welcome</p>
              <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">
                Ask how the workflow works now. Once a transcript exists, ask what happened in the visit, what the medication instructions were, or how to turn the visit into clear next steps.
              </p>
            </article>
          ) : null}

          {messages.map((message, index) => (
            <article
              key={message.message_id ?? `${message.role}-${index}-${message.created_at}`}
              className={`rounded-[30px] border px-4 py-4 ${
                message.role === "assistant"
                  ? "border-[color:var(--border)] bg-[var(--surface-strong)] text-[var(--text-primary)] shadow-[var(--shadow-soft)]"
                  : "ml-8 border-transparent bg-[linear-gradient(135deg,var(--surface-contrast),#215264)] text-white shadow-[var(--shadow-medium)]"
              }`}
            >
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em]">
                    {message.role === "assistant" ? "MedSpeak" : "You"}
                  </p>
                  {message.role === "assistant" ? (
                    <span className={`rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${statusPillTone(message.status)}`}>
                      {message.status}
                    </span>
                  ) : null}
                </div>
                <p className={`text-xs ${message.role === "assistant" ? "text-[var(--text-tertiary)]" : "text-white/70"}`}>
                  {new Date(message.updated_at ?? message.created_at).toLocaleTimeString()}
                </p>
              </div>
              <p className="mt-3 whitespace-pre-line text-sm leading-7">{message.content}</p>

              {message.delivery_note ? (
                <div className="mt-4 rounded-2xl border border-[color:var(--border)] bg-[var(--surface-soft)] px-3 py-3 text-xs leading-6 text-[var(--text-secondary)]">
                  {message.delivery_note}
                </div>
              ) : null}

              {message.safety_flag ? (
                <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs leading-6 text-amber-900">
                  This answer stayed limited to the visit record and the app context. Ask your clinician for advice beyond that record.
                </div>
              ) : null}

              {message.used_sources.length > 0 ? (
                <div className="mt-4 space-y-2">
                  {message.used_sources.map((source) => (
                    <details
                      key={`${source.visit_id}-${source.chunk_id}`}
                      className={`rounded-2xl border px-3 py-3 text-xs ${sourceTone[source.source_type] ?? sourceTone.site_context}`}
                    >
                      <summary className="cursor-pointer font-semibold">
                        Evidence: {source.source_type.replaceAll("_", " ")}
                      </summary>
                      <p className="mt-2 whitespace-pre-line leading-6">{source.quote}</p>
                    </details>
                  ))}
                </div>
              ) : null}

              {message.follow_up_suggestions.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {message.follow_up_suggestions.map((suggestion) => (
                    <button
                      key={`${message.created_at}-${suggestion}`}
                      className="rounded-full border border-[color:var(--border)] bg-[var(--surface-soft)] px-3 py-2 text-xs font-semibold text-[var(--text-secondary)] transition hover:border-[color:var(--border-strong)] hover:bg-[var(--surface-muted)]"
                      onClick={() => void submitMessage(suggestion)}
                      type="button"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}
            </article>
          ))}
        </div>

        <form
          className="border-t border-[color:var(--border)] bg-[var(--surface)] px-5 py-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submitMessage(draft);
          }}
        >
          <label className="sr-only" htmlFor="medspeak-chat-input">
            Message MedSpeak
          </label>
          <textarea
            id="medspeak-chat-input"
            className="min-h-28 w-full rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-3 text-sm leading-6 text-[var(--text-primary)] outline-none transition focus:border-[color:var(--border-strong)]"
            disabled={!canInteract}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submitMessage(draft);
              }
            }}
            placeholder={inputPlaceholder}
            value={draft}
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-xs leading-5 text-[var(--text-tertiary)]">
              {jobId
                ? "Visit-aware answers use the transcript, structured result, prior visits, and website context."
                : "Right now I can help with the workflow and visible app context. Visit answers appear after data exists."}
            </p>
            <button
              className="inline-flex min-h-11 items-center justify-center rounded-full bg-[linear-gradient(135deg,var(--brand-teal),#1d6d74)] px-5 py-3 text-sm font-semibold text-white shadow-[var(--shadow-medium)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-55"
              disabled={!chatSessionId || isSending || isBooting || !draft.trim()}
              type="submit"
            >
              {isSending ? "Starting..." : "Send"}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}
