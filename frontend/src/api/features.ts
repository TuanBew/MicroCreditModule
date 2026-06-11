import client from './client';

export interface Feature {
  key: string;
  name: string;
  description: string;
  cost: number;
  unlock_package_name: string;
}

export interface FeatureRunResult {
  id: string;
  feature_key: string;
  credits_spent: number;
  result_payload: Record<string, unknown>;
  balance: number;
  created_at: string;
}

export async function listFeatures(): Promise<Feature[]> {
  const res = await client.get<Feature[]>('/api/v1/features');
  return res.data;
}

export async function runFeature(featureKey: string, inputPayload: Record<string, unknown> = {}): Promise<FeatureRunResult> {
  const res = await client.post<FeatureRunResult>(
    `/api/v1/features/${featureKey}/run`,
    { input_payload: inputPayload }
  );
  return res.data;
}
