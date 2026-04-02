"use client";

import { SWRConfig } from "swr";
import { AuthProvider } from "@/lib/auth-context";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        dedupingInterval: 30000,
      }}
    >
      <AuthProvider>{children}</AuthProvider>
    </SWRConfig>
  );
}
