# Runbook — conversões assíncronas AWS

## Escopo e princípio de custo

Este runbook ativa o processamento sob demanda sem ambiente permanente de staging. Os recursos são criados em produção, permanecem sem tráfego público até a validação sintética e não usam provisioned concurrency. O código e a imagem da aplicação ficam no repositório público; conta, ARNs, state, parâmetros de infraestrutura e workflow de deploy ficam no repositório privado `gettdone-infra`.

## Perfis operacionais

As variáveis de cada perfil devem ser alteradas juntas e exigem restart do serviço Render.

| Perfil | `ARCHITECTURE_MODE` | `UPLOAD_MODE` | `EXECUTION_MODE` | Documentos | Resultados | Jobs |
|---|---|---|---|---|---|---|
| atual/emergência | `legacy` | `proxy` | `inline_legacy` | `filesystem` | `filesystem` | filesystem |
| fallback compartilhado | `async_aws` | `proxy` | `inline_shared` | `s3` | `s3` | PostgreSQL |
| AWS normal | `async_aws` | `direct_s3` | `sqs_lambda` | `s3` | `s3` | PostgreSQL |

Os nomes completos são `CONVERSION_ARCHITECTURE_MODE`, `CONVERSION_UPLOAD_MODE`, `CONVERSION_EXECUTION_MODE`, `CONVERSION_DOCUMENT_STORE`, `ANALYSIS_STORAGE` e `CONVERSION_BATCH_REPOSITORY`. Combinações diferentes das três acima são rejeitadas pelo backend.

Nos perfis `fallback compartilhado` e `AWS normal`, preserve também o caminho produtivo de documentos escaneados: `TEXTRACT_ENABLED=true`, `TEXTRACT_MODE=text`, `TEXTRACT_FORCE=false`, `TEXTRACT_TEMP_BUCKET` apontando para o bucket compartilhado, `TEXTRACT_S3_PREFIX=textract/tmp` e `PDF_OCR_ENABLED=false`. Essas variáveis não devem ser aplicadas isoladamente antes da atualização das permissões da fundação.

O primeiro rollback deve usar `fallback compartilhado`: novos PDFs voltam a passar pelo Render e são processados inline, enquanto jobs e resultados existentes continuam no S3/PostgreSQL. Se S3 ou PostgreSQL também estiverem indisponíveis, aplicar o perfil `atual/emergência`. O perfil atual não apaga a fila nem jobs assíncronos; eles podem ser retomados depois.

## Infraestrutura mínima no repositório privado

- Um bucket S3 privado, Block Public Access ativo, SSE-S3 e sem versionamento inicialmente.
- CORS limitado às origens HTTPS reais, métodos `POST` e `HEAD`, e headers usados pelo presigned POST.
- Lifecycle: entrada `conversion/jobs/` e staging `textract/tmp/` por 1 dia, resultados `conversion/results/` alinhados a `ANALYSIS_TTL_SECONDS`, e multipart uploads incompletos abortados após 1 dia.
- SQS Standard e DLQ na mesma região da Lambda.
- Redrive com `maxReceiveCount=5`.
- Lambda em imagem Python 3.12 construída por `Dockerfile.lambda`, sem provisioned concurrency.
- Event source mapping com `BatchSize=1`, `MaximumBatchingWindowInSeconds=0` e `ReportBatchItemFailures`.
- EventBridge a cada minuto chamando a mesma Lambda com `{"action":"dispatch_outbox"}`.
- CloudWatch Logs com retenção inicial de 7 dias.
- AWS Budget mensal baixo e alertas em 50%, 80% e 100% do teto definido pelo responsável.

Começar a Lambda com reserved concurrency `2`. Isso permite progresso paralelo em lotes de 12 sem abrir conexões demais no PostgreSQL. Aumentar para `4` somente depois de medir banco, memória, timeout e custo. Cada instância usa pool máximo `1`.

O timeout deve ser definido pelo benchmark do maior PDF suportado. A visibility timeout da fila deve ser no mínimo seis vezes o timeout da Lambda, mais qualquer batching window. O lease do job deve ser maior que o p99 observado e nunca menor que o timeout configurado.

O primeiro corte usa o Textract assíncrono em modo `text`, com polling dentro da invocação limitado a 210 segundos e timeout da Lambda de 300 segundos. A chave temporária e o `ClientRequestToken` são determinísticos por conteúdo/configuração para que retries SQS não iniciem uma segunda análise. Migrar o polling para conclusão SNS/SQS só se os benchmarks mostrarem espera longa ou custo relevante.

## IAM e credenciais

- Role da Lambda: somente leitura/remoção no prefixo de entrada, leitura/escrita no prefixo de resultados e no staging `textract/tmp/`, `Start/GetDocumentTextDetection`, consumo da fila e logs.
- Identidade da API Render: somente criação de presigned POST/`HeadObject`, escrita/leitura nos prefixos necessários, `Start/GetDocumentTextDetection` para o fallback inline e `sqs:SendMessage`. Guardar as credenciais somente como secrets do Render e rotacioná-las.
- Role de deploy: criada por bootstrap local com credenciais temporárias/MFA.
- GitHub Actions do repositório privado: OIDC com `id-token: write` e `contents: read`; nenhuma `AWS_ACCESS_KEY_ID` ou `AWS_SECRET_ACCESS_KEY` no GitHub.
- Trust policy restrita ao owner/repository ID imutável quando disponível, ambiente protegido `production` e branch autorizada. Pull requests e forks não recebem permissão de deploy.
- Actions externas devem ser fixadas por SHA; `apply` exige aprovação manual.

