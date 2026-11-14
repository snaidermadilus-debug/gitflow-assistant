# Solução de problemas

Comece sempre por `gitflow doctor` — ele verifica Git, identidade, credenciais, conectividade, remotos, conflitos e integridade, e sugere o comando de correção.

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Git is not installed` (código 3) | Git fora do PATH | Termux `pkg install git` · Debian/Ubuntu `sudo apt install git` · Windows `winget install --id Git.Git -e` |
| `Git identity missing` | `user.name`/`user.email` vazios | `gitflow config set git.user_name "Nome"` e `gitflow config set git.user_email voce@ex.com` (confirma aplicar no Git global) |
| `dubious ownership` no Termux | projeto em `/sdcard` (dono diferente) | rode o comando `git config --global --add safe.directory ...` mostrado pelo `doctor` |
| `no project selected` (código 4) | pasta atual não é repositório | `gitflow select CAMINHO` ou `-C CAMINHO` |
| push rejeitado | o remoto tem commits novos | `gitflow update` (escolha merge ou rebase; um branch de backup é criado) |
| `Authentication failed` / `terminal prompts disabled` | sem credencial HTTPS | `gh auth login && gh auth setup-git`, SSH, ou `GITHUB_TOKEN` |
| `unrelated histories` | repositório remoto criado com README | aceite a mesclagem oferecida no `upload` (merge com `--allow-unrelated-histories`) |
| conflito após `update`/`pull` | mesmas linhas alteradas | edite os arquivos, `git add`, `gitflow commit`; ou `gitflow abort` |
| publicação bloqueada (código 6) | segredo detectado | revise no modo interativo, exclua o arquivo ou adicione ao `.gitignore` |
| caracteres estranhos no Windows | console legado | use Windows Terminal ou `--no-color`; o GitFlow troca símbolos Unicode por ASCII automaticamente |
| `Gemini HTTP 400/403/404/429` | chave inválida / sem permissão / modelo / cota | `gitflow ai login`, verifique o projeto no AI Studio, `gitflow ai models`, ou use `gemini-3.1-flash-lite` |
| conexão instável | rede móvel | operações locais continuam; `update` offline faz o commit local e avisa para enviar depois |

Logs (com credenciais redigidas): `<diretório de dados>/logs/gitflow.log` — veja o caminho em `gitflow doctor`. Use `-v` para depuração no terminal.
