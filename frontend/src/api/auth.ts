import client from './client';

export interface AuthUser {
  id: string;
  email: string;
  role: 'user' | 'admin';
  initials: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export async function signup(email: string, password: string): Promise<AuthResponse> {
  const res = await client.post<AuthResponse>('/api/v1/auth/signup', { email, password });
  return res.data;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await client.post<AuthResponse>('/api/v1/auth/login', { email, password });
  return res.data;
}

export async function getMe(): Promise<AuthUser> {
  const res = await client.get<AuthUser>('/api/v1/auth/me');
  return res.data;
}

export async function logoutApi(): Promise<void> {
  await client.post('/api/v1/auth/logout');
}
