"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import { saveTokens, clearTokens } from "./api";

interface AuthContextType {
  isAuthenticated: boolean;
  login: (access: string, refresh: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  isAuthenticated: false,
  login: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    // Check on mount — token in localStorage = authenticated
    const token = localStorage.getItem("access_token");
    setIsAuthenticated(!!token);
  }, []);

  const login = (access: string, refresh: string) => {
    saveTokens(access, refresh);
    setIsAuthenticated(true);
  };

  const logout = () => {
    clearTokens();
    setIsAuthenticated(false);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);