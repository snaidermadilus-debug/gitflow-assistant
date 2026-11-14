# Arquitetura

## Camadas

```
gitflow_assistant/
├── app.py              bootstrap: configuração, idioma, logging, contexto → runner
├── i18n.py             mensagens (en/pt/es) e detecção de idioma
├── config/defaults.yaml valores padrão (fonte única)
├── core/               núcleo independente de interface (nunca imprime nem pergunta)
│   ├── git_engine.py        subprocess seguro + resultados estruturados
│   ├── project_detector.py  estado de projetos, busca limitada de repositórios
│   ├── repository_manager.py projetos recentes (JSON no diretório de dados)
│   ├── commit_manager.py    commits sem vazio, Conventional Commits
│   ├── sync_manager.py      fetch/ahead-behind, pull seguro, push sem force, abort
│   ├── security_scanner.py  classificação de arquivos (staged/working tree/projeto)
│   ├── github_client.py     API REST v3 (urllib), paginação, rate-limit, device flow
│   ├── gemini_client.py     API Gemini generateContent (urllib), retries
│   └── configuration.py     configuração JSON do usuário sobre defaults, import/export
├── security/           detector de segredos, credenciais, política de confirmação
├── services/           fluxos de uso (upload, update, clone, branch, backup, doctor, ai, history)
│   ├── ui.py                Protocol UserInterface (contrato com qualquer interface)
│   ├── context.py           AppContext: config, UI, stores, fábricas
│   └── errors.py            exceções → códigos de saída
├── interface/          CLI (argparse), handlers, TUI, saída Rich/texto, prompts, logger, runner
└── utils/              SO/Termux, caminhos por plataforma, validadores, templates
```

Por que um pacote `gitflow_assistant/` em vez de `core/`, `interface/`… na raiz (como sugerido no planejamento inicial)? Pacotes de topo com nomes genéricos colidem com outros projetos quando instalados via pip. A divisão interna mantém exatamente as mesmas responsabilidades.

## Decisões

- **Git real via subprocess**, nunca `shell=True`; argumentos validados (sem valores começando com `-`), caminhos depois de `--`, `GIT_TERMINAL_PROMPT=0` em modo não interativo, `LC_ALL=C` para mensagens estáveis, `--porcelain=v1 -z` e formatos com separadores `\x1f`/`\x1e`.
- **Sem dependências obrigatórias**: Rich (visual) e PyYAML são opcionais com fallback real (saída em texto e parser YAML embutido). Isso garante instalação no Termux sem compilação.
- **Serviços falam com o usuário somente via `UserInterface`**, o que permite o mesmo fluxo na CLI, no menu e em testes (FakeUI).
- **Confirmações**: `ConfirmationPolicy` — operações normais aceitam `--yes`; operações arriscadas exigem digitar a palavra de confirmação ou `--yes --allow-risky` em scripts.
- **Recuperação sem perda**: merge/rebase só após branch `gitflow-backup/<branch>-<data>`; trocas de branch com stash; `abort` restaura o estado anterior; nada de reset/clean.
- **Credenciais**: ordem sessão → env → keyring → `gh auth token` → `git credential fill`; nunca persistidas em texto puro.
- **Privacidade da IA**: diff higienizado (arquivos sensíveis fora, linhas com segredos ocultadas, limite de tamanho) e consentimento antes do envio.

## Códigos de saída

0 sucesso · 1 falha · 2 uso/validação · 3 Git ausente · 4 sem repositório · 5 cancelado · 6 bloqueio de segurança · 7 remoto/autenticação/IA · 130 interrompido.

## Testes

`tests/` usa repositórios temporários, HOME/config isolados (`GIT_CONFIG_GLOBAL`, `GITFLOW_HOME`), remotos bare locais e transportes HTTP falsos para GitHub/Gemini. Testes com internet são marcados `network` e só rodam com `GITFLOW_NETWORK_TESTS=1`.
