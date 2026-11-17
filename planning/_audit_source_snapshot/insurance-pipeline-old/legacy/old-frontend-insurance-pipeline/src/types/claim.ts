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

export interface RuleResult {
  rule_id: string;
  rule_name: string;
  input_values: Record<string, any>;
  expected_condition: string;
  actual_value: any;
  result: 'PASS' | 'FAIL' | 'MISSING_DATA';
  reason: string;
}

export interface RuleEngineDecision {
  claim_id: number | string;
  execution_id: string;
  decision: 'APPROVED' | 'REJECTED' | 'FLAGGED_FOR_REVIEW' | string;
  decision_reason: string;
  total_rules: number;
  passed_rules: number;
  failed_rules: number;
  missing_data_rules: number;
  evaluated_rules: RuleResult[];
  created_at?: string | null;
}

export interface ExtractedBillItem {
  description: string;
  amount: number;
  category?: string;
}

export interface ExtractedClaimData {
  patient_name?: string | null;
  patient_id?: string | null;
  policy_number?: string | null;
  hospital_name?: string | null;
  admission_date?: string | null;
  discharge_date?: string | null;
  diagnosis?: string | null;
  diagnosis_code?: string | null;
  total_bill_amount?: number | null;
  claimed_amount?: number | null;
  bill_items?: ExtractedBillItem[];
  pre_existing_conditions?: string[] | null;
  source_references?: Record<string, { document_id: number | string; page_number: number }>;
  [key: string]: any;
}

export interface ValidatedExtractionResult {
  claim_id: number | string;
  execution_id: string;
  source_document_ids?: number[];
  extraction_prompt_version?: string;
  extraction_model?: string;
  extraction_status: 'SUCCESS' | 'VALIDATION_ERROR' | 'API_ERROR' | 'NONE';
  extracted_data?: ExtractedClaimData | null;
  validation_errors?: string[] | null;
}

export interface PipelineExecutionResponse {
  claim_id: number;
  customer_name: string;
  status: string;
  total_documents?: number;
  total_pages?: number;
  extraction?: ValidatedExtractionResult | null;
  decision?: RuleEngineDecision | null;
}

