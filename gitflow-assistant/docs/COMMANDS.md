# Referência de comandos

Opções globais (podem aparecer em qualquer posição): `-C/--project CAMINHO`, `-y/--yes`, `--allow-risky`, `--batch/--non-interactive`, `--json`, `--lang pt|en|es`, `--no-color`, `-v/--verbose`, `-V/--version`, `-h/--help` (também em cada comando: `gitflow upload --help`).

| Comando | Descrição | Principais opções |
|---|---|---|
| `gitflow` / `gitflow menu` | menu interativo | — |
| `init [CAMINHO]` | inicializa repositório | `--branch`, `--gitignore` |
| `status` | estado do projeto e arquivos | `--fetch` |
| `projects [list\|add\|remove\|scan\|prune]` | projetos recentes | `scan DIR... --depth N --add` |
| `select [CAMINHO]` | define o projeto atual | sem caminho: escolher da lista |
| `upload` (`publish`) `[CAMINHO]` | primeira publicação | `-m`, `--all`, `--files`, `--remote URL`, `--create-github`, `--name`, `--private/--public`, `--description`, `--ssh`, `--accept-findings`, `--no-push`, `--ai` |
| `update` (`sync`) | sincronização completa | `-m`, `--all`, `--files`, `--strategy ff-only\|merge\|rebase`, `--no-push`, `--ai` |
| `clone URL [DESTINO]` | clona e registra | `--branch`, `--depth` |
| `commit` | revisão + análise + commit | `-m`, `--all`, `--files`, `--type feat --scope cli`, `--ai` |
| `push` | envia (nunca force) | — |
| `pull` | recebe alterações | `--strategy` |
| `abort` | aborta merge/rebase em andamento | — |
| `branch [list\|create\|switch\|delete\|rename]` | branches | `create NOME --from REF --switch`, `switch NOME --stash\|--carry` |
| `history [log\|ops\|publications]` (`log`) | histórico | `-n`, `--file`, `--ref` |
| `diff [REF [REF]]` | diferenças | `--staged`, `--stat`, `--files` |
| `scan` | análise de segredos | `--staged`, `--show-ignored`, `--mark-false-positive FP...` |
| `untrack CAMINHO...` | parar de rastrear (mantém no disco) | `--delete` (arriscado) |
| `remote [list\|set\|remove]` | remotos | `set origin URL` |
| `github [status\|login\|logout\|repos\|create\|info\|describe\|branches\|commits]` (`gh`) | GitHub | `login --device\|--token-stdin --store`, `create NOME --private --set-remote` |
| `ai [status\|login\|logout\|models\|commit-message\|summary\|chat]` | IA Gemini | `login --key-stdin --store`, `summary [REF REF] --staged`, `chat` (loop interativo) |
| `gitignore` | gera/completa `.gitignore` | `--print`, `--language python node` |
| `readme` | gera `README.md` | `--description`, `--print`, `--overwrite` |
| `backup [create\|list]` | backup seguro (bundle + zip) | — |
| `doctor` | diagnóstico | `--offline` |
| `config [show\|path\|get\|set\|unset\|reset\|export\|import\|alias\|unalias]` | configurações | `set CHAVE VALOR`, `alias NOME COMANDO...` |

## Automação

```bash
# CI: falhar se houver segredos no que está staged
gitflow --batch scan --staged || exit 1
# publicar sem perguntas (operações normais), arquivos explícitos
gitflow --batch --yes upload --files src README.md -m "chore: release" --remote git@github.com:me/app.git
# saída JSON para scripts
gitflow --json status | python -c "import json,sys; print(json.load(sys.stdin)['state'])"
```

Em modo `--batch`, qualquer dado ausente gera erro de uso (código 2) em vez de uma pergunta; operações arriscadas exigem `--yes --allow-risky`; enviar código à IA exige `--yes`.

No chat (`gitflow ai chat` ou menu **[15]**), `/sair` encerra, `/limpar` reinicia o histórico em memória, `/arquivo CAMINHO` envia um arquivo permitido, e `/repo`, `/status` e `/diff` fornecem contexto filtrado do projeto.

## Principais chaves de configuração

`language`, `theme` (auto/color/plain), `projects_dir`, `editor`, `default_branch`, `default_remote`, `git.user_name`, `git.user_email`, `commit.style` (conventional/free), `commit.default_message`, `confirm.mode` (always/risky), `timeouts.git`, `timeouts.network`, `scan.max_depth`, `security.block_secrets`, `security.max_file_size_mb`, `security.exclude_patterns`, `security.allow_patterns`, `github.oauth_client_id`, `github.default_private`, `ai.enabled`, `ai.model`, `ai.confirm_send`, `ai.max_diff_kb`, `ai.summary_before_commit`, `aliases.*`.
