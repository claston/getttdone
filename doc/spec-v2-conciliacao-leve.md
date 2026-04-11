# gettdone - Especificacao Tecnica V2 (Conciliacao Leve)

## 1) Objetivo da fase

Entregar uma V2 focada em conciliacao leve para validacao com contador:

- receber `1 extrato` + `1 planilha operacional`
- comparar os dois conjuntos
- mostrar o que bate, o que falta e o que diverge
- exportar resultado para acao operacional

Promessa de produto:

> "Envie seu extrato + sua planilha e veja o que bate e o que esta errado"

---

## 2) Escopo V2 (limitado)

### Entra na V2-MVP

- Upload de 2 arquivos:
  - extrato (`CSV`, `XLSX`, `OFX`)
  - planilha operacional (`CSV`, `XLSX`)
- Deteccao automatica de colunas da planilha:
  - `data`, `valor`, `descricao`
- Normalizacao dos dois lados:
  - data
  - valor/sinal
  - descricao
- Matching:
  - exato (valor + data)
  - tolerancia de data (+/- 2 dias)
  - descricao semelhante (basico)
- Classificacao:
  - `conciliado`
  - `pendente`
  - `divergente`
- Insights de problemas operacionais
- Exportacao do resultado (`XLSX` e/ou `CSV`)

### Fora da V2-MVP

- multiplas contas
- CNAB
- integracoes bancarias/sistemas terceiros
- regras fiscais complexas
- automacao de ajuste manual de mapeamento (fica para V2.1)
- matching avancado 1:N (opcional posterior)

---

## 3) Fluxo funcional (pagina unica)

1. Usuario sobe extrato e planilha
2. Backend parseia e normaliza os dois conjuntos
3. Motor tenta casar registros por regras em ordem
4. Sistema classifica cada item
5. UI mostra resumo e problemas
6. Usuario baixa relatorio conciliado

---

## 4) Modelo de dados minimo

## 4.1 Registro normalizado (base para matching)

```json
{
  "id": "row_001",
  "source": "bank|sheet",
  "date": "2026-04-01",
  "description": "PAGAMENTO FORNECEDOR ALFA",
  "amount": -980.0,
  "type": "outflow"
}
```

## 4.2 Resultado de conciliacao por linha

```json
{
  "row_id": "row_001",
  "source": "bank",
  "status": "conciliado|pendente|divergente",
  "match_rule": "exact|date_tolerance|description_similarity|none",
  "matched_row_id": "row_923",
  "reason": "matched_exact_value_and_date"
}
```

## 4.3 Insight operacional

```json
{
  "type": "missing_payment|missing_receipt|amount_mismatch|possible_duplicate",
  "title": "Pagamento nao encontrado no banco",
  "description": "3 pagamentos da planilha nao foram encontrados no extrato."
}
```

---

## 5) Contrato de API (V2)

## 5.1 `POST /reconcile`

### Request

- `multipart/form-data`
- campos:
  - `bank_file`
  - `sheet_file`

### Response 200 (exemplo)

```json
{
  "analysis_id": "rc_abc123",
  "summary": {
    "total_bank_rows": 120,
    "total_sheet_rows": 118,
    "conciliated_count": 102,
    "pending_count": 28,
    "divergent_count": 8
  },
  "problems": [
    {
      "type": "missing_payment",
      "title": "Pagamentos sem confirmacao",
      "description": "3 pagamentos da planilha nao foram localizados no extrato."
    }
  ],
  "rows": [
    {
      "row_id": "bank_001",
      "source": "bank",
      "date": "2026-04-01",
      "description": "PAGAMENTO FORNECEDOR ALFA",
      "amount": -980.0,
      "status": "divergente",
      "match_rule": "description_similarity",
      "matched_row_id": "sheet_044",
      "reason": "amount_mismatch"
    }
  ],
  "expires_at": "2026-04-11T21:10:00Z"
}
```

