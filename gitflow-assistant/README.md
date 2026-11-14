# GitFlow Assistant

**Gerenciador universal, seguro e multiplataforma de Git e GitHub para o Shell** — Android (Termux), Windows 10/11 e Linux.

Publique seu primeiro projeto sem decorar dezenas de comandos, ou automatize operações complexas por scripts. Tudo funciona localmente, sem conta paga, servidor ou banco de dados; recursos do GitHub e da IA avisam claramente quando precisam de internet.

> 🇬🇧 English: the interface is available in Portuguese, English and Spanish (`gitflow --lang en`). Documentation is in Portuguese; command help (`gitflow --help`) follows the selected language.

## Funcionalidades

| Área | O que faz |
|---|---|
| Projetos | seleciona pastas, detecta repositórios (busca com profundidade limitada), lista projetos recentes com estado (limpo, pendente, à frente, atrás, divergente, conflito) |
| Publicação | `upload`: init → revisão dos arquivos → análise de segredos do conteúdo *staged* → commit → remoto (URL ou criação no GitHub) → push → URL final |
| Atualização | `update`: fetch → resumo local/remoto → commit seletivo → integração (fast-forward; merge/rebase só com escolha explícita e branch de backup) → push → verificação |
| Segurança | detecção de `.env`, chaves SSH/PEM, tokens (GitHub, AWS, Google, Slack, Stripe, OpenAI…), senhas, arquivos grandes/backup; categorias *ignorado / suspeito / segredo / falso positivo / permitido* |
| GitHub | autenticação (GitHub CLI, `GITHUB_TOKEN`, credential helper, keyring, OAuth Device Flow com seu próprio client id), repositórios públicos/privados, info, descrição, branches, commits, permissões, limite de API |
| IA (Gemini) | sugestão de mensagem de commit e resumo das alterações em linguagem simples — com sua própria chave, consentimento antes de enviar e remoção de segredos do diff |
| Dia a dia | branches (troca protegida com stash), histórico, diff/comparação de commits, backups (`git bundle` + zip das alterações), gerador de `.gitignore` e `README.md`, diagnóstico (`doctor`), aliases, configurações exportáveis, histórico de operações |
| Interfaces | menu interativo (Rich com fallback em texto puro) e CLI completa com `--json`, `--batch`, códigos de saída |

**Garantias de segurança:** nunca executa `reset --hard`, `clean -fd` ou `push --force`; nunca usa `shell=True`; nunca faz commit vazio; nunca adiciona tudo sem mostrar a lista; tokens são mascarados e removidos dos logs; credenciais nunca são salvas em texto puro.

## Sistemas suportados

- **Android / Termux** (ARM64) — tratado como plataforma principal, sem dependências compiladas.
- **Windows 10 e 11** — PowerShell 5.1+/7, instalação no perfil do usuário (sem administrador).
- **Linux** — Debian, Ubuntu, Fedora, Arch e compatíveis; bash, zsh, fish, sh.
- Requisitos: **Python 3.9+** e **Git 2.23+** (recomendado). Rich e PyYAML são opcionais.

## Demonstração

```text
$ gitflow
== GITFLOW ASSISTANT 1.0.0 — Gerenciador Universal de Git e GitHub ==
[i] Projeto: meu-app [main] — alterações pendentes — 3 pendente(s) — ~/meu-app
  [ 1] Gerenciar projetos        [ 8] Comparar alterações
  [ 2] Publicar projeto          [ 9] Segurança e análise
  [ 3] Atualizar projeto         [10] Gerar README
  [ 4] Clonar repositório        [11] Gerar .gitignore
  [ 5] Criar repositório GitHub  [12] Diagnóstico do sistema
  [ 6] Gerenciar branches        [13] Configurações
  [ 7] Histórico e commits       [14] Assistente de IA (Gemini)
  [ 0] Sair
```

## Instalação

### Termux (Android)

