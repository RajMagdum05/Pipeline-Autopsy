import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useClaims } from '../context/ClaimsContext';
import { Claim, ClaimDocument, OCRResult } from '../types/claim';
import { getClaimDocuments, uploadClaimDocument, fetchDocumentOCR, getDocumentFileUrl } from '../api/claims';
import { StatusBadge } from '../components/StatusBadge';
import { Button } from '../components/Button';
import {
  ArrowLeft,
  FileText,
  ArrowRight,
  Layers,
  Sparkles,
  FileSearch,
  Brain,
  Workflow,
  Loader2,
  AlertTriangle,
  Upload,
  CheckCircle2,
  Eye,
  X,
  Code,
  ListFilter,
  ExternalLink,
  Columns,
} from 'lucide-react';

export const ClaimDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { getClaim } = useClaims();

  const [claim, setClaim] = useState<Claim | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Document management state
  const [serverDocuments, setServerDocuments] = useState<ClaimDocument[]>([]);
  const [documentType, setDocumentType] = useState<string>('Medical Report');
  const [customDocumentType, setCustomDocumentType] = useState<string>('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  // OCR Evidence Modal state
  const [activeOcrDocument, setActiveOcrDocument] = useState<ClaimDocument | null>(null);
  const [ocrResult, setOcrResult] = useState<OCRResult | null>(null);
  const [loadingOcr, setLoadingOcr] = useState<boolean>(false);
  const [ocrTab, setOcrTab] = useState<'text' | 'lines' | 'json'>('text');
  const [activePageIdx, setActivePageIdx] = useState<number>(0);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    setError(null);

    getClaim(id)
      .then((data) => {
        if (data) {
          setClaim(data);
        } else {
          setError(`Claim #${id} not found.`);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Unable to connect to the claims service.');
      })
      .finally(() => {
        setLoading(false);
      });

    getClaimDocuments(id)
      .then((docs) => setServerDocuments(docs))
      .catch((err) => console.error('Error loading claim documents:', err));
  }, [id, getClaim]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !selectedFile) {
      setUploadError('Please choose a file to upload.');
      return;
    }

    const finalDocType = documentType === 'Other' ? customDocumentType.trim() : documentType;
    if (!finalDocType) {
      setUploadError('Please specify a document type.');
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);

    try {
      await uploadClaimDocument(id, selectedFile, finalDocType);
      setUploadSuccess(`Document "${selectedFile.name}" uploaded & processed via OCR!`);
      setSelectedFile(null);

      const fileInput = document.getElementById('document-file-input') as HTMLInputElement;
      if (fileInput) fileInput.value = '';

      const updatedDocs = await getClaimDocuments(id);
      setServerDocuments(updatedDocs);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Failed to upload document.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleInspectOcr = async (doc: ClaimDocument) => {
    if (!id) return;
    setActiveOcrDocument(doc);
    setActivePageIdx(0);

    if (doc.ocr_result) {
      setOcrResult(doc.ocr_result as OCRResult);
      return;
    }

    setLoadingOcr(true);
    setOcrResult(null);
    try {
      const result = await fetchDocumentOCR(id, doc.id);
      setOcrResult(result);
    } catch (err) {
      console.error('Failed to load OCR evidence:', err);
    } finally {
      setLoadingOcr(false);
    }
  };

  const formatAmount = (num: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(num);
  };

  // Pipeline stages definition
  const pipelineStages = [
    {
      id: 'doc-input',
      title: 'Document Input',
      description: 'Ingest attached medical report, hospital bill, and policy files',
      icon: FileText,
      status: 'completed',
    },
    {
      id: 'ocr',
      title: 'OCR & Normalization',
      description: 'PyMuPDF text / Tesseract image extraction & schema normalization',
      icon: FileSearch,
      status: serverDocuments.some(d => d.ocr_status === 'completed') ? 'completed' : 'pending',
    },
    {
      id: 'extraction',
      title: 'Information Extraction',
      description: 'Extract structured entity data & monetary fields via Gemini LLM',
      icon: Layers,
      status: 'pending',
    },
    {
      id: 'rag',
      title: 'RAG Policy Retrieval',
      description: 'Semantic vector similarity search across policy terms (pgvector)',
      icon: Sparkles,
      status: 'pending',
    },
    {
      id: 'reasoning',
      title: 'Policy Reasoning',
      description: 'LLM root-cause analysis & policy compliance evaluation',
      icon: Brain,
      status: 'pending',
    },
    {
      id: 'action',
      title: 'Business Action',
      description: 'Automated claim approval, flag for review, or rejection dispatch',
      icon: Workflow,
      status: 'pending',
    },
  ];

  if (loading) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-12 text-center space-y-3 shadow-xs">
        <Loader2 className="w-6 h-6 text-slate-600 animate-spin mx-auto" />
        <p className="text-sm font-medium text-slate-700">Loading claim #{id}...</p>
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-8 text-center space-y-4 shadow-xs">
        <AlertTriangle className="w-8 h-8 text-rose-500 mx-auto" />
        <div className="space-y-1">
          <h3 className="text-base font-semibold text-slate-900">Claim Not Available</h3>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">{error || `Claim #${id} could not be loaded.`}</p>
        </div>
        <Button onClick={() => navigate('/claims')} variant="secondary" size="sm">
          Back to Claims
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top navigation back link */}
      <div>
        <button
          onClick={() => navigate('/claims')}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Claims
        </button>
      </div>

      {/* Claim Detail Header Card */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-bold font-mono text-slate-900">
                Claim #{claim.id}
              </h2>
              <StatusBadge status={claim.status} />
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Created on {claim.createdAt} &bull; Internal Reference ID: AUT-{claim.id}-INS
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link to="/claims">
              <Button variant="outline" size="sm">
                Close View
              </Button>
            </Link>
          </div>
        </div>

        {/* Claim Info Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div className="space-y-1">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
              Customer
            </p>
            <p className="text-base font-semibold text-slate-900">
              {claim.customerName}
            </p>
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
              Claim Amount
            </p>
            <p className="text-base font-semibold font-mono text-slate-900">
              {formatAmount(claim.amount)}
            </p>
          </div>

          <div className="space-y-1">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">
              Status
            </p>
            <p className="text-sm font-medium text-slate-800">
              {claim.status}
            </p>
          </div>
        </div>

        {/* Attached Documents Section */}
        <div className="pt-4 border-t border-slate-200 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
              <FileText className="w-4 h-4 text-slate-500" />
              Documents & OCR Evidence
            </h3>
            <span className="text-xs text-slate-500 font-mono">
              {serverDocuments.length} attached
            </span>
          </div>

          {/* Upload Document Form */}
          <form onSubmit={handleUpload} className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-3">
            <h4 className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
              Upload Document for Auto-OCR
            </h4>

            {uploadError && (
              <div className="p-3 bg-rose-50 border border-rose-200 rounded-md text-xs text-rose-700 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}

            {uploadSuccess && (
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-md text-xs text-emerald-700 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{uploadSuccess}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Document Type
                </label>
                <select
                  value={documentType}
                  onChange={(e) => setDocumentType(e.target.value)}
                  className="w-full text-xs bg-white border border-slate-300 rounded-md px-3 py-2 text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-slate-400"
                >
                  <option value="Medical Report">Medical Report</option>
                  <option value="Hospital Bill">Hospital Bill</option>
                  <option value="Insurance Policy">Insurance Policy</option>
                  <option value="Other">Other</option>
                </select>

                {documentType === 'Other' && (
                  <input
                    type="text"
                    placeholder="Enter document type..."
                    value={customDocumentType}
                    onChange={(e) => setCustomDocumentType(e.target.value)}
                    className="mt-2 w-full text-xs bg-white border border-slate-300 rounded-md px-3 py-1.5 text-slate-800 focus:outline-hidden focus:ring-2 focus:ring-slate-400"
                  />
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Choose File <span className="text-slate-400 font-normal">(PDF, PNG, JPG, JPEG)</span>
                </label>
                <input
                  id="document-file-input"
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  className="w-full text-xs text-slate-600 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-200 file:text-slate-700 hover:file:bg-slate-300 cursor-pointer"
                />
              </div>
            </div>

            <div className="flex justify-end pt-1">
              <Button type="submit" disabled={isUploading || !selectedFile} size="sm">
                {isUploading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                    Processing OCR...
                  </>
                ) : (
                  <>
                    <Upload className="w-3.5 h-3.5 mr-1.5" />
                    Upload & Run OCR
                  </>
                )}
              </Button>
            </div>
          </form>

          {/* Document List with OCR Status & Evidence Inspector */}
          {serverDocuments.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 pt-2">
              {serverDocuments.map((doc) => (
                <div
                  key={doc.id}
                  className="p-3.5 bg-white border border-slate-200 rounded-lg hover:border-slate-300 transition-all space-y-2 shadow-2xs flex flex-col justify-between"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FileText className="w-4 h-4 text-slate-600 shrink-0" />
                        <p className="text-xs font-semibold text-slate-900 font-mono truncate" title={doc.file_name}>
                          {doc.file_name}
                        </p>
                      </div>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border shrink-0 ${
                          doc.ocr_status === 'completed'
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : doc.ocr_status === 'failed'
                            ? 'bg-rose-50 text-rose-700 border-rose-200'
                            : 'bg-amber-50 text-amber-700 border-amber-200'
                        }`}
                      >
                        OCR {doc.ocr_status || 'completed'}
                      </span>
                    </div>

                    <div className="text-[11px] text-slate-500 space-y-0.5 font-mono">
                      <p><span className="text-slate-400 font-sans">Type:</span> {doc.document_type}</p>
                      {doc.ocr_result?.engine && (
                        <p><span className="text-slate-400 font-sans">Engine:</span> {doc.ocr_result.engine} ({doc.ocr_result.processing_duration_ms}ms)</p>
                      )}
                    </div>
                  </div>

                  <div className="pt-2 border-t border-slate-100 flex justify-end">
                    <button
                      onClick={() => handleInspectOcr(doc)}
                      className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-slate-700 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 px-2.5 py-1.5 rounded-md transition-colors cursor-pointer"
                    >
                      <Eye className="w-3.5 h-3.5 text-slate-500" />
                      Inspect OCR Evidence
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500 italic pt-1">No documents uploaded yet for this claim.</p>
          )}
        </div>
      </div>


      {/* PIPELINE VISUALIZATION SECTION */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-6">
        <div className="flex items-center justify-between border-b border-slate-200 pb-4">
          <div>
            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
              <Workflow className="w-5 h-5 text-slate-700" />
              Pipeline Execution Trace
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Live OCR execution sequence and evidence flow for root-cause analysis
            </p>
          </div>
          <span className="text-[11px] font-mono px-2.5 py-1 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-md">
            OCR Layer Active
          </span>
        </div>

        {/* Pipeline Stage Sequence Flow */}
        <div className="space-y-4">
          <div className="hidden lg:grid grid-cols-6 gap-2 items-center">
            {pipelineStages.map((stage, idx) => {
              const Icon = stage.icon;
              return (
                <React.Fragment key={stage.id}>
                  <div className={`border rounded-lg p-3 text-center space-y-2 relative group transition-all ${
                    stage.status === 'completed'
                      ? 'bg-slate-900 text-white border-slate-900'
                      : 'bg-slate-50 border-slate-200 text-slate-700'
                  }`}>
                    <div className={`w-8 h-8 rounded-full border flex items-center justify-center mx-auto shadow-2xs ${
                      stage.status === 'completed'
                        ? 'bg-white text-slate-900 border-white'
                        : 'bg-white text-slate-700 border-slate-200'
                    }`}>
                      <Icon className="w-4 h-4" />
                    </div>
                    <div>
                      <p className={`text-xs font-semibold leading-snug ${stage.status === 'completed' ? 'text-white' : 'text-slate-900'}`}>
                        {stage.title}
                      </p>
                      <p className={`text-[10px] mt-0.5 line-clamp-2 ${stage.status === 'completed' ? 'text-slate-300' : 'text-slate-500'}`}>
                        {stage.description}
                      </p>
                    </div>
                  </div>
                  {idx < pipelineStages.length - 1 && (
                    <div className="hidden lg:flex items-center justify-center text-slate-300 -mx-3 z-10">
                      <ArrowRight className="w-4 h-4 text-slate-400" />
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </div>


      {/* INTERACTIVE DOCUMENT EXTRACTION & EVIDENCE PREVIEW MODAL */}
      {activeOcrDocument && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-2 sm:p-4">
          <div className="bg-white rounded-xl shadow-2xl border border-slate-300 w-full max-w-7xl h-[92vh] max-h-[92vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-6 py-3.5 border-b border-slate-200 flex items-center justify-between bg-slate-900 text-white shrink-0">
              <div className="flex items-center gap-3">
                <FileSearch className="w-5 h-5 text-emerald-400" />
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm sm:text-base font-bold font-mono">
                      {activeOcrDocument.file_name}
                    </h3>
                    <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 uppercase">
                      {activeOcrDocument.file_name.toLowerCase().endsWith('.pdf') ? 'Digital PDF' : 'Image'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 font-sans">
                    Document #{activeOcrDocument.id} &bull; {activeOcrDocument.document_type} &bull; Claim #{id}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <a
                  href={id ? getDocumentFileUrl(id, activeOcrDocument.id) : '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-2.5 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 rounded border border-slate-700 flex items-center gap-1.5 transition-colors cursor-pointer"
                  title="Open original file in new browser tab"
                >
                  <ExternalLink className="w-3.5 h-3.5 text-slate-300" />
                  <span>Open Raw File</span>
                </a>
                <button
                  onClick={() => setActiveOcrDocument(null)}
                  className="p-1.5 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition-colors cursor-pointer"
                  title="Close Preview"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
              {loadingOcr ? (
                <div className="flex-1 flex flex-col items-center justify-center space-y-3 p-8">
                  <Loader2 className="w-8 h-8 text-slate-700 animate-spin" />
                  <p className="text-xs font-medium text-slate-600">Loading document extraction and original file...</p>
                </div>
              ) : !ocrResult ? (
                <div className="flex-1 flex items-center justify-center p-8 text-center text-rose-600 text-xs font-medium">
                  Failed to load extraction evidence for this document.
                </div>
              ) : (
                <div className="flex-1 flex flex-col min-h-0">
                  {/* Top Metadata & Navigation Toolbar */}
                  <div className="px-6 py-2.5 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 shrink-0 text-xs">
                    {/* Extraction Stats */}
                    <div className="flex items-center gap-4 text-slate-700 font-mono text-[11px]">
                      <div>
                        <span className="text-slate-400 font-sans uppercase text-[10px] block">Engine</span>
                        <span className="font-bold text-slate-900">{ocrResult.engine.toUpperCase()} {ocrResult.engine_version ? `v${ocrResult.engine_version}` : ''}</span>
                      </div>
                      <div className="h-6 w-px bg-slate-200" />
                      <div>
                        <span className="text-slate-400 font-sans uppercase text-[10px] block">Total Pages</span>
                        <span className="font-bold text-slate-900">{ocrResult.pages?.length || 1}</span>
                      </div>
                      <div className="h-6 w-px bg-slate-200" />
                      <div>
                        <span className="text-slate-400 font-sans uppercase text-[10px] block">Total Extracted Text</span>
                        <span className="font-bold text-emerald-700">
                          {ocrResult.pages?.reduce((acc, p) => acc + (p.raw_text?.length || 0), 0) || 0} chars
                        </span>
                      </div>
                    </div>

                    {/* View Mode Tabs */}
                    <div className="flex items-center gap-1.5 bg-slate-200/80 p-1 rounded-lg">
                      <button
                        onClick={() => setOcrTab('text')}
                        className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer flex items-center gap-1.5 ${
                          ocrTab === 'text'
                            ? 'bg-white text-slate-900 shadow-xs'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                      >
                        <Columns className="w-3.5 h-3.5 text-emerald-600" />
                        Side-by-Side Preview
                      </button>

                      <button
                        onClick={() => setOcrTab('lines')}
                        className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer flex items-center gap-1.5 ${
                          ocrTab === 'lines'
                            ? 'bg-white text-slate-900 shadow-xs'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                      >
                        <ListFilter className="w-3.5 h-3.5 text-blue-600" />
                        Layout Evidence & Words
                      </button>

                      <button
                        onClick={() => setOcrTab('json')}
                        className={`px-3 py-1 text-xs font-semibold rounded-md transition-colors cursor-pointer flex items-center gap-1.5 ${
                          ocrTab === 'json'
                            ? 'bg-white text-slate-900 shadow-xs'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                      >
                        <Code className="w-3.5 h-3.5 text-purple-600" />
                        JSONB
                      </button>
                    </div>
                  </div>

                  {/* Main Split Panels */}
                  <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-slate-200 overflow-hidden min-h-0">
                    {/* LEFT PANEL: Original Document Preview */}
                    <div className="flex flex-col min-h-0 bg-slate-100 p-4">
                      <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200 shrink-0">
                        <div className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                          <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                            Original Document Preview
                          </h4>
                        </div>
                        <span className="text-[11px] text-slate-500 font-mono">
                          {activeOcrDocument.file_name}
                        </span>
                      </div>

                      <div className="flex-1 bg-white rounded-lg border border-slate-300 shadow-inner overflow-hidden relative">
                        {id && (
                          <iframe
                            src={getDocumentFileUrl(id, activeOcrDocument.id)}
                            className="w-full h-full border-0"
                            title="Original Document Preview"
                          />
                        )}
                      </div>
                    </div>

                    {/* RIGHT PANEL: Complete Extracted Text / Evidence */}
                    <div className="flex flex-col min-h-0 bg-white p-4">
                      {/* Tab 1: Complete Extracted Text with Page Boundaries */}
                      {ocrTab === 'text' && (
                        <div className="flex flex-col min-h-0 flex-1">
                          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200 shrink-0">
                            <div className="flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full bg-blue-500"></span>
                              <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                                Complete Extracted Text (PyMuPDF)
                              </h4>
                            </div>
                            <span className="text-[11px] text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded font-mono border border-emerald-200 font-semibold">
                              All {ocrResult.pages?.length || 1} Pages Untruncated
                            </span>
                          </div>

                          <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                            {ocrResult.pages && ocrResult.pages.length > 0 ? (
                              ocrResult.pages.map((p, idx) => (
                                <div key={idx} className="border border-slate-200 rounded-lg overflow-hidden bg-slate-50">
                                  <div className="bg-slate-100 px-3 py-1.5 border-b border-slate-200 flex items-center justify-between text-xs font-mono text-slate-700">
                                    <span className="font-bold flex items-center gap-1.5">
                                      <FileText className="w-3.5 h-3.5 text-slate-500" />
                                      PAGE {p.page_number}
                                    </span>
                                    <span className="text-[11px] text-slate-500">
                                      {p.width && p.height ? `${p.width} x ${p.height} pt` : ''} &bull; {p.raw_text?.length || 0} chars
                                    </span>
                                  </div>
                                  <pre className="p-4 font-mono text-xs text-slate-900 whitespace-pre-wrap leading-relaxed bg-white select-text">
                                    {p.raw_text || <span className="text-slate-400 italic">No text extracted on this page.</span>}
                                  </pre>
                                </div>
                              ))
                            ) : (
                              <p className="text-xs text-slate-500 p-4">No text extracted.</p>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Tab 2: Structured Lines & Word Bounding Boxes */}
                      {ocrTab === 'lines' && (
                        <div className="flex flex-col min-h-0 flex-1">
                          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200 shrink-0">
                            <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                              Word & Line Layout Evidence
                            </h4>
                            {ocrResult.pages && ocrResult.pages.length > 1 && (
                              <div className="flex items-center gap-1.5 text-xs font-mono">
                                <span className="text-slate-500">Page:</span>
                                <select
                                  value={activePageIdx}
                                  onChange={(e) => setActivePageIdx(Number(e.target.value))}
                                  className="bg-white border border-slate-300 rounded px-2 py-0.5 text-xs font-mono"
                                >
                                  {ocrResult.pages.map((p, i) => (
                                    <option key={i} value={i}>Page {p.page_number}</option>
                                  ))}
                                </select>
                              </div>
                            )}
                          </div>

                          <div className="flex-1 overflow-y-auto space-y-3 pr-2">
                            {(() => {
                              const activePage = ocrResult.pages?.[activePageIdx] || ocrResult.pages?.[0];
                              if (!activePage || !activePage.lines || activePage.lines.length === 0) {
                                return <p className="text-xs text-slate-500 p-4">No line/word structured evidence available.</p>;
                              }
                              return activePage.lines.map((line, lIdx) => (
                                <div key={lIdx} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2 text-xs font-mono">
                                  <div className="flex items-start justify-between gap-2">
                                    <span className="font-semibold text-slate-900 font-sans">
                                      Line #{lIdx + 1}: "{line.text}"
                                    </span>
                                    {line.bounding_box && (
                                      <span className="px-1.5 py-0.5 bg-slate-200 text-slate-700 rounded text-[10px]">
                                        BBox: [{line.bounding_box.x0 ?? line.bounding_box[0]}, {line.bounding_box.y0 ?? line.bounding_box[1]}, {line.bounding_box.x1 ?? line.bounding_box[2]}, {line.bounding_box.y1 ?? line.bounding_box[3]}]
                                      </span>
                                    )}
                                  </div>

                                  {line.words && line.words.length > 0 && (
                                    <div className="pt-2 border-t border-slate-200 flex flex-wrap gap-1.5">
                                      {line.words.map((word, wIdx) => (
                                        <div
                                          key={wIdx}
                                          className="px-2 py-0.5 bg-white border border-slate-200 rounded text-[11px]"
                                          title={`Word: "${word.text}"`}
                                        >
                                          <span className="font-medium text-slate-900">{word.text}</span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              ));
                            })()}
                          </div>
                        </div>
                      )}

                      {/* Tab 3: Complete Raw JSONB */}
                      {ocrTab === 'json' && (
                        <div className="flex flex-col min-h-0 flex-1">
                          <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200 shrink-0">
                            <h4 className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                              PostgreSQL JSONB Stored Record
                            </h4>
                          </div>
                          <pre className="flex-1 overflow-y-auto p-4 bg-slate-900 text-emerald-400 font-mono text-xs rounded-lg border border-slate-800 select-text">
                            {JSON.stringify(ocrResult, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-2.5 border-t border-slate-200 bg-slate-50 flex items-center justify-between shrink-0">
              <span className="text-[11px] text-slate-500 font-sans">
                Source of truth: PyMuPDF extraction stored in PostgreSQL
              </span>
              <Button onClick={() => setActiveOcrDocument(null)} variant="secondary" size="sm">
                Close Preview
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
