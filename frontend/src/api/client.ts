import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '',
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('creditos:token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('creditos:token');
      localStorage.removeItem('creditos:user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default client;
