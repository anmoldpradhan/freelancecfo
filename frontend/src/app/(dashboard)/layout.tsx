"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { Toaster } from "sonner";

interface PaymentNotification {
  amount: number;
  currency: string;
  description: string;
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [toast, setToast] = useState<PaymentNotification | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      router.push("/login");
      return;
    }

    // Connect to payment WebSocket
    const wsBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
      .replace("http", "ws");
    const ws = new WebSocket(`${wsBase}/ws/payments?token=${token}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "payment_received") {
        setToast({
          amount: data.amount,
          currency: data.currency,
          description: data.description,
        });
        // Auto-dismiss after 5 seconds
        setTimeout(() => setToast(null), 5000);
      }
    };

    return () => ws.close();
  }, [router]);

  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <div className="p-8">{children}</div>
      </main>
      <Toaster position="top-right" richColors />

      {/* Payment toast */}
      {toast && (
        <div
          className="fixed bottom-6 right-6 bg-green-600 text-white
                     rounded-xl shadow-lg px-5 py-4 flex items-center
                     gap-3 animate-in slide-in-from-bottom-4 z-50"
        >
          <div className="text-2xl">💰</div>
          <div>
            <p className="font-semibold text-sm">Payment received!</p>
            <p className="text-xs text-green-100">
              {toast.currency} {toast.amount.toFixed(2)} —{" "}
              {toast.description}
            </p>
          </div>
          <button
            onClick={() => setToast(null)}
            className="ml-2 text-green-200 hover:text-white text-lg"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}