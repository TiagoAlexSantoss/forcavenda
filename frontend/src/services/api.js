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
  const companyId = localStorage.getItem("easy-active-company-id");
  if (companyId) config.headers["X-Company-Id"] = companyId;
  return config;
});

export default api;
