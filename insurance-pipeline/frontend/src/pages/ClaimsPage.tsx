import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useClaims } from '../context/ClaimsContext';
import { ClaimsTable } from '../components/ClaimsTable';
import { Button } from '../components/Button';
import { Plus, ShieldAlert, FileText, CheckCircle2, AlertTriangle, RefreshCw, Loader2, Trash2 } from 'lucide-react';

export const ClaimsPage: React.FC = () => {
  const navigate = useNavigate();
  const { claims, loading, error, refreshClaims, deleteAllClaims } = useClaims();
  const [isDeletingAll, setIsDeletingAll] = useState(false);
  const [showClearModal, setShowClearModal] = useState(false);

  const handleConfirmClearAll = async () => {
    setIsDeletingAll(true);
    try {
      await deleteAllClaims();
      setShowClearModal(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to clear claims');
    } finally {
      setIsDeletingAll(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
            Claims
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Manage and process insurance claims
          </p>
        </div>

        <div className="flex items-center gap-2.5 self-start sm:self-auto">
          {claims.length > 0 && (
            <Button
              onClick={() => setShowClearModal(true)}
              disabled={isDeletingAll}
              variant="outline"
              className="text-rose-600 border-rose-200 hover:bg-rose-50 hover:border-rose-300 shadow-xs text-xs font-semibold cursor-pointer"
            >
              {isDeletingAll ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-600" />
              ) : (
                <Trash2 className="w-3.5 h-3.5 text-rose-600" />
              )}
              Clear All ({claims.length})
            </Button>
          )}

          <Button
            onClick={() => navigate('/claims/new')}
            variant="primary"
            className="shadow-xs text-xs font-semibold"
          >
            <Plus className="w-4 h-4" />
            New Claim
          </Button>
        </div>
      </div>

      {/* Connection Error Banner if Backend is Unavailable */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 text-rose-800 flex items-start justify-between gap-3 shadow-xs">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-rose-900">
                Connection Error
              </h3>
              <p className="text-xs text-rose-700 mt-0.5">
                {error}
              </p>
            </div>
          </div>

          <Button
            onClick={() => refreshClaims()}
            variant="outline"
            size="sm"
            className="border-rose-300 text-rose-800 hover:bg-rose-100 shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Retry
          </Button>
        </div>
      )}

      {/* Loading State Banner */}
      {loading && !error && (
        <div className="bg-white border border-slate-200 rounded-xl p-12 text-center space-y-3 shadow-xs">
          <Loader2 className="w-6 h-6 text-slate-600 animate-spin mx-auto" />
          <p className="text-sm font-medium text-slate-700">Loading claims...</p>
        </div>
      )}

      {/* Main Claims Dashboard Content when loaded */}
      {!loading && !error && (
        <>
          {/* Summary KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Total Claims</p>
                <p className="text-2xl font-semibold text-slate-900 mt-1 font-mono">{claims.length}</p>
              </div>
              <div className="p-2.5 bg-slate-100 text-slate-600 rounded-lg">
                <FileText className="w-5 h-5" />
              </div>
            </div>

            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Processing</p>
                <p className="text-2xl font-semibold text-amber-600 mt-1 font-mono">
                  {claims.filter(c => c.status === 'Processing' || c.status === 'Under Review').length}
                </p>
              </div>
              <div className="p-2.5 bg-amber-50 text-amber-600 rounded-lg">
                <ShieldAlert className="w-5 h-5" />
              </div>
            </div>

            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">Approved</p>
                <p className="text-2xl font-semibold text-emerald-600 mt-1 font-mono">
                  {claims.filter(c => c.status === 'Approved').length}
                </p>
              </div>
              <div className="p-2.5 bg-emerald-50 text-emerald-600 rounded-lg">
                <CheckCircle2 className="w-5 h-5" />
              </div>
            </div>
          </div>

          {/* Claims Table or Empty State */}
          {claims.length === 0 ? (
            <div className="bg-white border border-slate-200 rounded-xl p-12 text-center space-y-3 shadow-xs">
              <FileText className="w-8 h-8 text-slate-300 mx-auto" />
              <h3 className="text-base font-medium text-slate-800">No claims found</h3>
              <p className="text-xs text-slate-500 max-w-sm mx-auto">
                Get started by creating your first claim and processing it through the automated pipeline.
              </p>
              <div className="pt-2">
                <Button onClick={() => navigate('/claims/new')} variant="primary" size="sm">
                  <Plus className="w-4 h-4 mr-1.5" />
                  Create Claim
                </Button>
              </div>
            </div>
          ) : (
            <ClaimsTable claims={claims} />
          )}
        </>
      )}

      {/* Confirmation Modal for Clearing All Claims */}
      {showClearModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start gap-4">
              <div className="p-3 bg-rose-50 text-rose-600 rounded-xl shrink-0">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-slate-900">
                  Delete All Claims ({claims.length})?
                </h3>
                <p className="text-sm text-slate-500 mt-1">
                  Are you sure you want to permanently clear all claims from the database?
                </p>
                <p className="text-xs text-rose-600 mt-2 bg-rose-50 p-2.5 rounded-lg border border-rose-100">
                  This action cannot be undone. All claims, attached documents, and pipeline traces will be permanently removed.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setShowClearModal(false)}
                disabled={isDeletingAll}
                className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmClearAll}
                disabled={isDeletingAll}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow-xs transition-colors disabled:opacity-50 cursor-pointer"
              >
                {isDeletingAll ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting All...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Delete All Claims
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