### Erros

- `400` arquivos invalidos/nao suportados
- `422` sem colunas minimas na planilha
- `500` erro inesperado no pipeline

## 5.2 `GET /reconcile-report/{analysis_id}`

### Response 200

- arquivo `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- nome sugerido: `gettdone_reconcile_{analysis_id}.xlsx`

### Erros

- `404` `analysis_id` nao encontrado/expirado

---

## 6) Regras de parsing e normalizacao

## 6.1 Extrato

Reutiliza parser/normalizador da V1 para `CSV`, `XLSX`, `OFX`.

## 6.2 Planilha operacional

- Detectar colunas por aliases:
  - `data|date|dt|dt_lancamento`
  - `valor|amount|vlr|valor_liquido`
  - `descricao|description|historico|memo`
- Ler primeira aba para `XLSX`
- Ignorar linhas vazias

## 6.3 Normalizacao comum

- data em `YYYY-MM-DD`
- descricao em uppercase, trim, sem ruido basico
- valor em `float` com sinal consistente:
  - entrada positivo
  - saida negativo

---

## 7) Motor de matching (ordem de regras)

## 7.1 Match exato

- valor igual
- mesma data
- marca `match_rule = "exact"`

## 7.2 Match com tolerancia de data

- valor igual
- data dentro de +/- 2 dias
- marca `match_rule = "date_tolerance"`

## 7.3 Match por descricao semelhante

- valor igual
- similaridade textual basica acima de limiar configuravel
- marca `match_rule = "description_similarity"`

Observacao:

- na V2-MVP usar matching `1:1` para manter previsibilidade
- `1:N` fica como extensao futura

---

## 8) Classificacao de status

## 8.1 `conciliado`

- correspondencia clara encontrada

## 8.2 `pendente`

- existe no extrato e nao na planilha, ou vice-versa

## 8.3 `divergente`

- candidato encontrado, mas com diferenca relevante:
  - valor diferente
  - data fora da janela esperada

---

## 9) Regras de problemas e insights

Gerar insights minimos:

- pagamentos nao encontrados no banco
- recebimentos nao registrados internamente
- valores divergentes
- possiveis duplicidades

Formato de saida deve priorizar objetividade e acao.

---

## 10) Output e relatorio

Abas minimas no `XLSX`:

1. `Resumo`
2. `Conciliacao_Detalhada`
3. `Problemas`

Campos minimos da aba detalhada:

- row_id
- source
- date
- description
- amount
- status
- match_rule
- matched_row_id
- reason

---

## 11) UX de validacao com contador

Tela deve destacar primeiro:

1. Quantos itens bateram
2. Quantos estao pendentes
3. Quantos divergem
4. Lista de problemas mais importantes

Mensagem de valor esperada:

- "X itens conciliados"
- "Y problemas encontrados"

---

## 12) Criterios de aceite V2-MVP

- upload de 2 arquivos funciona (`extrato` + `planilha`)
- matching exato + tolerancia + descricao basica funcionando
- classificacao correta em `conciliado|pendente|divergente`
- resumo e insights exibidos na UI
- exportacao `XLSX` (e opcional `CSV`) sem erro
- validacao com dataset real anonimizado para demo

---

## 13) Riscos e mitigacoes

Risco: baixa qualidade da planilha operacional (colunas inconsistentes).
Mitigacao: aliases + erro explicito de coluna minima + (futuro) mapeamento manual.

Risco: falso positivo de matching por descricao.
Mitigacao: manter regra conservadora e explicar `match_rule` + `reason`.

Risco: expectativa de cobranca/fiscal complexa na demo.
Mitigacao: reforcar escopo V2-MVP como conciliacao leve operacional.

---

## 14) Proximos passos (V2.1+)

- mapeamento manual de colunas na UI
- matching 1:N controlado
- score de confianca por match
- filtros por status na interface
- conectores de importacao futura
