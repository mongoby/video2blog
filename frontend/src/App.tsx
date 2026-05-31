import { useState, useEffect, useCallback, useRef } from 'react';
import { ConfigProvider, theme, Upload, Spin, message, Input, Pagination, Collapse } from 'antd';
import {
  VideoCameraOutlined, FileTextOutlined, DownloadOutlined, EditOutlined,
  DeleteOutlined, ReloadOutlined, PlayCircleOutlined, CheckCircleOutlined,
  CloseCircleOutlined, LoadingOutlined, FileAddOutlined,
} from '@ant-design/icons';
import type { UploadProps } from 'antd';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Job, listJobs, uploadVideo, submitUrl, getJob, triggerTranscribe, triggerGenerate,
  getTranscript, getBlog, saveBlog, getExportUrl, deleteJob,
  formatBytes, formatDuration, timeAgo,
} from './api/video2blog';

// ── Tone & Length options ──
const TONE_OPTIONS = [
  { value: 'professional', label: '专业分析' },
  { value: 'casual', label: '轻松随意' },
  { value: 'technical', label: '技术深度' },
  { value: 'storytelling', label: '故事叙述' },
];

const LENGTH_OPTIONS: { value: string; label: string }[] = [];

const MODEL_OPTIONS = [
  { value: 'tiny', label: 'Tiny (最快)' },
  { value: 'base', label: 'Base' },
  { value: 'small', label: 'Small' },
  { value: 'medium', label: 'Medium' },
  { value: 'large-v3', label: 'Large-v3 (最准)' },
];

// ── Status helpers ──
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    created: ['notion-badge-default', '待处理'],
    transcribing: ['notion-badge-processing', '转录中'],
    transcribed: ['notion-badge-success', '已转录'],
    generating: ['notion-badge-processing', '生成中'],
    done: ['notion-badge-success', '已完成'],
    error: ['notion-badge-error', '出错'],
  };
  const [cls, label] = map[status] || ['notion-badge-default', status];
  return <span className={`notion-badge ${cls}`}>{label}</span>;
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'transcribing': case 'generating':
      return <LoadingOutlined style={{ color: '#9b9a97', fontSize: 12 }} />;
    case 'done': return <CheckCircleOutlined style={{ color: '#4eac6d', fontSize: 12 }} />;
    case 'error': return <CloseCircleOutlined style={{ color: '#eb5757', fontSize: 12 }} />;
    default: return <FileTextOutlined style={{ color: '#9b9a97', fontSize: 12 }} />;
  }
}

