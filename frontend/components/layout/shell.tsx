"use client";

import { useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { getAuthToken, setAuthToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { LogIn, LogOut, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(Boolean(getAuthToken()));
  }, [pathname]);

  const onLogout = () => {
    setAuthToken(null);
    setAuthed(false);
    router.push("/login");
  };

  return (
    <div className="min-h-screen">
      <div className="flex items-center justify-end gap-2 px-5 py-2 md:px-6">
        <ThemeToggle />
        {authed ? (
          <Button variant="ghost" size="icon" onClick={onLogout} aria-label="Log out">
            <LogOut className="h-4 w-4" />
          </Button>
        ) : (
          <Button variant="ghost" size="sm" asChild>
            <Link href="/login">
              <LogIn className="mr-1 h-4 w-4" /> Sign in
            </Link>
          </Button>
        )}
      </div>
      <main className="px-5 pb-6 md:px-6">{children}</main>
    </div>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" aria-label="Toggle theme">
        <div className="h-4 w-4" />
      </Button>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      aria-label="Toggle theme"
    >
      {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}