import { Claim } from '../types/claim';

export const SAMPLE_CLAIMS: Claim[] = [
  {
    id: '1001',
    customerName: 'Rahul Sharma',
    amount: 75000,
    status: 'Processing',
    createdAt: '2026-09-14',
    documents: [
      { id: 'doc-1', name: 'Medical Report.pdf', size: '1.2 MB', type: 'application/pdf' },
      { id: 'doc-2', name: 'Hospital Bill.pdf', size: '450 KB', type: 'application/pdf' },
      { id: 'doc-3', name: 'Insurance Policy.pdf', size: '2.1 MB', type: 'application/pdf' },
    ],
  },
  {
    id: '1002',
    customerName: 'Priya Patil',
    amount: 42500,
    status: 'Approved',
    createdAt: '2026-09-12',
    documents: [
      { id: 'doc-4', name: 'Pharmacy Receipt.pdf', size: '320 KB', type: 'application/pdf' },
      { id: 'doc-5', name: 'Doctor Prescription.pdf', size: '880 KB', type: 'application/pdf' },
    ],
  },
  {
    id: '1003',
    customerName: 'Amit Shah',
    amount: 120000,
    status: 'Under Review',
    createdAt: '2026-09-10',
    documents: [
      { id: 'doc-6', name: 'Surgical Notes.pdf', size: '3.4 MB', type: 'application/pdf' },
      { id: 'doc-7', name: 'Lab Test Results.pdf', size: '1.8 MB', type: 'application/pdf' },
      { id: 'doc-8', name: 'ID Proof.pdf', size: '610 KB', type: 'application/pdf' },
    ],
  },
];
