/// <reference types="vite/client" />

export interface Job {
  id: string;
  title: string;
  source_url?: string;
  status: 'created' | 'transcribing' | 'transcribed' | 'generating' | 'done' | 'error';
  progress: number;
  message: string;
  video_file: string | null;
  video_size: number;
  video_duration: number | null;
  whisper_model: string;
  language: string | null;
  tone: string;
  length: string;
  transcript_chars: number;
  blog_word_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TranscriptData {
  text: string;
  segments: { start: number; end: number; text: string }[];
  language: string;
  duration: number;
  model: string;
}

export interface BlogData {
  content: string;
}

const BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data as T;
}

export async function listJobs(page: number = 1): Promise<{jobs: Job[], total: number, page: number, per_page: number}> {
  const data = await request<{jobs: Job[], total: number, page: number, per_page: number}>(`/jobs?page=${page}&per_page=10`);
  return data;
}

export async function getJob(jobId: string): Promise<Job> {
  const data = await request<{ job: Job }>(`/jobs/${jobId}`);
  return data.job;
}

export async function uploadVideo(
  file: File,
  title?: string,
  model?: string,
  language?: string,
  tone?: string,
  length?: string,
): Promise<Job> {
  const form = new FormData();
  form.append('file', file);
  if (title) form.append('title', title);
  if (model) form.append('model', model);
  if (language) form.append('language', language);
  if (tone) form.append('tone', tone);
  if (length) form.append('length', length);

  const res = await fetch(`${BASE}/jobs`, {
    method: 'POST',
    body: form,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data.job;
}

export async function submitUrl(
  url: string,
  title?: string,
  model?: string,
  language?: string,
  tone?: string,
  length?: string,
): Promise<Job> {
  const data = await request<{ job: Job }>('/jobs/from-url', {
    method: 'POST',
    body: JSON.stringify({ url, title, model, language, tone, length }),
  });
  return data.job;
}

export async function triggerTranscribe(jobId: string, model?: string, language?: string): Promise<Job> {
  return request<{ job: Job }>(`/jobs/${jobId}/transcribe`, {
    method: 'POST',
    body: JSON.stringify({ model, language }),
  }).then(d => d.job);
}

export async function triggerGenerate(jobId: string, tone?: string, length?: string): Promise<Job> {
  return request<{ job: Job }>(`/jobs/${jobId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ tone, length }),
  }).then(d => d.job);
}

export async function getTranscript(jobId: string): Promise<TranscriptData> {
  const data = await request<{ transcript: TranscriptData }>(`/jobs/${jobId}/transcript`);
  return data.transcript;
}

export async function getBlog(jobId: string): Promise<BlogData> {
  const data = await request<{ blog: BlogData }>(`/jobs/${jobId}/blog`);
  return data.blog;
}

export async function saveBlog(jobId: string, content: string): Promise<void> {
  await request(`/jobs/${jobId}/blog`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

export function getExportUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/export`;
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${res.status}`);
  }
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatDuration(seconds: number | null): string {
  if (!seconds) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  return new Date(iso).toLocaleDateString('zh-CN');
}
