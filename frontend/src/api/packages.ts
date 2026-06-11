import client from './client';

export interface Package {
  id: string;
  slug: string;
  name: string;
  badge: string;
  description: string;
  price_cents: number;
  credits: number;
  active: boolean;
  features: string[];
}

export interface PackageCreateInput {
  name: string;
  description: string;
  price_cents: number;
  credits: number;
  features: string[];
  active: boolean;
}

export type PackageUpdateInput = Partial<PackageCreateInput>;

export async function listPackages(): Promise<Package[]> {
  const res = await client.get<Package[]>('/api/v1/packages');
  return res.data;
}

export async function createPackage(data: PackageCreateInput): Promise<Package> {
  const res = await client.post<Package>('/api/v1/packages', data);
  return res.data;
}

export async function updatePackage(id: string, data: PackageUpdateInput): Promise<Package> {
  const res = await client.patch<Package>(`/api/v1/packages/${id}`, data);
  return res.data;
}

export async function deletePackage(id: string): Promise<void> {
  await client.delete(`/api/v1/packages/${id}`);
}
