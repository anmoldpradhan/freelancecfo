"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { Sidebar } from "@/components/sidebar";
import { Toaster } from "sonner";
import { LayoutDashboard, ArrowLeftRight, FileText, TrendingUp, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";

const mobileNav = [
  { href: "/dashboard", icon: LayoutDashboard, label: "Overview" },
  { href: "/transactions", icon: ArrowLeftRight, label: "Transactions" },
  { href: "/invoices", icon: FileText, label: "Invoices" },
  { href: "/forecast", icon: TrendingUp, label: "Forecast" },
  { href: "/cfo", icon: MessageSquare, label: "CFO" },
];

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
  const pathname = usePathname();
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
        <div className="p-4 md:p-8 pb-20 md:pb-8">{children}</div>
      </main>
      <Toaster position="top-right" richColors />

      {/* Mobile bottom nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 flex z-40">
        {mobileNav.map(({ href, icon: Icon, label }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex-1 flex flex-col items-center justify-center py-2 text-xs gap-1 transition-colors",
              pathname === href
                ? "text-violet-600"
                : "text-slate-400 hover:text-slate-700"
            )}
          >
            <Icon size={20} />
            <span>{label}</span>
          </Link>
        ))}
      </nav>

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