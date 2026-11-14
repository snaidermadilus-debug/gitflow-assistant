# Segurança no GitFlow Assistant

## O que é analisado antes de publicar

O `upload`, `update` e `commit` analisam o **conteúdo staged** (exatamente o que irá para o commit), não apenas os nomes:

- **Nomes**: `.env*` (exceto `.env.example/.sample/.template`), `id_rsa`, `id_ed25519`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `.netrc`, `.git-credentials`, `.npmrc`, `.pypirc`, `credentials*`, `*.tfstate`, bancos (`*.db`, `*.sqlite`), backups (`*.bak`, `*.old`, `*~`, `*.swp`).
- **Conteúdo**: blocos de chave privada, tokens GitHub (`ghp_`, `github_pat_`…), AWS, Google API, Slack, Stripe live, OpenAI, bots do Telegram, credenciais em URLs, JWT e atribuições como `password = "..."` (com descarte de placeholders e cálculo de entropia).
- **Tamanho**: arquivos acima de `security.max_file_size_mb` (padrão 50 MB). O conteúdo é lido em blocos até `security.max_content_scan_kb`; binários são verificados só por nome e tamanho.

## Categorias

| Categoria | Significado | Efeito |
|---|---|---|
| ignorado | coberto por `.gitignore` ou `security.exclude_patterns` | não será enviado |
| suspeito | heurística de média confiança | exige revisão |
| segredo | alta confiança | bloqueia (com `security.block_secrets=true`) até decisão explícita |
| falso positivo | revisado e descartado (impressão digital salva) | não bloqueia |
| permitido | casa com `security.allow_patterns` | não bloqueia |

Para cada achado: **excluir do commit** (o arquivo fica no disco), **marcar falso positivo** ou **manter** (segredos exigem digitar a confirmação). Em scripts, achados suspeitos podem ser aceitos com `--accept-findings`; segredos confirmados continuam bloqueados.

> A análise é heurística. Um resultado limpo **não garante** ausência de segredos.

## Credenciais

- Ordem de busca: sessão → `GITHUB_TOKEN`/`GH_TOKEN` → keyring do sistema (opcional) → `gh auth token` → `git credential fill`.
- Tokens nunca aparecem completos (mascarados), nunca vão para logs (filtro de redação) nem para arquivos de configuração (chaves com nomes de segredo são rejeitadas e removidas em exportações).
- Sem backend seguro (comum no Termux), o GitFlow **não** salva o token: use `gh auth login`, SSH ou variáveis de ambiente.

## Operações arriscadas

Nunca automáticas: `reset --hard`, `clean`, `push --force` não existem na ferramenta. Exclusão de arquivos do disco (`untrack --delete`), exclusão de branches (somente mesclados, `-d`) e sobrescrita de README exigem explicação + confirmação digitada (ou `--yes --allow-risky`).

## IA

O diff só é enviado ao Gemini com consentimento; arquivos sensíveis são omitidos e linhas com possíveis segredos substituídas por `[REDACTED]`.
