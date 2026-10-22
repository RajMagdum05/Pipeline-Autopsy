import { Claim, ClaimStatus, BackendClaimResponse, BackendClaimCreatePayload, ClaimDocument } from '../types/claim';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function formatStatus(rawStatus: string): ClaimStatus {
  const lower = (rawStatus || '').toLowerCase();
  if (lower === 'approved') return 'Approved';
  if (lower === 'under_review' || lower === 'under review') return 'Under Review';
  if (lower === 'rejected') return 'Rejected';
  return 'Processing';
}

function mapBackendClaimToFrontend(backendClaim: BackendClaimResponse): Claim {
  const parsedAmount = typeof backendClaim.claim_amount === 'number'
    ? backendClaim.claim_amount
    : parseFloat(backendClaim.claim_amount) || 0;

  return {
    id: String(backendClaim.id),
    customerName: backendClaim.customer_name,
    amount: parsedAmount,
    status: formatStatus(backendClaim.status),
    createdAt: new Date().toISOString().split('T')[0], // Fallback date if not returned by API
    documents: [],
  };
}

export async function fetchClaims(): Promise<Claim[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: BackendClaimResponse[] = await response.json();
    return data.map(mapBackendClaimToFrontend);
  } catch (error) {
    console.error('Error fetching claims from backend:', error);
    throw new Error('Unable to connect to the claims service.');
  }
}

export async function fetchClaimById(id: string): Promise<Claim> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${id}`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`Claim #${id} not found.`);
      }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: BackendClaimResponse = await response.json();
    return mapBackendClaimToFrontend(data);
  } catch (error) {
    if (error instanceof Error && error.message.includes('not found')) {
      throw error;
    }
    console.error(`Error fetching claim #${id} from backend:`, error);
    throw new Error('Unable to connect to the claims service.');
  }
}

export async function createBackendClaim(payload: BackendClaimCreatePayload): Promise<Claim> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        customer_name: payload.customer_name,
        claim_amount: payload.claim_amount,
        status: payload.status || 'processing',
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: BackendClaimResponse = await response.json();
    return mapBackendClaimToFrontend(data);
  } catch (error) {
    console.error('Error creating claim on backend:', error);
    throw new Error('Unable to connect to the claims service.');
  }
}

export async function getClaimDocuments(claimId: string): Promise<ClaimDocument[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${claimId}/documents`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(`Claim #${claimId} not found.`);
      }
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data: ClaimDocument[] = await response.json();
    return data;
  } catch (error) {
    if (error instanceof Error && error.message.includes('not found')) {
      throw error;
    }
    console.error(`Error fetching documents for claim #${claimId}:`, error);
    throw new Error('Unable to fetch claim documents.');
  }
}

export async function uploadClaimDocument(
  claimId: string,
  file: File,
  documentType: string
): Promise<ClaimDocument> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('document_type', documentType);

    const response = await fetch(`${API_BASE_URL}/claims/${claimId}/documents`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => null);
      if (errJson && errJson.detail) {
        throw new Error(errJson.detail);
      }
      if (response.status === 404) {
        throw new Error(`Claim #${claimId} not found.`);
      }
      throw new Error(`Upload failed with status: ${response.status}`);
    }

    const data: ClaimDocument = await response.json();
    return data;
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    console.error(`Error uploading document for claim #${claimId}:`, error);
    throw new Error('Unable to upload document to backend service.');
  }
}

export async function fetchDocumentOCR(claimId: string, documentId: number) {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${claimId}/documents/${documentId}/ocr`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error(`Error fetching OCR evidence for document #${documentId}:`, error);
    throw new Error('Unable to fetch OCR evidence.');
  }
}

export function getDocumentFileUrl(claimId: string, documentId: number): string {
  return `${API_BASE_URL}/claims/${claimId}/documents/${documentId}/file`;
}

export async function processClaim(claimId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${claimId}/process`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => null);
      throw new Error(errJson?.detail || `Processing failed with status ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    console.error(`Error running pipeline for claim #${claimId}:`, error);
    throw new Error('Unable to execute claim pipeline.');
  }
}

export async function getClaimExecution(claimId: string) {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${claimId}/execution`, {
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      if (response.status === 404) return null;
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error(`Error fetching execution history for claim #${claimId}:`, error);
  }
}

export async function deleteBackendClaim(claimId: string): Promise<void> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims/${claimId}`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => null);
      throw new Error(errJson?.detail || `Failed to delete claim with status ${response.status}`);
    }
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    console.error(`Error deleting claim #${claimId}:`, error);
    throw new Error('Unable to delete claim from backend.');
  }
}

export async function deleteAllBackendClaims(): Promise<void> {
  try {
    const response = await fetch(`${API_BASE_URL}/claims`, {
      method: 'DELETE',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errJson = await response.json().catch(() => null);
      throw new Error(errJson?.detail || `Failed to delete claims with status ${response.status}`);
    }
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    console.error('Error deleting all claims:', error);
    throw new Error('Unable to reset claims in backend.');
  }
}