```bash
pkg install git python
git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git
cd gitflow-assistant
bash scripts/install_termux.sh
termux-setup-storage   # opcional: acessar /sdcard
```

### Windows (PowerShell)

```powershell
winget install --id Git.Git -e ; winget install Python.Python.3.12
git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git
cd gitflow-assistant
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

### Linux

```bash
sudo apt install git python3 python3-venv     # ou dnf / pacman
git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git
cd gitflow-assistant
sh scripts/install_linux.sh                    # instala em ~/.local (sem root)
```

Também é possível: `pip install --user .` ou rodar direto do código com `python main.py`. Detalhes em [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Exemplos de comandos

```bash
gitflow                                   # menu interativo
gitflow select ~/projetos/meu-app         # define o projeto atual
gitflow status                            # estado do projeto
gitflow upload                            # primeira publicação guiada
gitflow upload --all -m "feat: inicial" --create-github --private --batch
gitflow update                            # sincroniza (commit + pull seguro + push)
gitflow update --strategy rebase --all -m "fix: ajuste" --batch
gitflow commit --files src/ README.md -m "docs: atualiza"
gitflow commit --ai                       # mensagem sugerida pelo Gemini
gitflow scan                              # análise de segredos (exit 6 se houver)
gitflow branch switch feature/x --stash
gitflow history log -n 10 --json
gitflow diff HEAD~3 HEAD --stat
gitflow clone https://github.com/user/repo.git
gitflow doctor
gitflow config set language en
gitflow config alias sp "status --fetch"
```

Referência completa: [docs/COMMANDS.md](docs/COMMANDS.md).

## Configuração do GitHub

O GitFlow funciona sem GitHub para tudo que é local. Para push via HTTPS e para a API, escolha **um** método:

1. **GitHub CLI** (recomendado): `gh auth login` e `gh auth setup-git`.
2. **SSH**: `ssh-keygen -t ed25519`, adicione a chave pública no GitHub e use remotos `git@github.com:usuario/repo.git` (`--ssh`).
3. **Token**: `export GITHUB_TOKEN=...` (ou `gitflow github login`, que valida e mantém o token só na sessão; `--store` salva no keyring do sistema, se existir).
4. **OAuth Device Flow**: registre seu próprio OAuth App, `gitflow config set github.oauth_client_id SEU_ID` e `gitflow github login --device`.

`gitflow github status` mostra a origem da credencial (sempre mascarada).

## IA com Google Gemini (opcional)

1. Crie uma chave gratuita em <https://aistudio.google.com/apikey>.
2. `export GEMINI_API_KEY=...` (Windows: `[Environment]::SetEnvironmentVariable('GEMINI_API_KEY','...','User')`).
3. Use `gitflow commit --ai`, `gitflow ai summary` ou o menu **[14]**.

Modelo padrão: `gemini-3.1-pro-preview` (`gitflow config set ai.model gemini-3.1-flash-lite` para algo mais rápido e barato; `gitflow ai models` lista os disponíveis). Antes de enviar, o GitFlow mostra quais arquivos vão, **exclui arquivos sensíveis** (`.env`, chaves…), **oculta linhas com possíveis segredos** e pede confirmação (`ai.confirm_send`). O código enviado é processado pelo Google conforme os termos da API Gemini.

## Segurança

A análise de segredos é **heurística**: um resultado limpo não é garantia e achados podem ser falsos positivos. Publicações com segredos confirmados são bloqueadas por padrão; para cada achado você decide: excluir do commit, marcar falso positivo ou manter com autorização explícita. Veja [docs/SECURITY.md](docs/SECURITY.md) e [SECURITY.md](SECURITY.md) para relatar vulnerabilidades.

## Contribuições

Contribuições são bem-vindas! Leia [CONTRIBUTING.md](CONTRIBUTING.md) e [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Rode `python -m pytest` antes de abrir um Pull Request.

## Licença

[MIT](LICENSE) — uso, modificação e redistribuição livres, inclusive comercial, mantendo o aviso de copyright. Sem garantias.
