export type ClaimStatus = 'Processing' | 'Approved' | 'Under Review' | 'Rejected';

export interface DocumentItem {
  id: string;
  name: string;
  size: string;
  type: string;
}

export interface Claim {
  id: string; // e.g. "1" or "1001"
  customerName: string;
  amount: number;
  status: ClaimStatus;
  createdAt: string;
  documents: DocumentItem[];
}

export interface BackendClaimResponse {
  id: number;
  customer_name: string;
  claim_amount: string | number;
  status: string;
}

export interface BackendClaimCreatePayload {
  customer_name: string;
  claim_amount: number;
  status?: string;
}

export interface OCRWord {
  text: string;
  confidence?: number | null;
  bounding_box?: [number, number, number, number] | { x0: number; y0: number; x1: number; y1: number } | any | null;
}

export interface OCRLine {
  text: string;
  confidence?: number | null;
  bounding_box?: [number, number, number, number] | { x0: number; y0: number; x1: number; y1: number } | any | null;
  words?: OCRWord[];
}

export interface OCRPage {
  page_number: number;
  width?: number | null;
  height?: number | null;
  raw_text: string;
  lines?: OCRLine[];
}

export interface OCRResult {
  document_id?: number | string | null;
  status: string;
  engine: string;
  engine_version?: string | null;
  created_at?: string | null;
  processing_duration_ms?: number | null;
  processing_metadata?: Record<string, any>;
  pages?: OCRPage[];
  errors?: string[];
}

export interface ClaimDocument {
  id: number;
  claim_id: number;
  document_type: string;
  file_name: string;
  file_path: string;
  ocr_status?: string;
  ocr_result?: OCRResult | null;
}
