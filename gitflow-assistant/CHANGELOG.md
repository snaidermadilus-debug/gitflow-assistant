# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e [SemVer](https://semver.org/lang/pt-BR/).

## [1.0.0] - 2026-11-14

### Adicionado
- Motor Git seguro (subprocess sem shell, timeouts, porcelain `-z`, redação de credenciais).
- Detecção de projetos, busca limitada de repositórios, projetos recentes.
- Fluxos `upload` (primeira publicação) e `update` (sincronização) com revisão de arquivos, análise de segredos do conteúdo staged, recuperação sem force push e branches de backup.
- Scanner de segurança com categorias ignorado/suspeito/segredo/falso positivo/permitido.
- Integração GitHub (API REST, GitHub CLI, credential helper, keyring opcional, OAuth Device Flow).
- Assistente de IA Google Gemini: sugestão de mensagens de commit e resumo de alterações, com consentimento e remoção de segredos.
- CLI completa (`--json`, `--batch`, aliases, códigos de saída) e menu interativo (Rich com fallback).
- Branches, histórico, diff/comparação, backups, `.gitignore`/README, diagnóstico, configurações exportáveis.
- Idiomas: português, inglês e espanhol.
- Instaladores para Termux, Linux e Windows; CI no GitHub Actions (Linux e Windows).
