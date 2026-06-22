import axios from "axios";

function apiBaseUrl(defaultPort) {
  const configured = import.meta.env.VITE_API_URL;
  const browserHost = window.location.hostname;
  if (configured) {
    try {
      const url = new URL(configured);
      if (!["localhost", "127.0.0.1"].includes(browserHost) && ["localhost", "127.0.0.1"].includes(url.hostname)) {
        url.hostname = browserHost;
      }
      return url.toString().replace(/\/$/, "");
    } catch {
      return configured;
    }
  }
  return `${window.location.protocol}//${browserHost}:${defaultPort}`;
}

const api = axios.create({
  baseURL: apiBaseUrl(8020),
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("easysales_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const companyId = localStorage.getItem("easy-active-company-id");
  if (companyId) config.headers["X-Company-Id"] = companyId;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("easysales_token");
      localStorage.removeItem("easysales_user");
      if (!window.location.pathname.includes("/login")) window.location.reload();
    }
    return Promise.reject(error);
  },
);

export default api;
