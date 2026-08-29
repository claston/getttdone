# Plano de implementação — conversão assíncrona AWS com lotes

## Objetivo

Retirar os bytes dos documentos do processo web, absorver picos de conversão sem manter um worker com custo fixo e preparar o produto para lotes de `1` a `12` arquivos, preservando um fallback operacional para o fluxo inline atual.

Este plano substitui, para o corte AWS, as partes ainda futuras de `doc/plan-convert-document-pipeline-migration.md`. As abstrações já entregues de job, executor, pipeline e armazenamento continuam sendo a fundação da implementação.

## Restrições e decisões

1. Não haverá ambiente permanente de staging.
2. Toda a infraestrutura será criada no ambiente de produção com o fluxo novo desligado por padrão.
3. A validação pré-corte será feita com jobs sintéticos internos e sem expor a rota nova aos usuários.
4. O código da aplicação pode continuar no repositório público.
5. O IaC e o workflow de deploy devem ficar em repositório privado separado.
6. Nenhuma chave AWS permanente será armazenada no GitHub.
7. O deploy automatizado, quando ativado, usará GitHub Actions OIDC limitado ao repositório, ambiente e branch de produção.
8. O primeiro deploy pode ser executado localmente com credenciais temporárias/MFA para evitar consumo de Actions privadas antes de existir receita.
9. Lambda será usada sob demanda, sem provisioned concurrency.
10. Cada arquivo de um lote será um job independente no SQS. O lote será somente um agregado de acompanhamento e autorização.

## Arquitetura-alvo

```text
Navegador
  |-- cria lote/job --------------------------------------------> API Render
  |                                                                |
  |<-- presigned POST por arquivo ---------------------------------|
  |
  |-- documentos (concorrência de upload limitada) -------------> S3 privado
  |
  |-- confirma uploads ------------------------------------------> API Render
                                                                   |
                                                        PostgreSQL + outbox
                                                                   |
                                                                   v
                                                                  SQS
                                                                   |
                                                                   v
                                                           Lambda worker
                                                             |          |
                                                             v          v
                                                       PostgreSQL      S3
                                                        estado/cota  resultados
```

O SQS recebe apenas `schema_version` e `job_id`. Nome do arquivo, identidade, cota, chaves S3 e resultado são resolvidos em armazenamento controlado pelo backend.

## Modelo de lote

### `conversion_batches`

- `batch_id` opaco e globalmente único;
- proprietário (`identity_type`, `identity_id`);
- `status`: `uploading`, `queued`, `processing`, `completed`, `completed_with_errors`, `failed`, `expired`;
- `files_count`, limitado inicialmente a `12`;
- contadores derivados de jobs concluídos, falhos e ativos;
- timestamps e expiração;
- chave de idempotência única por proprietário.

### `conversion_jobs`

- `job_id` opaco e globalmente único;
- `batch_id` opcional, permitindo que uma conversão unitária use o mesmo pipeline;
- posição estável dentro do lote;
- proprietário e metadados validados do documento;
- referência S3 de entrada e manifesto de resultado;
- `status`: `uploading`, `uploaded`, `queued`, `running`, `retrying`, `completed`, `failed`, `expired`;
- `attempt_count`, lease de execução e último código de erro seguro;
- versão do contrato do job;
- chave de idempotência única por proprietário;
- referência para reserva/consumo de cota idempotente.

O status do lote é calculado a partir dos filhos. Uma falha individual não cancela arquivos já processados nem impede os demais. `completed_with_errors` permite download dos resultados válidos e retry seletivo dos arquivos com erro.

## Limites iniciais

- `1` a `12` arquivos por lote;
- extensões permitidas iguais às do fluxo unitário;
- limite individual de bytes e páginas preservado;
- limite de bytes total do lote configurável;
- até `3` uploads simultâneos no navegador;
- uma mensagem SQS por arquivo;
- `BatchSize=1` na integração SQS/Lambda;
- concorrência inicial do worker igual a `1`, ampliada para `2` e `4` somente após medição;
- sem ordenação global: SQS Standard é suficiente;
- retenção curta de entrada e resultados, alinhada ao TTL do produto.

## Contrato HTTP novo

