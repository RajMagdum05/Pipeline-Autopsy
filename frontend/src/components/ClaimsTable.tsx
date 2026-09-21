import React from 'react';
import { Link } from 'react-router-dom';
import { Claim } from '../types/claim';
import { StatusBadge } from './StatusBadge';
import { ChevronRight, FileText } from 'lucide-react';

interface ClaimsTableProps {
  claims: Claim[];
}

export const ClaimsTable: React.FC<ClaimsTableProps> = ({ claims }) => {
  const formatAmount = (num: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(num);
  };

  return (
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
                Action
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
                  <Link
                    to={`/claims/${claim.id}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-slate-600 group-hover:text-slate-900 transition-colors"
                  >
                    View Details
                    <ChevronRight className="w-3.5 h-3.5 text-slate-400 group-hover:text-slate-700 transition-colors" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
