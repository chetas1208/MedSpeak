"use client";

import { startTransition, useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { MedSpeakDrawer } from "@/components/medspeak-drawer";
import { PreferencesForm } from "@/components/preferences-form";
import { type ResultTabKey, ResultsTabs } from "@/components/results-tabs";
import { ThemeToggle } from "@/components/theme-toggle";
import { analyzeFromAudio, analyzeTranscript, getHealth, getJob } from "@/lib/api";
import { defaultPreferences, demoTranscriptPath, jobStageLabels, jobStageOrder } from "@/lib/constants";
import type { HealthResponse, JobResponse, JobStatus, LanguageOption, Preferences } from "@/lib/types";

type Mode = "audio" | "demo";

function formatErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

function createQueuedJob(jobId: string, status: JobStatus): JobResponse {
  return {
    job_id: jobId,
    status,
    progress: 5,
    stage_times: { QUEUED: new Date().toISOString() },
    error: null,
    transcript_redacted: null,
    result_json: null,
    pdf_path_or_url: null,
  };
}

function GitHubIcon() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.477 2 2 6.589 2 12.248c0 4.526 2.865 8.365 6.839 9.72.5.094.682-.223.682-.495 0-.244-.008-.889-.013-1.745-2.782.62-3.369-1.375-3.369-1.375-.455-1.188-1.11-1.504-1.11-1.504-.908-.637.069-.624.069-.624 1.004.072 1.532 1.056 1.532 1.056.893 1.565 2.341 1.113 2.91.851.091-.664.35-1.114.636-1.37-2.221-.26-4.556-1.14-4.556-5.075 0-1.121.39-2.038 1.03-2.757-.102-.261-.447-1.312.098-2.736 0 0 .84-.277 2.75 1.053A9.37 9.37 0 0 1 12 6.878c.85.004 1.706.117 2.505.344 1.908-1.33 2.747-1.053 2.747-1.053.547 1.424.202 2.475.1 2.736.64.719 1.028 1.636 1.028 2.757 0 3.946-2.339 4.811-4.567 5.067.359.319.679.948.679 1.912 0 1.379-.012 2.491-.012 2.831 0 .275.18.594.688.493C19.138 20.61 22 16.772 22 12.248 22 6.589 17.523 2 12 2Z" />
    </svg>
  );
}