### `POST /api/conversion-batches`

Recebe apenas metadados dos arquivos. Cria lote e jobs `uploading`, verifica identidade e disponibilidade inicial de cota e retorna um presigned POST para cada arquivo.

### `POST /api/conversion-batches/{batch_id}/submit`

Confirma cada objeto com `HeadObject`, valida tamanho, checksum e metadados, reserva cota de forma idempotente e grava eventos de outbox na mesma transação dos jobs.

Retorna `202 Accepted` com o estado do lote. Chamadas repetidas com a mesma chave de idempotência retornam o lote já criado.

### `GET /api/conversion-batches/{batch_id}`

Retorna o resumo e os estados por arquivo. Apenas o proprietário pode consultar o lote.

### `GET /api/conversions/{job_id}`

Retorna estado, progresso persistido, erro seguro ou resultado de uma conversão individual.

Os endpoints atuais permanecem disponíveis durante toda a janela de rollback.

## Armazenamento S3

- bucket privado com Block Public Access;
- chaves geradas pelo servidor, nunca pelo nome enviado pelo cliente;
- prefixos separados por ambiente, lote, job, entrada e resultado;
- presigned POST com expiração curta, tipo exato e `content-length-range`;
- checksum SHA-256 validado no fechamento do upload e novamente pelo worker;
- criptografia SSE-S3 por padrão para evitar custo de chave KMS dedicada nesta fase;
- lifecycle como rede de segurança para uploads abandonados, entradas e resultados expirados;
- CORS limitado à origem real do frontend;
- roles separadas para API/presign, worker e deploy.

## Persistência, idempotência e cota

SQS e Lambda têm semântica de entrega pelo menos uma vez. Portanto:

1. aquisição do job usa compare-and-set e lease com expiração;
2. job já concluído retorna sucesso sem reexecutar;
3. artefatos usam chaves determinísticas/versionadas por job;
4. reserva, consumo e liberação de cota usam `job_id` como chave única;
5. eventos de histórico são atualizados pelo mesmo identificador, não inseridos novamente;
6. falha transitória mantém o job apto a retry;
7. falha permanente encerra o job e confirma a mensagem;
8. ao atingir a quinta tentativa, o job é marcado como falha antes de a mensagem seguir para a DLQ;
9. outbox evita o estado inconsistente “job salvo sem mensagem”;
10. dispatcher de outbox também é idempotente.

## Worker Lambda

- imagem de container Python 3.12;
- reutiliza `DocumentConversionPipeline` e o contrato `ConversionJobExecutor`;
- usa somente `/tmp` como scratch local;
- carrega entrada do S3 e grava manifesto/artefatos no S3;
- lê e atualiza jobs no PostgreSQL;
- atualiza progresso de OCR com frequência limitada;
- SQS Standard, DLQ e partial batch response;
- timeout e visibility timeout definidos a partir do benchmark do maior documento suportado;
- reserved/max concurrency protege o banco e os provedores de OCR;
- nenhum callback, token, cookie ou documento é transportado na mensagem.

O gate de adoção da Lambda exige que o p99 do maior arquivo suportado permaneça com margem segura abaixo do limite da função. Se o caminho de OCR longo não cumprir o gate, ele será separado sem alterar o contrato do job.

## Feature flags e fallback

### Modo normal antes do corte

```text
CONVERSION_ARCHITECTURE_MODE=legacy
```

Mantém upload multipart, executor inline e filesystem atuais.

### Modo AWS

```text
CONVERSION_ARCHITECTURE_MODE=async_aws
CONVERSION_UPLOAD_MODE=direct_s3
CONVERSION_EXECUTION_MODE=sqs_lambda
```

### Fallback operacional

```text
CONVERSION_ARCHITECTURE_MODE=async_aws
CONVERSION_UPLOAD_MODE=proxy
CONVERSION_EXECUTION_MODE=inline_shared
```

Novas conversões voltam a passar pela API e são executadas inline, mas continuam usando PostgreSQL/S3. Jobs e resultados já criados permanecem acessíveis.

### Fallback de emergência

```text
CONVERSION_ARCHITECTURE_MODE=legacy
```

