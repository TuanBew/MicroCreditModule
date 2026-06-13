import client from './client';

export interface PurchaseTransaction {
  id: string;
  package_name: string;
  status: string;
  amount_cents: number;
  credits_granted: number;
  created_at: string;
}

export interface PurchaseResult {
  transaction: PurchaseTransaction;
  balance: number;
  newly_unlocked: string[];
  entitlements: string[];
}

/** Returned by POST /purchases (202 Accepted) in the async flow. */
export interface PurchaseAccepted {
  transaction_id: string;
  status: string;
}

/** Returned by GET /purchases/:id/status for polling. */
export interface TransactionStatus {
  transaction_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  balance?: number;
  entitlements?: string[];
  failure_reason?: string;
}

export async function createPurchase(packageId: string): Promise<PurchaseAccepted> {
  const idempotencyKey = crypto.randomUUID();
  const res = await client.post<PurchaseAccepted>(
    '/api/v1/purchases',
    { package_id: packageId },
    { headers: { 'Idempotency-Key': idempotencyKey } }
  );
  return res.data;
}

export async function getPurchaseStatus(transactionId: string): Promise<TransactionStatus> {
  const res = await client.get<TransactionStatus>(`/api/v1/purchases/${transactionId}/status`);
  return res.data;
}
