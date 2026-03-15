import type {
  AnalyzeFromAudioPayload,
  AnalyzeFromTranscriptPayload,
  ChatHistoryResponse,
  ChatMessagePayload,
  ChatMessageResponse,
  ChatMessageStartResponse,
  ChatStartPayload,
  ChatStartResponse,
  HealthResponse,
  JobEnqueueResponse,
  JobResponse,
} from "@/lib/types";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const defaultTimeoutMs = 20000;
const chatTimeoutMs = 90000;

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit = {}, timeoutMs = defaultTimeoutMs): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The request timed out. Please try again.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function parseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string | { message?: string } };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (payload.detail && typeof payload.detail.message === "string") {
      return payload.detail.message;
    }
  } catch {
    return `Request failed with status ${response.status}.`;
  }
  return `Request failed with status ${response.status}.`;
}

async function getJson<TResponse>(path: string): Promise<TResponse> {
  const response = await fetchWithTimeout(`${apiBaseUrl}${path}`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return (await response.json()) as TResponse;
}

async function postJson<TPayload, TResponse>(path: string, payload: TPayload, timeoutMs = defaultTimeoutMs): Promise<TResponse> {
  const response = await fetchWithTimeout(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  }, timeoutMs);

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return (await response.json()) as TResponse;
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/api/health");
}

export function getJob(jobId: string): Promise<JobResponse> {
  return getJson<JobResponse>(`/api/job/${jobId}`);
}

export function analyzeTranscript(payload: AnalyzeFromTranscriptPayload): Promise<JobEnqueueResponse> {
  return postJson<AnalyzeFromTranscriptPayload, JobEnqueueResponse>("/api/analyze_from_transcript", payload);
}

export async function analyzeFromAudio(
  payload: AnalyzeFromAudioPayload,
  file: File,
): Promise<JobEnqueueResponse> {
  const formData = new FormData();
  formData.append("audio", file);
  formData.append("payload", JSON.stringify(payload));

  const response = await fetchWithTimeout(
    `${apiBaseUrl}/api/analyze_from_audio`,
    {
    method: "POST",
    body: formData,
    },
    60000,
  );

  if (!response.ok) {
    throw new Error(await parseError(response));
  }

  return (await response.json()) as JobEnqueueResponse;
}

export function startChat(payload: ChatStartPayload = {}): Promise<ChatStartResponse> {
  return postJson<ChatStartPayload, ChatStartResponse>("/api/chat/start", payload, chatTimeoutMs);
}

export function sendChatMessage(payload: ChatMessagePayload): Promise<ChatMessageResponse> {
  return postJson<ChatMessagePayload, ChatMessageResponse>("/api/chat/message", payload, chatTimeoutMs);
}

export function startRealtimeChatMessage(payload: ChatMessagePayload): Promise<ChatMessageStartResponse> {
  return postJson<ChatMessagePayload, ChatMessageStartResponse>("/api/chat/message/start", payload, defaultTimeoutMs);
}

export function getChatHistory(chatSessionId: string): Promise<ChatHistoryResponse> {
  return getJson<ChatHistoryResponse>(`/api/chat/history/${chatSessionId}`);
}

export function getChatStreamUrl(chatSessionId: string): string {
  return `${apiBaseUrl}/api/chat/stream/${chatSessionId}`;
}