function StatusRail({ job }: { job: JobResponse | null }) {
  const currentStatus = job?.status ?? "QUEUED";
  const currentIndex = jobStageOrder.indexOf(currentStatus === "FAILED" ? "RENDER_PDF" : currentStatus);

  return (
    <section className="space-y-5 rounded-[30px] border border-[color:var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-medium)] backdrop-blur">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--brand-teal-deep)]">Pipeline</p>
          <h2 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Job Progress</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
            {job ? `Job ${job.job_id} is ${jobStageLabels[job.status]}.` : "No job queued yet."}
          </p>
        </div>
        {job ? (
          <div className="rounded-full border border-[color:var(--border-strong)] bg-[var(--surface-muted)] px-4 py-2 text-sm font-semibold text-[var(--text-primary)]">
            {job.progress}%
          </div>
        ) : null}
      </div>

      <div className="h-3 overflow-hidden rounded-full bg-[var(--surface-soft)]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            job?.status === "FAILED"
              ? "bg-[linear-gradient(90deg,#ef4444,#f97316)]"
              : "bg-[linear-gradient(90deg,var(--brand-teal),var(--brand-gold))]"
          }`}
          style={{ width: `${job?.progress ?? 0}%` }}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {jobStageOrder.map((stage, index) => {
          const isComplete = job ? currentIndex > index || job.status === "READY" : false;
          const isCurrent = job?.status === stage;
          return (
            <article
              key={stage}
              className={`rounded-[22px] border px-4 py-4 text-sm transition ${
                isCurrent
                  ? "border-[color:var(--border-strong)] bg-[var(--surface-muted)] text-[var(--text-primary)]"
                  : isComplete
                    ? "border-[color:var(--border)] bg-[var(--surface-strong)] text-[var(--text-secondary)]"
                    : "border-[color:var(--border)] bg-[var(--surface-soft)] text-[var(--text-tertiary)]"
              }`}
            >
              <p className="text-xs font-semibold uppercase tracking-[0.18em]">{jobStageLabels[stage]}</p>
              <p className="mt-2 text-sm">
                {job?.stage_times[stage] ? new Date(job.stage_times[stage]).toLocaleTimeString() : "Waiting"}
              </p>
            </article>
          );
        })}
      </div>

      {job?.error ? (
        <div className="rounded-[22px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-800">
          {job.error}
        </div>
      ) : null}
    </section>
  );
}

export function AppShell() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const [mode, setMode] = useState<Mode>("audio");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [preferences, setPreferences] = useState<Preferences>(defaultPreferences);
  const [autismMode, setAutismMode] = useState(true);
  const [language, setLanguage] = useState<LanguageOption>("en");
  const [demoTranscript, setDemoTranscript] = useState("");
  const [localAudioFile, setLocalAudioFile] = useState<File | null>(null);
  const [localAudioUrl, setLocalAudioUrl] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState("Checking backend health and preparing MedSpeak.");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [activeResultTab, setActiveResultTab] = useState<ResultTabKey>("summary");

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadHealth = async () => {
      try {
        const nextHealth = await getHealth();
        if (cancelled) {
          return;
        }
        setHealth(nextHealth);
        setStatusMessage("Ready to record locally, upload audio, or load the demo transcript.");
      } catch (healthError) {
        if (cancelled) {
          return;
        }
        setError(formatErrorMessage(healthError));
        setStatusMessage("Backend health check failed. You can still prepare input, but analysis will not run.");
      }
    };

    void loadHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!jobId) {
      return;
    }

    let cancelled = false;
    let timeoutId: number | null = null;

    const poll = async () => {
      try {
        const nextJob = await getJob(jobId);
        if (cancelled) {
          return;
        }
        startTransition(() => setJob(nextJob));

        if (nextJob.status === "READY") {
          setStatusMessage("Analysis complete. Review the report or ask MedSpeak follow-up questions.");
          return;
        }
        if (nextJob.status === "FAILED") {
          setError(nextJob.error ?? "Analysis failed.");
          setStatusMessage("Analysis failed.");
          return;
        }
      } catch (pollError) {
        if (cancelled) {
          return;
        }
        setError(formatErrorMessage(pollError));
        setStatusMessage("Polling failed.");
        return;
      }

      timeoutId = window.setTimeout(poll, 1400);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [jobId]);

  useEffect(() => {
    return () => {
      if (localAudioUrl) {
        URL.revokeObjectURL(localAudioUrl);
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
      }
    };
  }, [localAudioUrl]);

  const hasPreparedInput = mode === "demo" ? demoTranscript.trim().length > 0 : Boolean(localAudioFile);
  const canAnalyze = !isSubmitting && !isRecording && hasPreparedInput;

  const resetArtifacts = () => {
    setJob(null);
    setJobId(null);
    setActiveResultTab("summary");
    setError(null);
  };

  const replaceAudioFile = (file: File) => {
    if (localAudioUrl) {
      URL.revokeObjectURL(localAudioUrl);
    }
    const nextUrl = URL.createObjectURL(file);
    setLocalAudioFile(file);
    setLocalAudioUrl(nextUrl);
  };

  const handleAudioPicked = (file: File | null) => {
    if (!file) {
      return;
    }
    resetArtifacts();
    replaceAudioFile(file);
    setStatusMessage(`Loaded ${file.name}. Analyze when you are ready.`);
  };

  const startRecording = async () => {
    resetArtifacts();
    setStatusMessage("Starting local microphone capture.");
    setError(null);

    if (!("MediaRecorder" in window)) {
      setError("This browser does not support MediaRecorder.");
      setStatusMessage("Unable to start recording.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        if (blob.size > 0) {
          const file = new File([blob], `medspeak-${Date.now()}.webm`, {
            type: blob.type || "audio/webm",
          });
          replaceAudioFile(file);
        }
        setStatusMessage("Recording stopped. Review the audio, then analyze when ready.");
      };

      recorder.start(250);
      setIsRecording(true);
      setStatusMessage("Recording locally. Press Stop Recording when the visit discussion is finished.");
    } catch (recordingError) {
      setError(formatErrorMessage(recordingError));
      setStatusMessage("Unable to start recording.");
    }
  };

  const stopRecording = () => {
    try {
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    } catch (stopError) {
      setError(formatErrorMessage(stopError));
      setStatusMessage("Unable to stop recording cleanly.");
    } finally {
      setIsRecording(false);
    }
  };

  const loadDemoTranscript = async () => {
    try {
      const response = await fetch(demoTranscriptPath, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("Could not load the bundled demo transcript.");
      }
      setDemoTranscript(await response.text());
      setStatusMessage("Demo transcript loaded. Analyze it when you are ready.");
    } catch (loadError) {
      setError(formatErrorMessage(loadError));
    }
  };

  const runAnalysis = async () => {
    setError(null);
    setIsSubmitting(true);
    setJob(null);
    setJobId(null);
    setActiveResultTab("summary");

    try {
      if (mode === "demo") {
        const nextJob = await analyzeTranscript({
          transcript: demoTranscript.trim(),
          autism_mode: autismMode,
          preferences,
          language,
        });
        setJob(createQueuedJob(nextJob.job_id, nextJob.status));
        setJobId(nextJob.job_id);
        setStatusMessage("Demo transcript queued. Polling worker progress now.");
      } else if (localAudioFile) {
        const nextJob = await analyzeFromAudio(
          {
            autism_mode: autismMode,
            preferences,
            language,
          },
          localAudioFile,
        );
        setJob(createQueuedJob(nextJob.job_id, nextJob.status));
        setJobId(nextJob.job_id);
        setStatusMessage("Audio queued. Polling worker progress now.");
      } else {
        throw new Error("No audio is ready yet. Record in the browser, upload a file, or load the demo transcript.");
      }
    } catch (analysisError) {
      setError(formatErrorMessage(analysisError));
      setStatusMessage("Analysis could not be started.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-8 px-4 pb-12 pt-4 sm:px-6 lg:px-8">
        <nav className="sticky top-4 z-30 flex items-center justify-between rounded-full border border-[color:var(--border)] bg-[var(--surface)] px-4 py-3 shadow-[var(--shadow-soft)] backdrop-blur">
          <div className="flex items-center gap-3">
            <BrandMark alt="MedSpeak logo" size={52} />
            <div>
              <p className="text-lg font-semibold text-[var(--text-primary)]">MedSpeak</p>
              <p className="text-xs uppercase tracking-[0.2em] text-[var(--text-tertiary)]">Grounded visit clarity</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <a
              aria-label="Open MedSpeak GitHub repository"
              className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[color:var(--border-strong)] bg-[var(--surface-strong)] text-[var(--text-primary)] shadow-[var(--shadow-soft)] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-medium)]"
              href="https://github.com/chetas1208/MedSpeak"
              rel="noreferrer"
              target="_blank"
              title="GitHub repository"
            >
              <GitHubIcon />
            </a>
            <ThemeToggle />
          </div>
        </nav>

        <section className="grid gap-8 xl:grid-cols-[1.08fr_0.92fr]">
          <div className="space-y-6">
            <div className="space-y-4 px-1">
              <p className="text-sm font-semibold uppercase tracking-[0.28em] text-[var(--brand-teal-deep)]">
                Visit capture and grounded follow-up
              </p>
              <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-[var(--text-primary)] sm:text-5xl">
                Upload audio, get a clear visit report, and ask MedSpeak questions from the beginning.
              </h1>
              <p className="max-w-3xl text-base leading-8 text-[var(--text-secondary)]">
                MedSpeak transcribes the visit, keeps real names visible when available, turns generic speakers into
                Patient and Doctor, and keeps every answer grounded to the visit record or the visible app workflow.
              </p>
            </div>

            <section className="rounded-[34px] border border-[color:var(--border)] bg-[var(--surface)] p-6 shadow-[var(--shadow-medium)] backdrop-blur">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--brand-teal-deep)]">Capture input</p>
                  <h2 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Record or upload a visit</h2>
                  <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                    Prepare the audio or load the bundled demo transcript, then run analysis.
                  </p>
                </div>
                <div className="flex gap-2 rounded-full border border-[color:var(--border)] bg-[var(--surface-soft)] p-1">
                  {(["audio", "demo"] as const).map((item) => (
                    <button
                      key={item}
                      className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${
                        mode === item
                          ? "bg-[var(--surface-strong)] text-[var(--text-primary)] shadow-[var(--shadow-soft)]"
                          : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                      }`}
                      onClick={() => setMode(item)}
                      type="button"
                    >
                      {item === "audio" ? "Audio workflow" : "Demo transcript"}
                    </button>
                  ))}
                </div>
              </div>

              {mode === "audio" ? (
                <div className="mt-6 grid gap-5 lg:grid-cols-2">
                  <article className="rounded-[28px] border border-[color:var(--border-strong)] bg-[var(--surface-muted)] p-5">
                    <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--brand-teal-deep)]">Record here</p>
                    <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">
                      Use local microphone capture if you just finished the visit and want a fast handoff.
                    </p>
                    <div className="mt-5 flex flex-wrap gap-3">
                      <button
                        className="rounded-full bg-[var(--surface-contrast)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--surface-contrast-soft)] disabled:cursor-not-allowed disabled:bg-slate-400"
                        disabled={isRecording}
                        onClick={() => void startRecording()}
                        type="button"
                      >
                        Start Recording
                      </button>
                      <button
                        className="rounded-full border border-[color:var(--border)] bg-[var(--surface-strong)] px-5 py-3 text-sm font-semibold text-[var(--text-primary)] transition hover:bg-[var(--surface-soft)] disabled:cursor-not-allowed disabled:opacity-60"
                        disabled={!isRecording}
                        onClick={stopRecording}
                        type="button"
                      >
                        Stop Recording
                      </button>
                    </div>
                  </article>

                  <article className="rounded-[28px] border border-[color:var(--border)] bg-[var(--surface-gold)] p-5">
                    <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[#8a6a1d]">Upload audio</p>
                    <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">
                      Bring a `.wav`, `.mp3`, `.m4a`, `.webm`, or similar file. The backend will normalize it before transcription.
                    </p>
                    <div className="mt-5 flex flex-wrap gap-3">
                      <button
                        className="rounded-full border border-[color:var(--border)] bg-[var(--surface-strong)] px-5 py-3 text-sm font-semibold text-[var(--text-primary)] transition hover:bg-[var(--background-strong)]"
                        onClick={() => fileInputRef.current?.click()}
                        type="button"
                      >
                        Choose Audio File
                      </button>
                      <input
                        ref={fileInputRef}
                        accept="audio/*"
                        className="hidden"
                        onChange={(event) => handleAudioPicked(event.target.files?.[0] ?? null)}
                        type="file"
                      />
                    </div>
                  </article>
                </div>
              ) : (
                <div className="mt-6 rounded-[28px] border border-[color:var(--border)] bg-[var(--surface-gold)] p-5">
                  <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[#8a6a1d]">Judge-friendly demo</p>
                  <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">
                    Load the bundled transcript to test the full analysis and chat experience without uploading audio.
                  </p>
                  <div className="mt-5 flex flex-wrap gap-3">
                    <button
                      className="rounded-full bg-[var(--surface-contrast)] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[var(--surface-contrast-soft)]"
                      onClick={() => void loadDemoTranscript()}
                      type="button"
                    >
                      Load Demo Transcript
                    </button>
                    {demoTranscript ? (
                      <span className="rounded-full border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#8a6a1d]">
                        Transcript ready
                      </span>
                    ) : null}
                  </div>
                  {demoTranscript ? (
                    <pre className="mt-5 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-[24px] border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-4 text-sm leading-7 text-[var(--text-secondary)]">
                      {demoTranscript}
                    </pre>
                  ) : null}
                </div>
              )}

              {localAudioUrl ? (
                <div className="mt-6 rounded-[28px] border border-[color:var(--border)] bg-[var(--surface-strong)] p-5 shadow-[var(--shadow-soft)]">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold uppercase tracking-[0.18em] text-[var(--brand-teal-deep)]">Audio ready</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">{localAudioFile?.name}</p>
                    </div>
                    <button
                      className="rounded-full border border-[color:var(--border)] bg-[var(--surface-strong)] px-4 py-2 text-sm font-semibold text-[var(--text-primary)] transition hover:bg-[var(--surface-soft)]"
                      onClick={() => {
                        if (localAudioUrl) {
                          URL.revokeObjectURL(localAudioUrl);
                        }
                        setLocalAudioUrl(null);
                        setLocalAudioFile(null);
                      }}
                      type="button"
                    >
                      Clear audio
                    </button>
                  </div>
                  <audio className="mt-4 w-full" controls src={localAudioUrl} />
                </div>
              ) : null}

              <div className="mt-6 rounded-[30px] border border-[color:var(--border-strong)] bg-[linear-gradient(135deg,var(--surface-contrast),#23606f)] px-5 py-5 text-white shadow-[var(--shadow-strong)]">
                <div className="flex flex-wrap items-center justify-between gap-5">
                  <div className="max-w-2xl">
                    <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--brand-gold-soft)]">Ready when you are</p>
                    <p className="mt-2 text-sm leading-7 text-white/84">
                      Generate the MedSpeak visit report, downloadable PDF, and grounded chat context from the prepared input.
                    </p>
                  </div>
                  <button
                    className="inline-flex min-h-14 items-center justify-center rounded-full bg-[linear-gradient(135deg,var(--brand-gold),#f7d78e)] px-6 py-3 text-sm font-semibold text-[var(--surface-contrast)] shadow-[0_18px_34px_rgba(212,177,91,0.26)] transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-55"
                    disabled={!canAnalyze}
                    onClick={() => void runAnalysis()}
                    type="button"
                  >
                    {isSubmitting ? "Queueing..." : mode === "demo" ? "Analyze Demo Transcript" : "Analyze Visit"}
                  </button>
                </div>
              </div>
            </section>
          </div>

          <div className="space-y-6">
            <section className="rounded-[30px] border border-[color:var(--border)] bg-[var(--surface)] p-5 shadow-[var(--shadow-medium)] backdrop-blur">
              <div className="flex items-start gap-4">
                <BrandMark alt="MedSpeak logo" size={58} />
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[var(--brand-teal-deep)]">Session status</p>
                  <h2 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Ask MedSpeak from the start</h2>
                  <p className="mt-3 text-sm leading-7 text-[var(--text-secondary)]">{statusMessage}</p>
                </div>
              </div>

              <p className="mt-5 text-sm leading-7 text-[var(--text-secondary)]">
                {mode === "audio" ? "Audio workflow" : "Demo transcript"}.
                {" "}
                {hasPreparedInput ? "Input ready." : "Input not ready yet."}
                {" "}
                {job ? `Current job: ${jobStageLabels[job.status]}.` : "Chat is available now."}
              </p>

              {error ? (
                <div className="mt-5 rounded-[22px] border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-800">
                  {error}
                </div>
              ) : null}
            </section>

            <PreferencesForm
              autismMode={autismMode}
              language={language}
              onAutismModeChange={setAutismMode}
              onLanguageChange={setLanguage}
              onPreferencesChange={setPreferences}
              preferences={preferences}
            />

            <StatusRail job={job} />
          </div>
        </section>

        {job?.status === "READY" ? (
          <ResultsTabs job={job} activeTab={activeResultTab} onActiveTabChange={setActiveResultTab} />
        ) : null}
      </main>

      <MedSpeakDrawer
        activeResultTab={job?.status === "READY" ? activeResultTab : null}
        autismMode={autismMode}
        hasAudioReady={hasPreparedInput}
        jobId={job?.job_id ?? null}
        jobStatus={job?.status ?? null}
        mode={mode}
        statusMessage={statusMessage}
      />
    </>
  );
}
