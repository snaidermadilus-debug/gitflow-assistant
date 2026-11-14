import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api";
import { useState } from "react";

interface ApiHealth {
  status: "ok";
}

const INSTALL: Record<string, string[]> = {
  termux: ["pkg install git python", "git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git", "cd gitflow-assistant", "bash scripts/install_termux.sh"],
  linux: ["sudo apt install git python3 python3-venv", "git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git", "cd gitflow-assistant", "sh scripts/install_linux.sh"],
  windows: ["winget install --id Git.Git -e", "git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git", "cd gitflow-assistant", "powershell -ExecutionPolicy Bypass -File scripts\\install_windows.ps1"],
};

const FEATURES = [
  ["Publicação guiada", "init → revisão de arquivos → análise de segredos → commit → remoto → push"],
  ["Atualização segura", "fetch, merge/rebase só com sua escolha e branch de backup; nunca push --force"],
  ["Scanner de segredos", ".env, chaves SSH/PEM, tokens GitHub/AWS/Stripe, senhas e arquivos grandes"],
  ["GitHub", "GitHub CLI, token, SSH ou OAuth Device Flow; cria repositórios públicos e privados"],
  ["IA Gemini", "sugere mensagens de commit e resume alterações, com consentimento e segredos ocultados"],
  ["Multiplataforma", "Termux (Android), Windows 10/11 e Linux — só biblioteca padrão do Python"],
];

const COMMANDS = ["gitflow", "gitflow upload", "gitflow update", "gitflow commit --ai", "gitflow scan", "gitflow doctor", "gitflow --json status"];

export default function Home() {
  const [platform, setPlatform] = useState<keyof typeof INSTALL>("termux");
  const { data: health, isError, isPending, isSuccess } = useQuery({
    queryKey: ["api-health"],
    queryFn: () => apiGet<ApiHealth>("/health"),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
  const apiStatus = isPending
    ? "Verificando a API..."
    : isError
      ? "API indisponível"
      : isSuccess && health.status === "ok"
        ? "API conectada"
        : "API indisponível";

  return (
    <main className="min-h-svh bg-[#0d1110] text-[#d7e3dc]" style={{ fontFamily: "'JetBrains Mono Variable', monospace" }}>
      <div className="mx-auto max-w-5xl px-6 py-16 md:py-24">
        <p className="text-sm text-[#7fd1a3]" data-testid="hero-eyebrow">$ gitflow --version → GitFlow Assistant 1.0.0</p>
        <h1 className="mt-4 max-w-3xl text-4xl font-bold leading-tight md:text-6xl" style={{ fontFamily: "'Space Grotesk Variable', sans-serif" }} data-testid="hero-title">
          Git e GitHub sem decorar comandos.
        </h1>
        <p className="mt-6 max-w-2xl text-base text-[#9fb3a8]" data-testid="hero-description">
          Ferramenta de linha de comando open source (MIT) para publicar, sincronizar e proteger seus projetos — no celular com Termux, no Windows ou no Linux.
        </p>
        <p
          className={`mt-4 flex items-center text-xs ${isError ? "text-rose-300" : isPending ? "text-[#9fb3a8]" : "text-[#7fd1a3]"}`}
          data-testid="api-status"
          role="status"
          aria-live="polite"
        >
          <span
            aria-hidden="true"
            className={`mr-2 inline-block size-2 rounded-full ${isError ? "bg-rose-400" : isPending ? "bg-[#9fb3a8]" : "bg-[#7fd1a3]"}`}
          />
          {apiStatus}
        </p>

        <section className="mt-14 rounded-xl border border-[#25332c] bg-[#111a16]/80 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.8)] backdrop-blur" data-testid="install-section">
          <div className="flex gap-1 border-b border-[#25332c] p-2">
            {Object.keys(INSTALL).map((key) => (
              <button
                key={key}
                type="button"
                data-testid={`install-tab-${key}`}
                onClick={() => setPlatform(key as keyof typeof INSTALL)}
                className={`rounded-md px-3 py-1.5 text-sm transition-colors duration-150 ${platform === key ? "bg-[#7fd1a3] text-[#0d1110]" : "text-[#9fb3a8] hover:bg-[#1b2822]"}`}
              >
                {key === "termux" ? "Termux" : key === "linux" ? "Linux" : "Windows"}
              </button>
            ))}
          </div>
          <pre className="overflow-x-auto p-5 text-sm leading-7" data-testid="install-commands">
            {INSTALL[platform].map((line) => (
              <div key={line}><span className="text-[#7fd1a3]">$ </span>{line}</div>
            ))}
          </pre>
        </section>

        <section className="mt-16 grid gap-x-10 gap-y-8 md:grid-cols-2" data-testid="features-section">
          {FEATURES.map(([title, text]) => (
            <div key={title} className="border-l-2 border-[#7fd1a3]/40 pl-4">
              <h2 className="text-lg font-semibold text-white" style={{ fontFamily: "'Space Grotesk Variable', sans-serif" }}>{title}</h2>
              <p className="mt-1 text-sm text-[#9fb3a8]">{text}</p>
            </div>
          ))}
        </section>

        <section className="mt-16" data-testid="commands-section">
          <h2 className="text-sm uppercase tracking-widest text-[#7fd1a3]">Comandos</h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {COMMANDS.map((cmd) => (
              <code key={cmd} className="rounded-md border border-[#25332c] bg-[#111a16] px-3 py-1.5 text-sm">{cmd}</code>
            ))}
          </div>
        </section>

        <p className="mt-16 text-xs text-[#6b7f74]" data-testid="footer-note">
          O código-fonte completo está em <code>/gitflow-assistant</code> deste projeto: README, documentação, instaladores e testes.
        </p>
      </div>
    </main>
  );
}
