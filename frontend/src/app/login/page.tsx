"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/auth-context";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function LoginPage() {
  const router = useRouter();
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, displayName);
      }
      toast.success(mode === "login" ? "Sesión iniciada" : "Cuenta creada");
      router.push("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : "No se pudo completar la operación."
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-12">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="w-full max-w-sm"
      >
        <Card className="shadow-lg">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 text-2xl font-bold tracking-tight">BP$</div>
            <CardTitle>{mode === "login" ? "Iniciar sesión" : "Crear cuenta"}</CardTitle>
            <CardDescription>
              {mode === "login"
                ? "Entra con tu correo y contraseña para ver el torneo."
                : "Crea tu cuenta para empezar a predecir con tus amigos."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <AnimatePresence initial={false}>
                {mode === "register" && (
                  <motion.div
                    key="display-name"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="overflow-hidden"
                  >
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="display_name">Nombre</Label>
                      <Input
                        id="display_name"
                        value={displayName}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="Cómo te vamos a mostrar"
                        required
                      />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="flex flex-col gap-2">
                <Label htmlFor="email">Correo</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="tu@email.com"
                  required
                />
              </div>

              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Contraseña</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  minLength={8}
                />
              </div>

              {error && (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}

              <Button type="submit" disabled={isSubmitting} className="mt-1">
                {isSubmitting && <Loader2 className="size-4 animate-spin" />}
                {mode === "login" ? "Entrar" : "Crear cuenta"}
              </Button>
            </form>

            <p className="mt-4 text-center text-sm text-muted-foreground">
              {mode === "login" ? "¿No tienes cuenta?" : "¿Ya tienes cuenta?"}{" "}
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setMode(mode === "login" ? "register" : "login");
                }}
                className="font-medium text-foreground underline underline-offset-4 hover:no-underline"
              >
                {mode === "login" ? "Crear una" : "Inicia sesión"}
              </button>
            </p>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
