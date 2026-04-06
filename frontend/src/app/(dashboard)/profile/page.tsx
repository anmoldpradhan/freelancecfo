"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";
import { auth, clearTokens } from "@/lib/api";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ProfilePage() {
    const router = useRouter();
    const [profile, setProfile] = useState({
        trading_name: "",
        base_currency: "GBP",
        vat_registered: false,
        utr_number: "",
        stripe_account_id: "",
        telegram_chat_id: "",
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState("");
    const [deletePassword, setDeletePassword] = useState("");
    const [deleting, setDeleting] = useState(false);

    const headers = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${typeof window !== "undefined"
                ? localStorage.getItem("access_token")
                : ""
            }`,
    };

    useEffect(() => {
        fetch(`${API}/api/v1/profile`, { headers })
            .then((r) => r.json())
            .then((data) => {
                setProfile(data);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, []);

    const handleDeleteAccount = async () => {
        if (!deletePassword) {
            toast.error("Enter your password to confirm deletion");
            return;
        }
        if (!confirm("This will permanently delete your account and ALL your data. This cannot be undone.")) return;
        setDeleting(true);
        try {
            const refresh_token = localStorage.getItem("refresh_token") ?? undefined;
            await auth.deleteAccount(deletePassword, refresh_token);
            clearTokens();
            router.push("/login");
        } catch (err: any) {
            toast.error(err.message ?? "Failed to delete account");
        } finally {
            setDeleting(false);
        }
    };

    const handleSave = async (e: React.SyntheticEvent<HTMLFormElement>) => {
        e.preventDefault();
        setSaving(true);
        setMessage("");
        try {
            const res = await fetch(`${API}/api/v1/profile`, {
                method: "PATCH",
                headers,
                body: JSON.stringify({
                    trading_name: profile.trading_name || null,
                    base_currency: profile.base_currency,
                    vat_registered: profile.vat_registered,
                    utr_number: profile.utr_number || null,
                    telegram_chat_id: profile.telegram_chat_id || null,
                }),
            });
            if (res.ok) {
                setMessage("✅ Profile saved.");
            } else {
                const err = await res.json();
                setMessage(`❌ ${err.detail}`);
            }
        } catch {
            setMessage("❌ Failed to save.");
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return <p className="text-slate-500">Loading profile...</p>;
    }

    return (
        <div className="space-y-6 max-w-2xl">
            <div>
                <h1 className="text-2xl font-bold text-slate-900">Profile</h1>
                <p className="text-slate-500 text-sm">
                    Your business details — used on invoices and tax calculations
                </p>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
                <Card>
                    <CardHeader>
                        <CardTitle className="text-base">Business Details</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-1">
                            <Label>Trading Name</Label>
                            <Input
                                value={profile.trading_name || ""}
                                onChange={(e) =>
                                    setProfile({ ...profile, trading_name: e.target.value })
                                }
                                placeholder="Your business or freelance name"
                            />
                            <p className="text-xs text-slate-400">
                                Appears on invoices and emails
                            </p>
                        </div>

                        <div className="space-y-1">
                            <Label>Base Currency</Label>
                            <select
                                value={profile.base_currency}
                                onChange={(e) =>
                                    setProfile({ ...profile, base_currency: e.target.value })
                                }
                                className="w-full h-9 rounded-md border border-slate-200
                           bg-white px-3 text-sm"
                            >
                                <option value="GBP">GBP — British Pound</option>
                                <option value="EUR">EUR — Euro</option>
                                <option value="USD">USD — US Dollar</option>
                            </select>
                        </div>

                        <div className="flex items-center gap-3">
                            <input
                                type="checkbox"
                                id="vat"
                                checked={profile.vat_registered}
                                onChange={(e) =>
                                    setProfile({
                                        ...profile,
                                        vat_registered: e.target.checked,
                                    })
                                }
                                className="h-4 w-4"
                            />
                            <div>
                                <Label htmlFor="vat">VAT Registered</Label>
                                <p className="text-xs text-slate-400">
                                    Affects VAT threshold warnings
                                </p>
                            </div>
                        </div>
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader>
                        <CardTitle className="text-base">Tax Details</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="space-y-1">
                            <Label>UTR Number</Label>
                            <Input
                                value={profile.utr_number || ""}
                                onChange={(e) =>
                                    setProfile({ ...profile, utr_number: e.target.value })
                                }
                                placeholder="10-digit Unique Taxpayer Reference"
                                maxLength={10}
                            />
                            <p className="text-xs text-slate-400">
                                Stored securely · shown masked
                            </p>
                        </div>

                        {profile.stripe_account_id && (
                            <div className="space-y-1">
                                <Label>Stripe Account</Label>
                                <p className="text-sm text-slate-600 font-mono bg-slate-50
                               border rounded px-3 py-2">
                                    {profile.stripe_account_id}
                                </p>
                                <p className="text-xs text-slate-400">
                                    Connected via Stripe Connect
                                </p>
                            </div>
                        )}
                        <div className="space-y-1">
                            <Label>Telegram Chat ID</Label>
                            <Input
                                value={profile.telegram_chat_id || ""}
                                onChange={(e) =>
                                    setProfile({ ...profile, telegram_chat_id: e.target.value })
                                }
                                placeholder="Find yours by messaging @userinfobot on Telegram"
                            />
                            <p className="text-xs text-slate-400">
                                Links your Telegram account for bot notifications
                            </p>
                        </div>
                    </CardContent>
                </Card>

                {message && (
                    <p className="text-sm text-slate-700 bg-slate-50 border
                         rounded p-3">
                        {message}
                    </p>
                )}

                <Button
                    type="submit"
                    className="bg-violet-600 hover:bg-violet-700"
                    disabled={saving}
                >
                    {saving ? "Saving..." : "Save Profile"}
                </Button>
            </form>

            {/* Danger zone */}
            <Card className="border-red-200">
                <CardHeader>
                    <CardTitle className="text-base text-red-600">Danger Zone</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                    <p className="text-sm text-slate-600">
                        Permanently delete your account and all associated data. This cannot be undone.
                    </p>
                    <div className="space-y-1">
                        <Label>Confirm with your password</Label>
                        <Input
                            type="password"
                            value={deletePassword}
                            onChange={(e) => setDeletePassword(e.target.value)}
                            placeholder="Enter password to confirm"
                        />
                    </div>
                    <Button
                        type="button"
                        variant="outline"
                        className="border-red-300 text-red-600 hover:bg-red-50"
                        disabled={deleting}
                        onClick={handleDeleteAccount}
                    >
                        {deleting ? "Deleting..." : "Delete My Account"}
                    </Button>
                </CardContent>
            </Card>
        </div>
    );
}