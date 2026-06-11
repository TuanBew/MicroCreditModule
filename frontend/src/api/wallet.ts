import client from './client';

export interface WalletFeature {
  key: string;
  name: string;
  description: string;
  cost: number;
  unlock_package_name: string;
  owned: boolean;
}

export interface WalletData {
  balance: number;
  features: WalletFeature[];
}

export interface Purchase {
  id: string;
  package_id: string;
  package_name: string;
  status: string;
  amount_cents: number;
  credits_granted: number;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  delta: number;
  reason: string;
  description: string;
  reference_type: string;
  reference_id: string;
  balance_after: number;
  created_at: string;
}

export async function getWallet(): Promise<WalletData> {
  const res = await client.get<WalletData>('/api/v1/wallet');
  return res.data;
}

export async function getPurchases(): Promise<Purchase[]> {
  const res = await client.get<Purchase[]>('/api/v1/wallet/purchases');
  return res.data;
}

export async function getLedger(): Promise<LedgerEntry[]> {
  const res = await client.get<LedgerEntry[]>('/api/v1/wallet/ledger');
  return res.data;
}
