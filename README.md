# Forca de Vendas

Produto separado do ecossistema Insights X para operacao comercial, catalogo de produtos e base futura de pedidos, CRM e app de campo.

## Decisao de arquitetura

- Projeto independente do EasyFinance.
- Pode usar o mesmo banco Postgres do ecossistema em desenvolvimento.
- Tabelas proprias usam prefixo `sf_` para evitar acoplamento com tabelas do EasyFinance.
- Integra com pessoas/clientes do EasyFinance por leitura da tabela `people`, sem transformar o EasyFinance em dependencia obrigatoria.
- Futuramente outros ERPs/SaaS podem ser integrados por conectores, mantendo o produto operando separado.

## Banco em desenvolvimento

Use o Postgres ja definido em `easyFinance/docker-compose.yml`:

```env
DATABASE_URL=postgresql+psycopg2://easyfinance:easyfinance@localhost:5433/easyfinance
CUSTOMER_PROVIDER=easyfinance
```

## Modelo comercial

O produto pode operar sozinho ou integrado ao ecossistema. Quando `CUSTOMER_PROVIDER=easyfinance`, a lista de clientes e lida da tabela `people` do EasyFinance, mas as tabelas comerciais continuam proprias do Forca de Vendas com prefixo `sf_`.

Cadastros atuais:

- Clientes locais ou compartilhados do EasyFinance.
- Grupos, classes e produtos.
- Produtos com preco de compra, custo, preco de venda de referencia e status.
- Tabelas de preco com cabecalho e itens por produto.
- Pedidos com cabecalho e multiplos itens.

## Regra de preco e rentabilidade

O item do pedido busca o preco base na tabela de preco e calcula o preco corrigido pela data de prazo de pagamento do pedido.

- Correcao por fora: `preco_corrigido = preco_base * (1 + taxa_mensal * dias / 30)`.
- Correcao por dentro: `preco_corrigido = preco_base / (1 - taxa_mensal * dias / 30)`.
- Custo do item: usa o `cost_price` atual do produto no momento da inclusao/alteracao do item.
- Lucro do item: `(preco_corrigido - custo_unitario) * quantidade`.
- Rentabilidade do item: `lucro_item / total_item * 100`.
- Rentabilidade do pedido: media ponderada da rentabilidade dos itens pelo total de cada item (`quantidade * preco_corrigido`). Na pratica, equivale a `lucro_total / total_pedido * 100`.

## Aprovacao de pedidos

O fluxo atual tem duas etapas:

- Financeira: valida limite de credito, titulos vencidos acima da tolerancia do perfil comercial e, quando configurado, dias sem movimentacao.
- Comercial: aprova o pedido depois da etapa financeira.

O limite de credito pertence ao cadastro de pessoas do EasyFinance (`people.credit_limit`) e e apenas consultado pelo Forca de Vendas. Valores pagos, em aberto e titulos vencidos ficam no EasyFinance; o Forca usa esses dados somente para decidir a aprovacao, sem exibir o detalhe financeiro na tela.

O cadastro **Perfis comerciais** classifica clientes como Novo, Bom, Excelente, Ruim, Inativo ou outros perfis cadastrados. Cada perfil define:

- Dias maximos sem movimentacao.
- Dias tolerados para titulos vencidos.
- Se deve bloquear por falta de movimentacao.
- Se deve bloquear por titulos vencidos.

## Swagger / Endpoints

Com o backend rodando, acesse:

```text
http://127.0.0.1:8020/docs
```

Grupos publicados no Swagger:

- Sistema: `GET /health`.
- Clientes: `GET /customers`, `POST /customers`, `PUT /customers/{customer_id}`, `DELETE /customers/{customer_id}`.
- Perfis comerciais: `GET/POST /customer-profiles`, `PUT/DELETE /customer-profiles/{profile_id}`.
- Produtos: grupos, classes e produtos.
- Tabelas de preco: cabecalho, itens e `GET /price-preview`.
- Pedidos: CRUD do pedido e itens, alem de `POST /orders/{order_id}/submit`, `POST /orders/{order_id}/approve-financial`, `POST /orders/{order_id}/approve-commercial` e `POST /orders/{order_id}/reject`.

## Rodar pelo VS Code

Backend:

```powershell
cd forca-vendas\backend
python -m venv env
.\env\Scripts\pip install -r requirements.txt
copy .env.example .env
.\env\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8020
```

Frontend:

```powershell
cd forca-vendas\frontend
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 5190
```
