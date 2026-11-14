# Instalação

Todos os instaladores trabalham **no espaço do usuário**, sem privilégios de administrador, e só criam:
um ambiente virtual em `~/.local/share/gitflow-assistant/venv` (Windows: `%LOCALAPPDATA%\gitflow-assistant\venv`) e o comando `gitflow`.
Defina `GITFLOW_EXTRAS=0` (ou `-NoExtras` no Windows) para instalar sem Rich/PyYAML.

## Termux

```bash
pkg update && pkg install git python
git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git && cd gitflow-assistant
bash scripts/install_termux.sh
```
O instalador detecta o Termux, verifica Python/Git (pergunta antes de instalar pacotes), cria o venv, cria o wrapper `$PREFIX/bin/gitflow` (não sobrescreve arquivos de terceiros), testa `gitflow --version` e mostra os próximos passos.
Para projetos em `/sdcard`, rode `termux-setup-storage` e use `~/storage/shared/...`.

## Linux

```bash
sudo apt install git python3 python3-venv
sh scripts/install_linux.sh
```
Cria o link `~/.local/bin/gitflow` e informa como incluir esse diretório no PATH (bash, zsh, fish).

## Windows 10/11

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```
Verifica `py`/`python` e `git`, cria o venv e (com confirmação) adiciona a pasta `Scripts` ao PATH **do usuário**. Abra um novo terminal depois.

## Alternativas

- `pip install --user ".[full]"` (comando `gitflow` no `Scripts`/`bin` do usuário)
- `python main.py ...` direto do código-fonte
- `python -m gitflow_assistant ...`

## Desinstalação

Remova o comando (`$PREFIX/bin/gitflow`, `~/.local/bin/gitflow` ou a entrada do PATH no Windows) e a pasta do venv. Configurações ficam em `gitflow config path` e podem ser apagadas manualmente.
