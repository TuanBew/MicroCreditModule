import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
  withCredentials: true,
});

const getCookie = (name: string): string | null => {
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith(name + '='));
  return match ? decodeURIComponent(match.split('=')[1]) : null;
};

client.interceptors.request.use((config) => {
  const method = config.method?.toUpperCase();
  if (method === 'POST' || method === 'PATCH' || method === 'DELETE') {
    const csrf = getCookie('creditos_csrf_token');
    if (csrf) {
      config.headers['X-CSRF-Token'] = csrf;
    }
  }
  return config;
});

client.interceptors.response.use(
  (r) => r,
  (error) => {
    // /auth/me 401 → AuthContext handles gracefully (no redirect)
    // /auth/login 401 → Login form's catch block shows the error (no redirect)
    const url: string = error.config?.url ?? '';
    const isAuthFlow = url.includes('/auth/me') || url.includes('/auth/login');
    if (error.response?.status === 401 && !isAuthFlow) {
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default client;
