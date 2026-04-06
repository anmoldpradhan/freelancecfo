/**
 * Thin wrapper around fetch that:
 * - Adds Authorization header from localStorage
 * - Handles 401 → redirect to login
 * - Returns typed responses
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token");
}

export function saveTokens(access: string, refresh: string) {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
}

export function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // Auto-redirect on auth failure
  if (response.status === 401 || response.status === 403) {
    clearTokens();
    window.location.href = "/login";
    throw new ApiError(response.status, "Unauthorized");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      error.detail || "Request failed"
    );
  }

  // 204 No Content
  if (response.status === 204) return null as T;

  return response.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export const auth = {
  register: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>(
      "/api/v1/auth/register",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }
    ),

  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>(
      "/api/v1/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }
    ),

  logout: (refresh_token: string) =>
    request("/api/v1/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token }),
    }),

  deleteAccount: (password: string, refresh_token?: string) =>
    request<null>("/api/v1/auth/account", {
      method: "DELETE",
      body: JSON.stringify({ password, refresh_token }),
    }),
};

// ── Transactions ──────────────────────────────────────────────────────────────

export const transactions = {
  list: (params?: {
    page?: number;
    date_from?: string;
    date_to?: string;
    source?: string;
  }) => {
    const qs = new URLSearchParams(
      Object.entries(params || {})
        .filter(([, v]) => v != null)
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request<Transaction[]>(
      `/api/v1/transactions${qs ? `?${qs}` : ""}`
    );
  },

  create: (data: Partial<Transaction>) =>
    request<Transaction>("/api/v1/transactions", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  update: (id: string, data: Partial<Pick<Transaction, "date" | "description" | "amount" | "notes" | "category_id">>) =>
    request<Transaction>(`/api/v1/transactions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  delete: (id: string) =>
    request<null>(`/api/v1/transactions/${id}`, { method: "DELETE" }),

  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const token = getToken();
    return fetch(`${API_BASE}/api/v1/transactions/import/csv`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    }).then((r) => r.json());
  },
};

// ── Invoices ──────────────────────────────────────────────────────────────────

export const invoices = {
  list: (status?: string) =>
    request<Invoice[]>(
      `/api/v1/invoices${status ? `?status=${status}` : ""}`
    ),

  create: (data: InvoiceCreate) =>
    request<Invoice>("/api/v1/invoices", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  updateStatus: (id: string, status: string) =>
    request<Invoice>(`/api/v1/invoices/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),

  send: (id: string) =>
    request(`/api/v1/invoices/${id}/send`, { method: "POST" }),

  void: (id: string) =>
    request<Invoice>(`/api/v1/invoices/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status: "void" }),
    }),

  downloadPdf: async (id: string, filename: string) => {
    const token = getToken();
    const response = await fetch(`${API_BASE}/api/v1/invoices/${id}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (response.status === 401 || response.status === 403) {
      clearTokens();
      window.location.href = "/login";
      return;
    }
    if (!response.ok) throw new ApiError(response.status, "Failed to download PDF");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};

// ── Tax ───────────────────────────────────────────────────────────────────────

export const tax = {
  estimate: () => request<TaxEstimate>("/api/v1/tax/estimate"),
  breakdown: () => request<TaxBreakdown>("/api/v1/tax/breakdown"),
};

// ── Forecast ──────────────────────────────────────────────────────────────────

export const forecast = {
  cashflow: () => request<CashflowForecast>("/api/v1/forecast/cashflow"),
  vat: () => request<VatForecast>("/api/v1/forecast/vat"),
};

// ── CFO ───────────────────────────────────────────────────────────────────────

export const cfo = {
  chat: (message: string, conversation_id?: string) =>
    request<{ response: string; conversation_id: string }>(
      "/api/v1/cfo/chat",
      {
        method: "POST",
        body: JSON.stringify({ message, conversation_id }),
      }
    ),

  history: () =>
    request<CFOConversation[]>("/api/v1/cfo/history"),

  clearHistory: () =>
    request("/api/v1/cfo/history", { method: "DELETE" }),
};

// ── WebSocket CFO (streaming) ─────────────────────────────────────────────────

export function createCFOWebSocket(token: string): WebSocket {
  const wsBase = API_BASE.replace("http", "ws");
  return new WebSocket(`${wsBase}/ws/cfo/chat?token=${token}`);
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  currency: string;
  category_id: string | null;
  confidence: number | null;
  source: string;
  is_confirmed: boolean;
  notes: string | null;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  client_name: string;
  client_email: string | null;
  line_items: LineItem[];
  subtotal: number;
  tax_rate: number;
  total: number;
  currency: string;
  status: string;
  issued_date: string | null;
  due_date: string | null;
  paid_date: string | null;
  pdf_s3_key: string | null;
}

export interface InvoiceCreate {
  client_name: string;
  client_email?: string;
  line_items: LineItem[];
  tax_rate: number;
  currency?: string;
  issued_date?: string;
  due_date?: string;
  send_immediately?: boolean;
}

export interface LineItem {
  description: string;
  quantity: number;
  unit_price: number;
}

export interface TaxEstimate {
  tax_year: string;
  gross_income: number;
  allowable_expenses: number;
  net_profit: number;
  income_tax: number;
  ni_class2: number;
  ni_class4: number;
  total_ni: number;
  total_liability: number;
  effective_rate_pct: number;
  set_aside_recommended: number;
}

export interface TaxBreakdown {
  tax_year: string;
  income_summary: {
    gross_income: number;
    allowable_expenses: number;
    net_profit: number;
  };
  income_tax: {
    personal_allowance: number;
    taxable_income: number;
    basic_rate_20pct: number;
    higher_rate_40pct: number;
    additional_rate_45pct: number;
    total: number;
  };
  national_insurance: {
    class2_flat_rate: number;
    class4_9pct_band: number;
    class4_2pct_above_upper: number;
    total: number;
  };
  total_liability: number;
  effective_rate_pct: number;
  payments_on_account: {
    january_31: number;
    july_31: number;
    note: string;
  };
}

export interface CashflowForecast {
  generated_at: string;
  summary: string;
  averages: {
    weekly_income: number;
    weekly_expenses: number;
    weekly_net: number;
  };
  current_balance_proxy: number;
  weeks: WeekForecast[];
}

export interface WeekForecast {
  week_start: string;
  week_end: string;
  projected_income: number;
  projected_expenses: number;
  net: number;
  cumulative_balance: number;
  confidence: number;
  alert: string;
}

export interface VatForecast {
  rolling_12m_income: number;
  vat_threshold: number;
  percentage_used: number;
  amount_remaining: number;
  warning_level: string;
  alert_message: string;
  vat_registered: boolean;
  registration_deadline_note: string | null;
}

export interface CFOConversation {
  conversation_id: string;
  messages: CFOMessage[];
  created_at: string;
  updated_at: string;
}

export interface CFOMessage {
  role: string;
  content: string;
  timestamp?: string;
}

// ── Categories ────────────────────────────────────────────────────────────────

export interface Category {
  id: string;
  name: string;
  type: "income" | "expense";
  is_system: boolean;
}

export const categories = {
  list: () => request<Category[]>("/api/v1/transactions/categories"),

  create: (name: string, type: "income" | "expense") =>
    request<Category>("/api/v1/transactions/categories", {
      method: "POST",
      body: JSON.stringify({ name, type }),
    }),
};