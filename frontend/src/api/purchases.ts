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

export async function createPurchase(packageId: string): Promise<PurchaseResult> {
  const idempotencyKey = crypto.randomUUID();
  const res = await client.post<PurchaseResult>(
    '/api/v1/purchases',
    { package_id: packageId },
    { headers: { 'Idempotency-Key': idempotencyKey } }
  );
  return res.data;
}