Volta integralmente ao comportamento atual para novas conversões. Jobs assíncronos em andamento não são apagados e poderão ser retomados quando AWS/PostgreSQL compartilhado estiver disponível.

As flags serão validadas no startup. Combinações inseguras ou incompletas devem impedir a inicialização em vez de produzir um modo híbrido acidental.

## Cutover único sem staging permanente

1. Criar recursos de produção com acesso público ao fluxo novo desligado.
2. Executar migrações aditivas mantendo o fluxo legado ativo.
3. Publicar Lambda e backend compatíveis com ambos os modos.
4. Executar jobs sintéticos internos unitários e lotes de `5` e `12` arquivos.
5. Validar duplicidade, retry, timeout, DLQ, expiração, isolamento e download.
6. Executar carga controlada com o máximo de concorrência planejado.
7. Publicar frontend ainda com `legacy` ativo.
8. Aplicar, em uma única alteração de configuração, o perfil `async_aws/direct_s3/sqs_lambda`.
9. Observar fila, erros, duração e conclusão.
10. Em incidente, aplicar primeiro o fallback `inline_shared`; usar `legacy` somente em falha mais ampla.

## Observabilidade e privacidade

Logs JSON devem usar `job_id`, `batch_id`, `attempt`, `status`, duração e códigos de erro classificados.

É proibido registrar:

- nome original do arquivo;
- identidade ou e-mail;
- token, cookie ou presigned URL;
- chave S3 completa;
- hash do arquivo como dimensão pesquisável;
- texto do PDF, transações ou exceção bruta que possa conter dados bancários.

Métricas mínimas:

- uploads iniciados, concluídos e abandonados;
- tempo de upload até fila;
- idade da mensagem e profundidade da fila;
- duração, memória, erros e throttles da Lambda;
- sucesso, falha permanente e retry por etapa;
- lotes concluídos, parciais e falhos;
- mensagens na DLQ;
- divergência de cota/job/resultado.

Para reduzir custo:

- retenção curta de logs;
- métricas com dimensões de baixa cardinalidade;
- sem provisioned concurrency;
- sem pollers provisionados do SQS;
- dashboard pequeno e alarmes somente para sinais acionáveis;
- Parameter Store Standard para segredos/configuração de baixo volume, com acesso limitado por IAM;
- budgets e alertas de custo da AWS configurados antes do corte.

## Repositórios e deploy

### Repositório público atual

Contém aplicação, contratos, handler Lambda, Dockerfile do worker e testes. Não contém IDs de conta, ARNs privados, state de IaC ou credenciais.

### Repositório privado de IaC

Nome sugerido: `gettdone-infra`.

Contém template SAM/CloudFormation ou Terraform, parâmetros não secretos, políticas IAM, alarmes e runbooks. Nunca contém `.tfstate`, planos com valores sensíveis ou arquivos `.env`.

Ordem de segurança/custo para o deploy:

1. primeiro deploy local com AWS SSO/credencial temporária e MFA;
2. depois, se a automação justificar o consumo, GitHub Actions OIDC;
3. trust policy restrita ao repositório privado, ambiente protegido e branch `main`;
4. `permissions: id-token: write, contents: read` somente no job de deploy;
5. actions de terceiros fixadas por SHA;
6. `plan` sem credencial em pull request e `apply` apenas manualmente ou após aprovação;
7. sem workflows AWS em pull requests de forks.

## Critérios de aceite

- nenhum byte de documento passa pelo Render no modo `async_aws/direct_s3`;
- lote de `12` arquivos pode terminar parcialmente e permite retry seletivo;
- uma entrega SQS duplicada gera uma conversão, um consumo de cota e um conjunto de artefatos;
- restart da API ou da Lambda não perde job nem progresso já persistido;
- usuário A não acessa lote, job ou resultado de B;
- expiração remove entrada e resultado sem depender somente do código da aplicação;
- DLQ gera alarme e deixa o job em estado terminal compreensível;
- fallback `inline_shared` preserva jobs e resultados;
- fallback `legacy` volta a aceitar novas conversões pelo contrato atual;
- testes HTTP felizes e negativos dos endpoints atuais continuam passando;
- carga de lote não ultrapassa os limites definidos de banco, Lambda, S3 ou OCR.
