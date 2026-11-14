# Contribuindo

Obrigado pelo interesse! Este projeto aceita correções, novas funcionalidades, traduções e documentação.

## Ambiente

```bash
git clone https://github.com/snaidermadilus-debug/gitflow-assistant.git
cd gitflow-assistant
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[full,dev]"
python -m pytest
```

## Regras

1. **Código real**: nada de funções vazias, `TODO` em funcionalidades anunciadas ou sucesso falso. Toda funcionalidade nova vem com testes.
2. **Núcleo sem interface**: `core/` e `services/` não imprimem nem leem do terminal; usam o `UserInterface`.
3. **Segurança**: nunca `shell=True`; valide argumentos (`utils/validators.py`); passe caminhos depois de `--`; nenhuma operação destrutiva sem `confirm_risky`.
4. **Compatibilidade**: Python 3.9+, somente biblioteca padrão no núcleo; teste caminhos com espaços/acentos; pense em Windows e Termux.
5. **Tipagem e docstrings** nas interfaces públicas.
6. **Mensagens**: textos de usuário vão em `i18n.py` com as três colunas (en, pt, es) e os mesmos placeholders (há teste para isso).
7. Testes que exigem internet/credenciais usam `@pytest.mark.network` e ficam desativados por padrão.

## Fluxo

1. Abra uma issue descrevendo o problema ou a proposta.
2. Crie um branch (`feature/minha-ideia`), use Conventional Commits (`feat:`, `fix:`, `docs:`…).
3. Garanta `python -m pytest` verde e atualize `CHANGELOG.md`/docs.
4. Abra o Pull Request. O CI executa os testes em Linux e Windows.

## Nova tradução

Acrescente o código do idioma em `LANGS` e uma coluna em cada tupla de `M` (`gitflow_assistant/i18n.py`) e inclua-o em `--lang` (`interface/cli_parser.py`).
