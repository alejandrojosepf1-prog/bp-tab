"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Gem, Loader2, Mail, Phone, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingState, ErrorState } from "@/components/query-state";

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

export default function AccessRequestPage() {
  const { id } = useParams<{ id: string }>();
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const { data: tournament, isLoading, error: loadError } = useQuery({
    queryKey: queryKeys.tournament(id),
    queryFn: () => api.tournaments.get(id),
    staleTime: 30_000,
  });

  const submitMutation = useMutation({
    mutationFn: () => api.accessPasses.submit(id, { email, phone, full_name: fullName }),
    onSuccess: () => setSubmitted(true),
    onError: (err) =>
      setError(err instanceof ApiError ? err.detail : "No se pudo enviar la solicitud."),
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
            {isLoading ? (
              <div className="py-4">
                <LoadingState label="Cargando torneo…" />
              </div>
            ) : loadError || !tournament ? (
              <ErrorState error={loadError ?? new Error("Torneo no encontrado")} />
            ) : (
              <>
                <CardTitle className="flex items-center justify-center gap-2">
                  <ShieldCheck className="size-4.5 text-primary" />
                  Pedí tu pase
                </CardTitle>
                <CardDescription>
                  Para apostar en <span className="font-medium text-foreground">{tournament.name}</span>{" "}
                  necesitás que un admin apruebe tu acceso. Se juega con tokens — cero dinero real.
                </CardDescription>
              </>
            )}
          </CardHeader>

          {tournament && (
            <CardContent>
              <AnimatePresence mode="wait" initial={false}>
                {submitted ? (
                  <motion.div
                    key="success"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex flex-col items-center gap-3 py-4 text-center"
                  >
                    <span className="flex size-11 items-center justify-center rounded-full bg-primary/15 text-primary">
                      <Sparkles className="size-5" />
                    </span>
                    <p className="text-sm font-medium">Solicitud enviada</p>
                    <p className="text-sm text-muted-foreground">
                      Un admin va a revisar tu pase. Cuando lo apruebe, te llega un correo con un
                      link para activar tu cuenta.
                    </p>
                  </motion.div>
                ) : (
                  <motion.form
                    key="form"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      setError(null);
                      submitMutation.mutate();
                    }}
                    className="flex flex-col gap-4"
                  >
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="full_name">
                        <UserRound className="size-3.5" /> Nombre completo
                      </Label>
                      <Input
                        id="full_name"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        placeholder="Como te conocen en el circuito"
                        minLength={2}
                        required
                      />
                    </div>
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="email">
                        <Mail className="size-3.5" /> Correo
                      </Label>
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
                      <Label htmlFor="phone">
                        <Phone className="size-3.5" /> Teléfono
                      </Label>
                      <Input
                        id="phone"
                        type="tel"
                        autoComplete="tel"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        placeholder="+507 6000-0000"
                        required
                      />
                    </div>

                    {error && <p className="text-sm text-destructive">{error}</p>}

                    <Button type="submit" disabled={submitMutation.isPending} className="mt-1">
                      {submitMutation.isPending && <Loader2 className="size-4 animate-spin" />}
                      Enviar solicitud
                    </Button>
                    <p className="text-center text-xs text-muted-foreground">
                      El teléfono se guarda pero no se verifica. Nunca compartimos tus datos.
                    </p>
                  </motion.form>
                )}
              </AnimatePresence>
            </CardContent>
          )}
        </Card>
      </motion.div>
    </div>
  );
}
