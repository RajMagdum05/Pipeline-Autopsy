import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useClaims } from '../context/ClaimsContext';
import { ClaimsTable } from '../components/ClaimsTable';
import { Button } from '../components/Button';
import { Plus, ShieldAlert, FileText, CheckCircle2, AlertTriangle, RefreshCw, Loader2 } from 'lucide-react';

export const ClaimsPage: React.FC = () => {
  const navigate = useNavigate();
  const { claims, loading, error, refreshClaims } = useClaims();

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

        <Button
          onClick={() => navigate('/claims/new')}
          variant="primary"
          className="shadow-xs self-start sm:self-auto"
        >
          <Plus className="w-4 h-4" />
          New Claim
        </Button>
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

          {/* Table section */}
          <div>
            {claims.length === 0 ? (
              <div className="bg-white border border-slate-200 rounded-xl p-12 text-center space-y-3">
                <FileText className="w-8 h-8 text-slate-400 mx-auto" />
                <h3 className="text-sm font-semibold text-slate-800">No Claims Found</h3>
                <p className="text-xs text-slate-500 max-w-sm mx-auto">
                  There are currently no insurance claims stored in the PostgreSQL database. Click "+ New Claim" above to create one.
                </p>
              </div>
            ) : (
              <ClaimsTable claims={claims} />
            )}
          </div>
        </>
      )}
    </div>
  );
};