// ── Notion-style Dropdown ──
function NotionSelect({ value, options, onChange, style }: any) {
  return (
    <select
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      style={{
        border: '1px solid var(--notion-border)',
        borderRadius: 4,
        padding: '6px 10px',
        fontSize: 13,
        fontFamily: 'inherit',
        color: 'var(--notion-text)',
        background: 'var(--notion-bg)',
        outline: 'none',
        cursor: 'pointer',
        ...style,
      }}
      onFocus={(e) => { e.target.style.borderColor = '#2d7ff9'; }}
      onBlur={(e) => { e.target.style.borderColor = '#e9e9e7'; }}
    >
      {options.map((opt: any) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

// ── Main App ──
export default function App() {
  // Restore page from URL hash (survives Ctrl+R / F5)
  const getInitialPage = () => {
    const hash = window.location.hash.slice(1);
    return (hash === 'jobs' || hash === 'upload') ? hash : 'upload';
  };
  const [page, setPage_] = useState<'upload' | 'jobs'>(getInitialPage());
  // setPage wrapper that also updates URL hash
  const setPage = useCallback((p: 'upload' | 'jobs') => {
    setPage_(p);
    window.location.hash = p;
  }, []);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [transcript, setTranscript] = useState<string>('');
  const [blogContent, setBlogContent] = useState<string>('');
  const [editingBlog, setEditingBlog] = useState(false);
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Upload options
  const [whisperModel, setWhisperModel] = useState('base');
  const [tone, setTone] = useState('professional');
  const [inputMode, setInputMode] = useState<'file' | 'url'>('url');
  const [urlValue, setUrlValue] = useState('');
  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [pageNum, setPageNum] = useState(1);
  const [totalJobs, setTotalJobs] = useState(0);

  // ── Load jobs (plain async, not memoized) ──
  const loadJobs = useCallback(async (p?: number) => {
    try {
      const targetPage = p ?? pageNum;
      const data = await listJobs(targetPage);
      setJobs(data.jobs);
      setTotalJobs(data.total);
      if (p !== undefined) setPageNum(p);
    } catch (e: any) {
      console.error('Failed to fetch jobs:', e);
    }
  }, [pageNum]);

  useEffect(() => {
    loadJobs(1);
  }, []);

  // ── Poll job status ──
  const loadBlogData = useCallback(async (jobId: string) => {
    try {
      const [trans, blog] = await Promise.all([
        getTranscript(jobId).catch(() => null),
        getBlog(jobId).catch(() => null),
      ]);
      if (trans) setTranscript(trans.text);
      if (blog) setBlogContent(blog.content);
    } catch (e) {
      console.error('Failed to load blog data:', e);
    }
  }, []);

  const startPolling = useCallback((jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    setPolling(true);
    pollRef.current = window.setInterval(async () => {
      try {
        const job = await getJob(jobId);
        setSelectedJob(job);
        if (job.status === 'done') {
          loadBlogData(job.id);
        }
        if (['done', 'error'].includes(job.status)) {
          if (pollRef.current) clearInterval(pollRef.current);
          setPolling(false);
          loadJobs();
        }
      } catch (e) {
        if (pollRef.current) clearInterval(pollRef.current);
        setPolling(false);
      }
    }, 2000);
  }, [loadBlogData]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ── Upload handler ──
  const handleUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options;
    setLoading(true);
    try {
      const job = await uploadVideo(file as File, undefined, whisperModel, undefined, tone);
      setSelectedJob(job);
      setPage('jobs');
      startPolling(job.id);
      message.success('视频上传成功，开始转录...');
      onSuccess?.(job);
    } catch (e: any) {
      message.error(`上传失败: ${e.message}`);
      onError?.(e);
    } finally {
      setLoading(false);
    }
  };

  // ── URL submit handler ──
  const handleSubmitUrl = async () => {
    const url = urlValue.trim();
    if (!url) { message.warning('请输入视频链接'); return; }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      message.error('请输入有效的链接（以 http:// 或 https:// 开头）');
      return;
    }
    setLoading(true);
    try {
      const job = await submitUrl(url, undefined, whisperModel, undefined, tone);
      setSelectedJob(job);
      setPage('jobs');
      startPolling(job.id);
      message.success('链接已提交，开始下载视频...');
    } catch (e: any) {
      message.error(`提交失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Job actions ──
  const handleSelectJob = async (job: Job) => {
    setSelectedJob(job);
    setEditingBlog(false);
    if (['done', 'transcribed', 'generating'].includes(job.status)) {
      await loadBlogData(job.id);
    }
    setPage('jobs');
  };

  const handleGenerate = async (jobId: string) => {
    try {
      const job = await triggerGenerate(jobId);
      setSelectedJob(job);
      startPolling(jobId);
      message.info('开始生成博客');
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const handleRegenerate = async (jobId: string, t?: string, l?: string) => {
    try {
      const job = await triggerGenerate(jobId, t, l);
      setSelectedJob(job);
      startPolling(jobId);
      message.info('重新生成博客中...');
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const handleSaveBlog = async (jobId: string) => {
    try {
      await saveBlog(jobId, blogContent);
      message.success('博客已保存');
      setEditingBlog(false);
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const handleDelete = async (jobId: string) => {
    try {
      await deleteJob(jobId);
      message.success('已删除');
      if (selectedJob?.id === jobId) {
        setSelectedJob(null);
        setTranscript('');
        setBlogContent('');
      }
      loadJobs();
    } catch (e: any) {
      message.error(e.message);
    }
  };

  const runningCount = (jobs || []).filter(j => ['transcribing', 'generating'].includes(j.status)).length;

  // Job index helper (reverse order: newest = #01)
  const jobIdx = (id: string) => {
    const i = (jobs || []).findIndex(j => j.id === id);
    if (i === -1) return '??';
    return String(jobs.length - i).padStart(2, '0');
  };

  // ── Render: Upload page ──
  const renderUpload = () => {
    const SUPPORTED_PLATFORMS = [
      '小红书 (XiaoHongShu)', '抖音 (Douyin)', '腾讯短视频',
      'B站 (Bilibili)', 'YouTube', 'TikTok',
    ];
    return (
    <div className="notion-upload">
      <div className="notion-upload-title">🎬 video2blog</div>
      <div className="notion-upload-subtitle">
        AI 短视频转博客 — 粘贴链接或上传视频，自动转录，智能生成
      </div>

      {/* Mode tabs */}
      <div className="notion-mode-tabs">
        <button
          className={`notion-mode-tab ${inputMode === 'url' ? 'active' : ''}`}
          onClick={() => setInputMode('url')}
        ><FileTextOutlined /> 粘贴链接</button>
        <button
          className={`notion-mode-tab ${inputMode === 'file' ? 'active' : ''}`}
          onClick={() => setInputMode('file')}
        ><VideoCameraOutlined /> 上传文件</button>
      </div>

      {inputMode === 'file' ? (
      <div className="notion-upload-zone">
        <Upload.Dragger
          name="file"
          multiple={false}
          showUploadList={false}
          customRequest={handleUpload}
          accept=".mp4,.mkv,.mov,.avi,.webm,.flv,.wmv,.m4v,.mp3,.wav,.m4a,.ogg"
          disabled={loading}
          style={{ background: 'transparent', border: 'none' }}
        >
          <div className="upload-icon">
            <VideoCameraOutlined />
          </div>
          <p className="upload-label">点击或拖拽视频文件到此区域</p>
          <p className="upload-hint">
            支持 mp4/mkv/mov/avi/webm 等短视频格式 · GPU 加速
          </p>
        </Upload.Dragger>
      </div>
      ) : (
      <div className="notion-url-section">
        <div className="notion-url-input-row">
          <Input
            className="notion-url-input"
            placeholder="粘贴视频链接，例如 https://www.bilibili.com/video/BV1xx..."
            value={urlValue}
            onChange={(e) => setUrlValue(e.target.value)}
            onPressEnter={handleSubmitUrl}
            disabled={loading}
            size="large"
          />
          <button
            className="notion-btn notion-btn-blue"
            onClick={handleSubmitUrl}
            disabled={loading || !urlValue.trim()}
            style={{ height: 40, marginLeft: 8, whiteSpace: 'nowrap' }}
          >
            {loading ? <Spin style={{ fontSize: 14 }} /> : '提交'}
          </button>
        </div>
        <div className="notion-url-hints">
          支持平台：
          {SUPPORTED_PLATFORMS.map((p) => (
            <span key={p} className="notion-platform-badge">{p}</span>
          ))}
          <span className="notion-hint-note">等平台</span>
        </div>
      </div>
      )}

      <div className="notion-options">
        <div className="option-group">
          <span className="option-label">Whisper 模型</span>
          <NotionSelect value={whisperModel} options={MODEL_OPTIONS} onChange={setWhisperModel} style={{ minWidth: 140 }} />
        </div>
        <div className="option-group">
          <span className="option-label">语气风格</span>
          <NotionSelect value={tone} options={TONE_OPTIONS} onChange={setTone} style={{ minWidth: 120 }} />
        </div>
      </div>

      {loading && (
        <div className="notion-loading">
          <Spin style={{ color: '#9b9a97' }} />
          <span>{inputMode === 'url' ? '提交中...' : '上传中...'}</span>
        </div>
      )}
    </div>
    );
  };

  // ── Render: Jobs layout ──
  const renderJobs = () => {
    return (
    <div style={{ height: 'calc(100vh - var(--notion-header-height))', overflow: 'auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 24px', borderBottom: '1px solid var(--notion-border)' }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>📋 任务列表</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Pagination
            size="small"
            current={pageNum}
            total={totalJobs}
            pageSize={10}
            showSizeChanger={false}
            onChange={(p) => loadJobs(p)}
            style={{ marginRight: 8 }}
          />
          <button className="notion-btn notion-btn-sm" onClick={() => loadJobs()}><ReloadOutlined /> 刷新</button>
          <button className="notion-btn notion-btn-sm" onClick={() => setPage('upload')}><VideoCameraOutlined /> 新任务</button>
        </div>
      </div>

      {/* Table */}
      {!jobs || jobs.length === 0 ? (
        <div style={{ padding: '60px', textAlign: 'center', color: 'var(--notion-text-light)' }}>
          <div style={{ fontSize: 40, opacity: 0.4, marginBottom: 16 }}><FileTextOutlined /></div>
          <div style={{ fontSize: 14 }}>暂无任务，去上传页面提交一个新任务</div>
        </div>
      ) : (
      <div style={{ padding: '16px 24px' }}>
        <table className="notion-table">
          <thead>
            <tr>
              <th style={{ width: 50 }}>#</th>
              <th style={{ width: 160 }}>ID</th>
              <th>标题 / 链接</th>
              <th style={{ width: 100 }}>状态</th>
              <th style={{ width: 120 }}>大小</th>
              <th style={{ width: 80 }}>字数</th>
              <th style={{ width: 160 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job, idx) => {
              const isDetail = detailJob?.id === job.id;
              return (
                <tr key={job.id} className={isDetail ? 'notion-table-row-active' : ''}>
                  <td className="notion-td-idx">#{String(jobs.length - idx).padStart(2, '0')}</td>
                  <td style={{ fontSize: 12, color: 'var(--notion-text-muted)', fontFamily: 'monospace' }}>{job.id}</td>
                  <td>
                    <div className="notion-td-title" title={job.source_url || job.title}>{job.title}</div>
                    {job.source_url && <div className="notion-td-url" title={job.source_url}>{job.source_url}</div>}
                  </td>
                  <td><StatusBadge status={job.status} /></td>
                  <td className="notion-td-mono">{formatBytes(job.video_size)}</td>
                  <td className="notion-td-mono">{job.blog_word_count > 0 ? `${job.blog_word_count}字` : '-'}</td>
                  <td>
                    <button
                      className="notion-btn notion-btn-sm"
                      onClick={() => { setDetailJob(isDetail ? null : job); handleSelectJob(job); }}
                      title="详情"
                    >📋</button>
                    {job.status === 'transcribed' && (
                      <button
                        className="notion-btn notion-btn-sm"
                        style={{ color: 'var(--notion-green)', marginLeft: 4 }}
                        onClick={(e) => { e.stopPropagation(); handleGenerate(job.id); }}
                        title="生成博客"
                      >📝</button>
                    )}
                    {job.status === 'done' && (
                      <button
                        className="notion-btn notion-btn-sm"
                        style={{ color: 'var(--notion-blue)', marginLeft: 4 }}
                        onClick={(e) => { e.stopPropagation(); window.open(getExportUrl(job.id)); }}
                        title="导出MD"
                      >📥</button>
                    )}
                    <button
                      className="notion-btn notion-btn-sm"
                      style={{ opacity: 0.5, marginLeft: 4 }}
                      onClick={(e) => { e.stopPropagation(); handleDelete(job.id); }}
                      title="删除"
                    >🗑</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}

      {/* Detail panel */}
      {detailJob && selectedJob && (
        <div className="notion-detail-panel">
          <div className="notion-detail-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 600 }}>#{jobIdx(detailJob.id)} {detailJob.title}</span>
              <StatusBadge status={detailJob.status} />
            </div>
            <button className="notion-btn notion-btn-sm" onClick={() => setDetailJob(null)}>✕ 关闭</button>
          </div>
          <div className="notion-detail-body">
            {/* Meta info */}
            <div className="notion-detail-meta">
              <span className="meta-item">⏱ ID: {detailJob.id}</span>
              {detailJob.source_url && (
                <span className="meta-item">
                  🔗 <a href={detailJob.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--notion-blue)' }}>原链接</a>
                </span>
              )}
              <span className="meta-item">{formatBytes(detailJob.video_size)}</span>
              {detailJob.video_duration && <span className="meta-item">⏱ {formatDuration(detailJob.video_duration)}</span>}
              <span className="meta-item">模型: {detailJob.whisper_model}</span>
              {detailJob.blog_word_count > 0 && <span className="meta-item">{detailJob.blog_word_count} 字</span>}
              <span className="meta-item" style={{ marginLeft: 'auto' }}>{timeAgo(detailJob.created_at)}</span>
            </div>

            {/* Error */}
            {detailJob.status === 'error' && (
              <div className="notion-error">
                <CloseCircleOutlined />
                <span>{detailJob.error}</span>
                <div className="notion-error-actions">
                  <button className="notion-btn notion-btn-sm" onClick={() => {
                    triggerTranscribe(detailJob.id).then(j => { setSelectedJob(j); startPolling(j.id); });
                  }}>重试</button>
                </div>
              </div>
            )}

            {/* Transcribed - ready to generate blog */}
            {detailJob.status === 'transcribed' && (
              <div className="notion-info" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px' }}>
                <FileTextOutlined style={{ fontSize: 16, color: 'var(--notion-green)' }} />
                <span style={{ flex: 1 }}>转录完成，可以生成博客了</span>
                <button
                  className="notion-btn notion-btn-sm"
                  style={{ color: 'var(--notion-green)', border: '1px solid var(--notion-green)' }}
                  onClick={() => handleGenerate(detailJob.id)}
                >📝 生成博客</button>
              </div>
            )}

            {/* Polling */}
            {polling && (
              <div className="notion-info">
                <LoadingOutlined />
                <span>{selectedJob.message || '处理中...'}</span>
              </div>
            )}

            {/* Blog preview (collapsible) */}
            {detailJob.status === 'done' && (
              <div style={{ padding: '12px 16px' }}>
                <Collapse
                  ghost
                  expandIconPosition="end"
                  items={[
                    transcript ? {
                      key: 'transcript',
                      label: <span><FileTextOutlined style={{ marginRight: 6 }} />转录文本 ({detailJob.transcript_chars || 0}字符)</span>,
                      children: (
                        <div style={{
                          background: 'var(--notion-code-bg)',
                          borderRadius: 6,
                          padding: 12,
                          fontSize: 13,
                          lineHeight: 1.7,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          maxHeight: 400,
                          overflow: 'auto',
                          color: 'var(--notion-text)',
                        }}>
                          {transcript}
                        </div>
                      ),
                    } : null,
                    blogContent ? {
                      key: 'blog',
                      label: <span><FileTextOutlined style={{ marginRight: 6 }} />博客内容 ({detailJob.blog_word_count || 0}字)</span>,
                      children: (
                        <div className="blog-preview">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {blogContent}
                          </ReactMarkdown>
                          <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                            <button
                              className="notion-btn notion-btn-sm"
                              style={{ color: 'var(--notion-blue)' }}
                              onClick={() => window.open(getExportUrl(detailJob.id))}
                            >📥 导出MD</button>
                          </div>
                        </div>
                      ),
                    } : null,
                  ].filter(Boolean)}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
    );
  };

  // ── Main Render ──
  return (
    <ConfigProvider theme={{ algorithm: theme.defaultAlgorithm }}>
      <div className="notion-app">
        {/* Header with navigation tabs */}
        <div className="notion-header">
          <div className="notion-header-left">
            <span className="notion-header-brand">🎬 video2blog</span>
          </div>
          <div className="notion-header-right">
            <button
              className={`notion-btn ${page === 'upload' ? 'notion-btn-primary' : ''}`}
              onClick={() => setPage('upload')}
            >
              <VideoCameraOutlined /> 上传
            </button>
            <button
              className={`notion-btn ${page === 'jobs' ? 'notion-btn-primary' : ''}`}
              onClick={() => { setPage('jobs'); loadJobs(1); }}
            >
              <FileTextOutlined /> 任务列表
            </button>
          </div>
        </div>
        {page === 'upload' ? renderUpload() : renderJobs()}
      </div>
    </ConfigProvider>
  );
}
