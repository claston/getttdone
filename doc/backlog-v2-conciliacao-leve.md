# Backlog V2 - Conciliacao Leve Como Servico

## Objetivo da Fase 2

- Produto: Conciliacao leve como servico
- Promessa: "Envie seu extrato + sua planilha e veja o que bate e o que esta errado"

## Escopo V2 (limitado)

Para reduzir complexidade nesta fase:

- 1 extrato por analise
- 1 planilha operacional simples por analise
- matching por:
  - valor
  - data (com tolerancia)
  - descricao (basico)

Fora de escopo nesta fase:

- multiplas contas
- CNAB
- integracoes
- regras fiscais complexas

---

## Prioridades (visao rapida)

- `P0` = obrigatorio para validar com contador
- `P1` = recomendado para evolucao da V2
- `P2` = pode adiar sem bloquear

---

## Backlog Priorizado

## EPIC 1 - INPUT (entrada de dados)

1. `P0` Upload duplo (`extrato` + `planilha`)
- Estimativa: 4h
- Dependencias: V1 `POST /analyze` estavel
- Pronto quando: endpoint recebe ambos os arquivos e valida formato

2. `P0` Parser da planilha operacional (`CSV`/`XLSX`)
- Estimativa: 6h
- Dependencias: item 1
- Pronto quando: linhas da planilha entram no mesmo schema base da conciliacao

3. `P0` Deteccao automatica de colunas (`data`, `valor`, `descricao`)
- Estimativa: 4h
- Dependencias: item 2
- Pronto quando: aliases comuns sao reconhecidos sem configuracao manual

4. `P0` Normalizacao unica dos dois lados
- Estimativa: 5h
- Dependencias: item 3
- Pronto quando: extrato e planilha ficam comparaveis (data, sinal, descricao)

5. `P1` Ajuste manual de mapeamento de colunas
- Estimativa: 4h
- Dependencias: item 3
- Pronto quando: usuario consegue corrigir mapeamento ambigguo

## EPIC 2 - MOTOR DE MATCHING (core)

6. `P0` Match exato (valor igual + mesma data)
- Estimativa: 4h
- Dependencias: item 4
- Pronto quando: pares exatos sao conciliados com motivo explicito

7. `P0` Match com tolerancia (valor igual + data +/- 2 dias)
- Estimativa: 4h
- Dependencias: item 6
- Pronto quando: pares com pequena variacao de data sao conciliados

8. `P0` Match por aproximacao de descricao
- Estimativa: 5h
- Dependencias: item 6
- Pronto quando: valor igual + similaridade textual basica gera match confiavel

9. `P1` Matching 1:N leve (varios itens -> 1 lancamento)
- Estimativa: 6h
- Dependencias: itens 6, 7, 8
- Pronto quando: casos simples de consolidacao sao detectados sem ambiguidade alta

## EPIC 3 - CLASSIFICACAO DE RESULTADOS

10. `P0` Status por item: `conciliado`, `pendente`, `divergente`
- Estimativa: 4h
- Dependencias: itens 6, 7, 8
- Pronto quando: todo item recebe status final e motivo

11. `P0` Regras de divergencia
- Estimativa: 3h
- Dependencias: item 10
- Pronto quando: valor diferente ou data fora da janela entra como divergente

12. `P0` Pendencias dos dois lados
- Estimativa: 3h
- Dependencias: item 10
- Pronto quando: itens sem par no extrato/planilha sao listados corretamente

## EPIC 4 - DETECCAO DE PROBLEMAS E INSIGHTS

13. `P0` Regras de problemas operacionais
- Estimativa: 4h
- Dependencias: itens 10, 11, 12
- Pronto quando: sistema sinaliza:
  - pagamento nao encontrado no banco
  - recebimento nao registrado
  - valor divergente
  - possivel duplicidade

