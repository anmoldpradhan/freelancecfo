"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const fn = isRegister ? auth.register : auth.login;
      const data = await fn(email, password);
      login(data.access_token, data.refresh_token);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl text-violet-600">
            FreelanceCFO
          </CardTitle>
          <CardDescription>
            {isRegister
              ? "Create your account"
              : "Sign in to your dashboard"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={
                  isRegister
                    ? "Min 8 chars, 1 uppercase, 1 number"
                    : "Your password"
                }
                required
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 bg-red-50
                            border border-red-200 rounded p-2">
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="w-full bg-violet-600 hover:bg-violet-700"
              disabled={loading}
            >
              {loading
                ? "Please wait..."
                : isRegister
                ? "Create account"
                : "Sign in"}
            </Button>

            <button
              type="button"
              onClick={() => { setIsRegister(!isRegister); setError(""); }}
              className="w-full text-sm text-slate-500 hover:text-slate-700"
            >
              {isRegister
                ? "Already have an account? Sign in"
                : "No account? Register free"}
            </button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}