## Ordem de implantação sem staging

1. Criar o repositório privado e executar o bootstrap IAM localmente.
2. Criar S3, SQS/DLQ, ECR, Lambda, EventBridge, roles, logs, métricas, alarmes e budget com o trigger SQS desabilitado.
3. Construir `Dockerfile.lambda`; validar o import do handler, a disponibilidade do SDK Textract e a arquitetura da imagem compatível com a função.
4. Executar a migração aditiva `20260829_01` antes do backend novo. O backend antigo ignora as novas tabelas.
5. Publicar backend e frontend mantendo o perfil `atual/emergência`.
6. Invocar diretamente a Lambda com jobs sintéticos internos: 1 arquivo, lote de 5 e lote de 12.
7. Testar duplicidade da mensagem, erro permanente, erro transitório, quinta tentativa/DLQ, replay do outbox, expiração e isolamento entre proprietários.
8. Executar carga controlada com concorrência `2`; registrar p50/p95/p99, pico de memória, conexões e custo estimado.
9. Habilitar o event source mapping.
10. Aplicar em uma só mudança o perfil `AWS normal` e reiniciar o Render.
11. Observar os sinais abaixo por pelo menos uma janela completa do maior job.

### Primeiro canário escaneado em modo escuro

Com `QueueTriggerEnabled=false` e `OutboxDispatcherEnabled=false`, execute da
raiz do repositório público:

```powershell
backend\venv\Scripts\python.exe backend\scripts\run_conversion_worker_canary.py `
  --profile gettdone-iac `
  --region us-east-1
```

O utilitário recusa a execução se os dois toggles não estiverem desligados,
gera o cenário escaneado `inline_signed_values` do corpus sintético e usa
somente o objeto S3 reservado
`conversion/jobs/doc_cafe5afe0000000000000000/document.pdf`. Ele cria um lote
e um job identificados por `worker_canary` no PostgreSQL, sob a identidade
anônima isolada `gettdone-worker-canary`, e invoca diretamente a Lambda sem
publicar na SQS. Em caso de sucesso, exige evidência
`extraction_provider=aws_textract`, confirma a conclusão no banco e verifica
que o worker removeu o arquivo temporário de entrada.

O comando não imprime `DATABASE_URL` nem outros segredos. O resultado e a
telemetria sintéticos permanecem sujeitos ao TTL/lifecycle normal; nenhum dado
ou cota de usuário real é utilizado.

## Sinais e alarmes

Alarmes acionáveis:

- DLQ com uma ou mais mensagens;
- `ApproximateAgeOfOldestMessage` acima de duas vezes o p99 esperado;
- erros ou throttles da Lambda acima de zero em duas janelas consecutivas;
- duração p95 acima de 80% do timeout;
- outbox pendente mais antigo acima de 2 minutos;
- falhas permanentes acima de 10% dos jobs em 15 minutos;
- budget nos limiares definidos.

Logs estruturados aceitam apenas `job_id`, `batch_id`, `trace_id`, tentativa, resultado, duração, código/classe segura de erro e contagens. Não registrar nome do arquivo, identidade/e-mail, conteúdo, transações, token, cookie, presigned URL, chave S3 completa ou exceção bruta potencialmente sensível.

## Rollback

1. Desabilitar o event source mapping para interromper novas execuções sem perder mensagens.
2. Aplicar o perfil `fallback compartilhado` e reiniciar o Render.
3. Confirmar `GET /api/conversion-runtime`: `direct_batch_enabled=false`, upload `proxy` e execução `inline_shared`.
4. Validar uma conversão pelo endpoint atual e um download de relatório.
5. Manter S3, PostgreSQL, SQS e DLQ intactos durante a investigação.
6. Se S3/PostgreSQL estiverem afetados, aplicar todas as variáveis do perfil `atual/emergência` e reiniciar.
7. Nunca executar downgrade da migração durante rollback de aplicação. As tabelas são aditivas e compatíveis com o código anterior.

## Evidências obrigatórias antes do corte

- build da imagem Lambda e import do handler/SDK Textract dentro do contêiner;
- invocação real do Textract em modo escuro com PDF sintético escaneado, sem fallback local;
- `alembic upgrade head` em banco de teste descartável e SQL de downgrade revisado, sem executar downgrade em produção;
- testes automatizados e lint verdes;
- chamadas HTTP reais: conversão feliz, download feliz, formato inválido e consulta de lote por outro proprietário;
- lote de 12 com conclusão independente por arquivo;
- uma mensagem duplicada sem duplicar cota nem resultado;
- screenshot/registro dos alarmes, lifecycle, Block Public Access e trust OIDC;
- comandos exatos de rollback conferidos por uma segunda pessoa ou em dry run.
