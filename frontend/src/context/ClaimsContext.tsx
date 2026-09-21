import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { Claim } from '../types/claim';
import { fetchClaims, fetchClaimById, createBackendClaim, uploadClaimDocument } from '../api/claims';

interface CreateClaimInput {
  customerName: string;
  amount: number;
  files?: File[];
}

interface ClaimsContextType {
  claims: Claim[];
  loading: boolean;
  error: string | null;
  isCreating: boolean;
  refreshClaims: () => Promise<void>;
  addClaim: (input: CreateClaimInput) => Promise<Claim>;
  getClaim: (id: string) => Promise<Claim | undefined>;
}

const ClaimsContext = createContext<ClaimsContextType | undefined>(undefined);

export const ClaimsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState<boolean>(false);

  const refreshClaims = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchClaims();
      setClaims(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to connect to the claims service.';
      setError(msg);
      setClaims([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshClaims();
  }, [refreshClaims]);

  const addClaim = async (input: CreateClaimInput): Promise<Claim> => {
    setIsCreating(true);
    setError(null);
    try {
      const newClaim = await createBackendClaim({
        customer_name: input.customerName,
        claim_amount: input.amount,
        status: 'processing',
      });

      if (input.files && input.files.length > 0) {
        for (const file of input.files) {
          await uploadClaimDocument(newClaim.id, file, 'Medical Report');
        }
      }

      // Update local state with newly created claim
      setClaims(prev => [...prev, newClaim]);
      return newClaim;
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unable to connect to the claims service.';
      setError(msg);
      throw err;
    } finally {
      setIsCreating(false);
    }
  };

  const getClaim = async (id: string): Promise<Claim | undefined> => {
    // Check local memory first
    const existing = claims.find(c => c.id === id);
    if (existing) return existing;

    // Otherwise fetch directly from backend GET /claims/{id}
    try {
      return await fetchClaimById(id);
    } catch (err) {
      console.error(`Error fetching claim ${id}:`, err);
      return undefined;
    }
  };

  return (
    <ClaimsContext.Provider
      value={{
        claims,
        loading,
        error,
        isCreating,
        refreshClaims,
        addClaim,
        getClaim,
      }}
    >
      {children}
    </ClaimsContext.Provider>
  );
};

export const useClaims = (): ClaimsContextType => {
  const context = useContext(ClaimsContext);
  if (!context) {
    throw new Error('useClaims must be used within a ClaimsProvider');
  }
  return context;
};
