"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
    LayoutDashboard,
    ArrowLeftRight,
    FileText,
    Calculator,
    TrendingUp,
    MessageSquare,
    LogOut, Tag, Settings,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";

const navItems = [
    { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
    { href: "/transactions", label: "Transactions", icon: ArrowLeftRight },
    { href: "/categories", label: "Categories", icon: Tag },

    { href: "/invoices", label: "Invoices", icon: FileText },
    { href: "/tax", label: "Tax", icon: Calculator },
    { href: "/forecast", label: "Cash Flow", icon: TrendingUp },
    { href: "/cfo", label: "AI CFO", icon: MessageSquare },
    { href: "/profile", label: "Profile", icon: Settings },
];

export function Sidebar() {
    const pathname = usePathname();
    const { logout } = useAuth();

    return (
        <aside className="hidden md:flex w-64 min-h-screen bg-slate-900 text-white flex-col">
            {/* Logo */}
            <div className="p-6 border-b border-slate-700">
                <h1 className="text-xl font-bold text-violet-400">FreelanceCFO</h1>
                <p className="text-xs text-slate-400 mt-1">AI Financial Assistant</p>
            </div>

            {/* Nav */}
            <nav className="flex-1 p-4 space-y-1">
                {navItems.map(({ href, label, icon: Icon }) => (
                    <Link
                        key={href}
                        href={href}
                        className={cn(
                            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
                            pathname === href
                                ? "bg-violet-600 text-white"
                                : "text-slate-300 hover:bg-slate-800 hover:text-white"
                        )}
                    >
                        <Icon size={18} />
                        {label}
                    </Link>
                ))}
            </nav>

            {/* Logout */}
            <div className="p-4 border-t border-slate-700">
                <button
                    onClick={logout}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-lg
                     text-sm text-slate-300 hover:bg-slate-800
                     hover:text-white w-full transition-colors"
                >
                    <LogOut size={18} />
                    Logout
                </button>
            </div>
        </aside>
    );
}