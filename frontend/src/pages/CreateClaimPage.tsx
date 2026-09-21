import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useClaims } from '../context/ClaimsContext';
import { Button } from '../components/Button';
import { Upload, ArrowLeft, FileCheck, X, AlertTriangle, Loader2 } from 'lucide-react';

export const CreateClaimPage: React.FC = () => {
  const navigate = useNavigate();
  const { addClaim, isCreating } = useClaims();

  const [customerName, setCustomerName] = useState('');
  const [claimAmount, setClaimAmount] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      setSelectedFiles(prev => [...prev, ...files]);
    }
  };

  const handleRemoveFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!customerName.trim() || !claimAmount) return;

    try {
      const newClaim = await addClaim({
        customerName: customerName.trim(),
        amount: parseFloat(claimAmount) || 0,
        files: selectedFiles,
      });

      // After successful creation in PostgreSQL, navigate directly to /claims/:id
      navigate(`/claims/${newClaim.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to connect to the claims service.';
      setFormError(msg);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Back button */}
      <div>
        <button
          onClick={() => navigate('/claims')}
          disabled={isCreating}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-900 transition-colors cursor-pointer disabled:opacity-50"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Claims
        </button>
      </div>

      {/* Page Title & Subtitle */}
      <div className="border-b border-slate-200 pb-5">
        <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
          New Insurance Claim
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Enter the basic information for the claim.
        </p>
      </div>

      {/* Error alert banner */}
      {formError && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-rose-800 flex items-start gap-3 shadow-xs">
          <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-rose-900">
              Failed to Create Claim
            </h3>
            <p className="text-xs text-rose-700 mt-0.5">
              {formError}
            </p>
          </div>
        </div>
      )}

      {/* Form Container */}
      <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-6">
        {/* Field: Customer Name */}
        <div className="space-y-1.5">
          <label htmlFor="customerName" className="block text-sm font-medium text-slate-700">
            Customer Name <span className="text-rose-500">*</span>
          </label>
          <input
            id="customerName"
            type="text"
            required
            disabled={isCreating}
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            placeholder="e.g. Rahul Sharma"
            className="w-full px-3.5 py-2 text-sm bg-slate-50 border border-slate-300 rounded-lg focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-400 focus:border-slate-400 transition-all text-slate-900 placeholder:text-slate-400 disabled:opacity-50"
          />
        </div>

        {/* Field: Claim Amount */}
        <div className="space-y-1.5">
          <label htmlFor="claimAmount" className="block text-sm font-medium text-slate-700">
            Claim Amount (₹) <span className="text-rose-500">*</span>
          </label>
          <div className="relative">
            <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center text-slate-400 font-mono text-sm pointer-events-none">
              ₹
            </span>
            <input
              id="claimAmount"
              type="number"
              required
              min="0"
              disabled={isCreating}
              value={claimAmount}
              onChange={(e) => setClaimAmount(e.target.value)}
              placeholder="75000"
              className="w-full pl-8 pr-3.5 py-2 text-sm bg-slate-50 border border-slate-300 rounded-lg focus:bg-white focus:outline-none focus:ring-2 focus:ring-slate-400 focus:border-slate-400 transition-all text-slate-900 placeholder:text-slate-400 font-mono disabled:opacity-50"
            />
          </div>
        </div>

        {/* Field: Documents Upload (UI Only) */}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-slate-700">
            Documents
          </label>
          <div
            onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragOver(false);
              if (e.dataTransfer.files) {
                const files = Array.from(e.dataTransfer.files);
                setSelectedFiles(prev => [...prev, ...files]);
              }
            }}
            className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
              isDragOver ? 'border-slate-400 bg-slate-100' : 'border-slate-200 bg-slate-50/50 hover:bg-slate-50'
            }`}
          >
            <div className="w-10 h-10 rounded-full bg-slate-100 text-slate-600 flex items-center justify-center mx-auto mb-3">
              <Upload className="w-5 h-5" />
            </div>
            <p className="text-sm font-medium text-slate-800">
              Upload Documents
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Drag and drop files here or click to browse (PDF, PNG, JPG)
            </p>

            <input
              type="file"
              multiple
              disabled={isCreating}
              onChange={handleFileChange}
              className="hidden"
              id="file-upload-input"
            />
            <label
              htmlFor="file-upload-input"
              className="mt-4 inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium bg-white text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50 cursor-pointer shadow-xs"
            >
              Select Files
            </label>
          </div>

          {/* Selected File List */}
          {selectedFiles.length > 0 && (
            <ul className="mt-3 divide-y divide-slate-200 border border-slate-200 rounded-lg overflow-hidden bg-white">
              {selectedFiles.map((file, idx) => (
                <li key={idx} className="px-3.5 py-2 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-2 font-mono text-slate-700 truncate">
                    <FileCheck className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                    {file.name}
                  </span>
                  <button
                    type="button"
                    disabled={isCreating}
                    onClick={() => handleRemoveFile(idx)}
                    className="text-slate-400 hover:text-rose-500 p-1"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-200">
          <Button
            type="button"
            variant="secondary"
            disabled={isCreating}
            onClick={() => navigate('/claims')}
          >
            Cancel
          </Button>

          <Button type="submit" variant="primary" disabled={isCreating}>
            {isCreating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Creating claim...
              </>
            ) : (
              'Create Claim'
            )}
          </Button>
        </div>
      </form>
    </div>
  );
};
