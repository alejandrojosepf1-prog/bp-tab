"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Gem, KeyRound, Loader2 } from "lucide-react";
import { api, ApiError, setToken } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Wordmark() {
  return (
    <Link href="/dashboard" className="mx-auto mb-2 flex items-center justify-center gap-2">
      <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Gem className="size-5" strokeWidth={2.4} />
      </span>
      <span className="font-heading text-xl font-bold uppercase tracking-[0.18em]">Claim</span>
    </Link>
  );
}

function ActivateForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const activateMutation = useMutation({
    mutationFn: () => api.accessPasses.activate({ token, password }),
    onSuccess: (data) => {
      setToken(data.access_token);
      router.push("/dashboard");
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.detail : "No se pudo activar la cuenta."),
  });

  return (
    <div className="flex min-h-screen flex-1 items-center justify-center px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="w-full max-w-sm"
      >
        <Card className="shadow-lg">
          <CardHeader className="text-center">
            <Wordmark />
            <CardTitle className="flex items-center justify-center gap-2">
              <KeyRound className="size-4.5 text-primary" />
              Activá tu cuenta
            </CardTitle>
            <CardDescription>
              Tu pase fue aprobado. Elegí una contraseña para entrar.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!token ? (
              <p className="text-center text-sm text-destructive">
                Este link no es válido. Revisá que lo hayas abierto completo desde el correo.
              </p>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  setError(null);
                  if (password !== confirm) {
                    setError("Las contraseñas no coinciden.");
                    return;
                  }
                  activateMutation.mutate();
                }}
                className="flex flex-col gap-4"
              >
                <div className="flex flex-col gap-2">
                  <Label htmlFor="password">Contraseña</Label>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    minLength={8}
                    required
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <Label htmlFor="confirm">Repetí la contraseña</Label>
                  <Input
                    id="confirm"
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="••••••••"
                    minLength={8}
                    required
                  />
                </div>

                {error && <p className="text-sm text-destructive">{error}</p>}

                <Button type="submit" disabled={activateMutation.isPending} className="mt-1">
                  {activateMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                  Activar y entrar
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}

export default function ActivatePage() {
  return (
    <Suspense fallback={null}>
      <ActivateForm />
    </Suspense>
  );
}