14. `P0` Geracao de insights de conciliacao
- Estimativa: 3h
- Dependencias: item 13
- Pronto quando: resposta inclui mensagens objetivas de pendencia/divergencia

15. `P1` Criticidade de problemas (alto/medio/baixo)
- Estimativa: 3h
- Dependencias: item 13
- Pronto quando: problemas ja saem ordenados por impacto

## EPIC 5 - OUTPUT (resultado)

16. `P0` Resumo geral de conciliacao
- Estimativa: 3h
- Dependencias: itens 10, 11, 12
- Pronto quando: total conciliado, pendente e divergente sao exibidos

17. `P0` Tabela detalhada com status e correspondencia
- Estimativa: 4h
- Dependencias: item 16
- Pronto quando: cada linha mostra status, motivo e par encontrado (quando houver)

18. `P0` Exportacao `CSV`/`XLSX` do resultado de conciliacao
- Estimativa: 4h
- Dependencias: item 17
- Pronto quando: arquivo exportado traz status e referencia cruzada

19. `P1` Aba especifica de "Problemas" no relatorio
- Estimativa: 2h
- Dependencias: item 18
- Pronto quando: pendencias e divergencias ficam destacadas em aba dedicada

## EPIC 6 - UX para venda e feedback

20. `P0` Preview com KPIs de conciliacao
- Estimativa: 4h
- Dependencias: item 16
- Pronto quando: usuario ve rapidamente o percentual conciliado

21. `P0` Bloco de problemas em destaque
- Estimativa: 3h
- Dependencias: item 14
- Pronto quando: tela prioriza o que esta errado antes dos detalhes

22. `P0` Narrativa antes/depois da conciliacao
- Estimativa: 3h
- Dependencias: itens 20, 21
- Pronto quando: fica claro o ganho operacional apos processamento

23. `P1` Filtro rapido por status
- Estimativa: 3h
- Dependencias: item 17
- Pronto quando: usuario filtra em 1 clique conciliado/pendente/divergente

## EPIC 7 - QUALIDADE E VALIDACAO

24. `P0` Testes unitarios do motor de matching
- Estimativa: 5h
- Dependencias: itens 6, 7, 8
- Pronto quando: cenarios exato, tolerancia e descricao estao cobertos

25. `P0` Testes de integracao API (extrato + planilha)
- Estimativa: 4h
- Dependencias: itens 1, 16, 18
- Pronto quando: cenario feliz e erros de entrada estao cobertos

26. `P0` Validacoes negativas minimas
- Estimativa: 3h
- Dependencias: item 25
- Pronto quando: erros esperados retornam mensagens claras:
  - planilha sem colunas minimas
  - formato invalido
  - sem correspondencia

27. `P0` Smoke test com dataset real anonimizado (demo contador)
- Estimativa: 3h
- Dependencias: itens P0 concluidos
- Pronto quando: demo ponta-a-ponta mostra valor pratico com dados reais

---

## Corte recomendado para demo V2-MVP (contador)

Itens:
`1,2,3,4,6,7,8,10,11,12,13,14,16,17,18,20,21,22,24,25,26,27`

---

## Itens para adiar para V2.1

- `5` Ajuste manual de mapeamento
- `9` Matching 1:N
- `15` Criticidade de problemas
- `19` Aba extra de problemas no relatorio
- `23` Filtro rapido por status

---

## Sequencia de execucao sugerida

1. Upload duplo + parser planilha + normalizacao unica
2. Motor de matching (exato -> tolerancia -> descricao)
3. Classificacao de status + problemas + insights
4. Output/export completo
5. UX de destaque de problemas
6. Testes e smoke test com contador

---

## Definicao de pronto da V2-MVP

- usuario envia extrato + planilha e recebe conciliacao clara
- sistema mostra o que bate, o que falta e o que diverge
- relatorio exportavel com status por linha
- preview destaca problemas antes dos detalhes
- demo com contador valida utilidade operacional real
