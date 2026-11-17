import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Claim } from '../types/claim';
import { StatusBadge } from './StatusBadge';
import { ChevronRight, FileText, Trash2, Loader2, AlertTriangle } from 'lucide-react';
import { useClaims } from '../context/ClaimsContext';

interface ClaimsTableProps {
  claims: Claim[];
}

export const ClaimsTable: React.FC<ClaimsTableProps> = ({ claims }) => {
  const { deleteClaim } = useClaims();
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [claimToDelete, setClaimToDelete] = useState<{ id: string; name: string } | null>(null);

  const formatAmount = (num: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(num);
  };

  const handleOpenDeleteModal = (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation();
    e.preventDefault();
    setClaimToDelete({ id, name });
  };

  const handleConfirmDelete = async () => {
    if (!claimToDelete) return;
    const targetId = claimToDelete.id;
    setDeletingId(targetId);
    try {
      await deleteClaim(targetId);
      setClaimToDelete(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete claim');
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <div className="bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                <th scope="col" className="px-6 py-3.5">
                  Claim ID
                </th>
                <th scope="col" className="px-6 py-3.5">
                  Customer Name
                </th>
                <th scope="col" className="px-6 py-3.5">
                  Amount
                </th>
                <th scope="col" className="px-6 py-3.5">
                  Status
                </th>
                <th scope="col" className="px-6 py-3.5">
                  Created Date
                </th>
                <th scope="col" className="px-6 py-3.5 text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 text-sm">
              {claims.map((claim) => (
                <tr
                  key={claim.id}
                  className="hover:bg-slate-50/80 transition-colors group cursor-pointer"
                >
                  <td className="px-6 py-4 font-mono font-medium text-slate-900">
                    <Link
                      to={`/claims/${claim.id}`}
                      className="flex items-center gap-1.5 hover:text-slate-700"
                    >
                      <FileText className="w-4 h-4 text-slate-400 group-hover:text-slate-600 transition-colors" />
                      #{claim.id}
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-slate-800 font-medium">
                    {claim.customerName}
                  </td>
                  <td className="px-6 py-4 font-mono text-slate-900 font-semibold">
                    {formatAmount(claim.amount)}
                  </td>
                  <td className="px-6 py-4">
                    <StatusBadge status={claim.status} />
                  </td>
                  <td className="px-6 py-4 text-slate-500 text-xs font-mono">
                    {claim.createdAt}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="inline-flex items-center gap-3">
                      <Link
                        to={`/claims/${claim.id}`}
                        className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 group-hover:text-slate-900 transition-colors"
                      >
                        View Details
                        <ChevronRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-700 transition-colors" />
                      </Link>

                      <button
                        onClick={(e) => handleOpenDeleteModal(e, claim.id, claim.customerName)}
                        disabled={deletingId === claim.id}
                        title="Delete Claim from Database"
                        className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors disabled:opacity-50 cursor-pointer"
                      >
                        {deletingId === claim.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-rose-600" />
                        ) : (
                          <Trash2 className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Confirmation Modal for Single Claim Deletion */}
      {claimToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-slate-200 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start gap-4">
              <div className="p-3 bg-rose-50 text-rose-600 rounded-xl shrink-0">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-slate-900">
                  Delete Claim #{claimToDelete.id}?
                </h3>
                <p className="text-sm text-slate-500 mt-1">
                  Are you sure you want to delete the claim for <strong className="text-slate-800">{claimToDelete.name}</strong>?
                </p>
                <p className="text-xs text-rose-600 mt-2 bg-rose-50 p-2.5 rounded-lg border border-rose-100">
                  This permanently removes the claim record, uploaded PDFs, extracted fields, and rule evaluation results from the database.
                </p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setClaimToDelete(null)}
                disabled={Boolean(deletingId)}
                className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={Boolean(deletingId)}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow-xs transition-colors disabled:opacity-50 cursor-pointer"
              >
                {deletingId ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Delete Claim
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
