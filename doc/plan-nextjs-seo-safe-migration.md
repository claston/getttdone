# Plano de migração gradual do frontend para Next.js

- Status: proposto
- Data de referência: 27/08/2026
- Horizonte: execução incremental durante várias semanas
- Risco de negócio: alto, porque a aquisição depende de SEO

## 1. Decisão resumida

O OFX Simples deve começar pelo frontend da área autenticada e não pelas páginas que já recebem tráfego orgânico.

A primeira versão em Next.js será um site exportado estaticamente, servido pelo mesmo FastAPI e pelo mesmo serviço do Render. O Node.js será usado apenas no build. Assim, nesta etapa:

- o DNS continua sendo `www.ofxsimples.com.br`;
- o serviço FastAPI continua sendo a origem da API e dos arquivos estáticos;
- não há um servidor Next.js adicional em produção;
- não há CORS entre o frontend novo e a API;
- as URLs públicas indexadas não mudam;
- a área nova fica em `/app/` e recebe `noindex`;
- o custo recorrente de compute tende a permanecer o mesmo;
- o frontend HTML/JavaScript atual permanece disponível para rollback.

Não é recomendável dividir agora o serviço atual em gateway, servidor Next.js e API. Essa divisão aumenta custo, pontos de falha e complexidade operacional sem oferecer benefício necessário para a primeira etapa.

## 2. Resposta à dúvida sobre conversões públicas e autenticadas

### 2.1 Estado desejado

As páginas públicas e a área autenticada terão responsabilidades diferentes:

| Contexto | Experiência desejada | Identidade e cota |
| --- | --- | --- |
| Visitante anônimo em `/convert.html` | Escolhe o formato de saída | Ainda não consome cota |
| Visitante anônimo em uma página pública de conversão | Pode converter dentro da política do plano anônimo | Identidade e cota anônimas |
| Cliente autenticado que chegou pelo Google a uma página pública | É convidado a continuar em `/app/converter/`; durante a transição, a conversão pública ainda funciona | Usuário ou empresa autenticada, nunca anônimo |
| Cliente navegando dentro de `/app/` | Usa somente `/app/converter/` | Usuário ou empresa autenticada |
| Robô de busca sem sessão | Recebe o conteúdo público estático completo | Não há comportamento baseado em user-agent |

Portanto, “o cliente logado converte dentro da área logada” será a experiência principal, mas isso não exige retirar agora o conversor das páginas públicas. Retirar a ferramenta de uma página que já ranqueia pode reduzir sua utilidade e sua capacidade de aquisição.

### 2.2 Regra obrigatória de identidade

Antes de alterar a navegação, o backend deve garantir e testar o seguinte invariante em todos os endpoints de conversão e de resultado:

1. Uma identidade autenticada válida prevalece sobre a identidade anônima.
2. A conversão feita por um cliente autenticado é registrada no histórico desse cliente.
3. A cota consumida é a do usuário ou da empresa ativa.
4. O proprietário do arquivo, do job e do relatório é a identidade autenticada.
5. Uma sessão autenticada expirada ou inválida não pode cair silenciosamente na cota anônima. O frontend tenta renovar a sessão e, se não conseguir, solicita novo login.
6. O cookie anônimo continua existindo para visitantes sem sessão e não deve substituir uma sessão válida.

O resolvedor atual já prioriza uma credencial de usuário quando ela chega à camada de conversão. A primeira entrega deve transformar isso em contrato explícito e cobrir os caminhos antigos e novos com testes, inclusive o caso em que os cookies autenticado e anônimo estão presentes simultaneamente.

### 2.3 Transição de navegação

A mudança deve ocorrer em duas etapas:

1. Inicialmente, um cliente autenticado que abrir uma página pública verá uma mensagem como “Você está conectado. Continue na área do cliente para salvar esta conversão no seu espaço”, com link para `/app/converter/?formato=ofx` ou `/app/converter/?formato=excel`. Não haverá redirecionamento automático.
2. Depois de medir uso e falhas por pelo menos duas semanas, pode-se ativar um redirecionamento somente para sessões autenticadas. Essa decisão será controlada por feature flag e não por identificação de robôs.

Os links “Nova conversão” dentro da área do cliente devem apontar apenas para `/app/converter/`. Depois do login iniciado numa página pública, o parâmetro `next` deve levar ao conversor interno, preservando o formato escolhido.

### 2.4 Por que não remover a conversão anônima agora

As páginas `converter-pdf-para-ofx.html` e `converter-pdf-para-excel.html` são páginas indexadas e ferramentas funcionais. Elas combinam intenção de busca, explicação e execução da tarefa. Transformá-las imediatamente em páginas apenas informativas seria uma alteração de produto e SEO, não uma simples migração de framework.

Se no futuro o negócio decidir exigir cadastro antes de qualquer conversão, essa mudança deve ser testada como um experimento separado, com métricas de conversão orgânica e receita. Ela não faz parte da migração inicial para Next.js.

## 3. Situação atual observada

- O FastAPI monta o diretório `frontend/` na raiz por meio de `StaticFiles`.
- O Docker atual copia o backend Python e o frontend estático para uma única imagem.
- `convert.html` é um seletor público de formato.
- `converter-pdf-para-ofx.html` é uma página indexável com conversor funcional.
- `converter-pdf-para-excel.html` é uma página indexável com conversor funcional.
- `ofx-convert.html` é um conversor legado com `noindex,follow`, mas foi informado como indexado pelo Google.
- O link “Nova conversão” da área atual leva para `ofx-convert.html`, misturando a jornada autenticada com a pública.
- A API já possui sessão por cookie HttpOnly e também identidade anônima por cookie. A migração precisa preservar essa compatibilidade enquanto remove gradualmente a dependência do token no JavaScript.

## 4. Manifesto de URLs protegidas

As URLs abaixo foram informadas como indexadas em 27/08/2026. Até que uma fase específica autorize uma migração individual, cada uma deve manter URL, código HTTP, canonical, indexabilidade, conteúdo principal e links internos.

| URL | Última data informada | Regra durante a migração da área autenticada |
| --- | --- | --- |
| `/blog/o-que-e-ofx-e-como-usar/` | 21/08/2026 | Não alterar |
| `/converter-pdf-para-ofx.html` | 21/08/2026 | Manter conteúdo e conversor público |
| `/contato.html` | 18/08/2026 | Não alterar |
| `/blog/` | 17/08/2026 | Não alterar |
| `/convert.html` | 17/08/2026 | Manter como seletor público |
| `/` | 16/08/2026 | Não alterar |
| `/ofx-convert.html` | 06/08/2026 | Tratar como legado; não corrigir indexação no mesmo rollout |
| `/blog/checklist-fechamento-financeiro-com-ofx/` | 03/08/2026 | Não alterar |
| `/planos.html` | 03/08/2026 | Não alterar |
| `/converter-pdf-para-excel.html` | 03/08/2026 | Manter conteúdo e conversor público |
| `/politica-de-privacidade.html` | 20/07/2026 | Não alterar |
| `/blog/7-erros-comuns-na-conciliacao-bancaria/` | 18/07/2026 | Não alterar |
| `/blog/como-validar-ofx-antes-de-importar-no-erp/` | 04/07/2026 | Não alterar |

Qualquer mudança numa dessas rotas exige um PR de SEO próprio. Alterar layout, conteúdo e tecnologia ao mesmo tempo dificulta saber qual mudança afetou o ranking.

## 5. Arquitetura de destino da primeira etapa

### 5.1 Divisão de responsabilidade por rota

| Prefixo ou arquivo | Responsável inicial | Renderização | Indexação |
| --- | --- | --- | --- |
| URLs públicas existentes | HTML/JavaScript atual | Arquivo estático | Conforme estado atual |
| `/app/` e `/app/**` | Next.js App Router + TypeScript | Export estático com hidratação no cliente | `noindex`, fora do sitemap |
| `/api/**`, `/auth/**`, `/report/**` e endpoints atuais | FastAPI | API | Não indexável |
| `/_next/**` | Build do Next.js | Assets imutáveis | Assets, não páginas |

O projeto Next.js pode declarar as rotas `/app/**` diretamente e gerar arquivos estáticos. O deploy copia apenas os diretórios permitidos, como `out/app` e `out/_next`, sem sobrescrever os HTMLs públicos existentes. Assets próprios colocados em `public/` devem usar um namespace, por exemplo `/app-assets/`.

### 5.2 Build e runtime

1. Uma etapa Node instala dependências e executa o build do Next.js com `output: "export"`.
2. O resultado estático permitido é copiado para a imagem final.
3. A imagem final continua executando somente o FastAPI.
4. O FastAPI continua servindo os arquivos antigos, `/app/**` e `/_next/**` no mesmo domínio.

Essa arquitetura não usa SSR, Server Actions, Route Handlers dinâmicos nem leitura server-side de cookies pelo Next.js. A sessão é consultada no navegador por `/auth/me`, e o FastAPI permanece como autoridade de autenticação, planos, cotas, conversões e relatórios.

### 5.3 Por que usar export estático primeiro

- Evita introduzir um processo Node em produção.
- Evita proxy, CORS e cookies entre hosts.
- Permite rollback copiando novamente os arquivos estáticos anteriores.
- Isola a modernização nas rotas não indexadas.
- Mantém aberta a possibilidade de adotar um runtime Next.js mais tarde, se houver necessidade real de SSR ou BFF.

## 6. Infraestrutura e custo

### Opção recomendada: um serviço no Render

- Mesmo serviço web e mesmo domínio.
- Node existe apenas durante o build.
- Incremento esperado de compute mensal: zero.
- Possíveis impactos: build mais longo, imagem maior e mais arquivos estáticos no deploy.
- Métricas a acompanhar: duração e memória do build, tamanho da imagem, tempo de deploy, uso de memória do FastAPI e taxa de erro de assets `/_next/**`.

### Opção de contingência: Static Site separado

Se o build conjunto se mostrar instável, a área Next.js pode ser publicada como Static Site em `app.ofxsimples.com.br`. O compute estático do Render é gratuito, mas surgem custos operacionais: configuração de domínio, cookies, CORS, deploy separado e observabilidade dividida. Essa opção só deve ser usada após um spike provar que o serviço único não é viável.

### Opção adiada: três serviços

Gateway + servidor Next.js + FastAPI adicionariam pelo menos dois processos de produção. Pelos valores públicos do Render na data deste plano, dois serviços Starter adicionais começariam em aproximadamente US$ 14/mês; usando Standard para o Next.js, o acréscimo seria maior. O custo mais relevante, porém, é a operação: health checks, proxy, deploy coordenado, logs, rollback e novos modos de falha.

Reavaliar a divisão somente se pelo menos um destes gatilhos ocorrer:

- necessidade comprovada de SSR nas páginas públicas;
- adoção de Server Actions ou BFF;
- necessidade de escalar frontend e API de forma independente;
- deploys do frontend bloqueados pelo tempo ou risco do deploy da API;
- build estático incapaz de atender uma funcionalidade de produto aprovada.

## 7. Plano passo a passo

As durações abaixo são faixas de planejamento, não compromissos de calendário. Cada fase só começa após o gate da fase anterior.

### Fase 0 — Baseline e contrato de SEO (semana 1)

Entregas:

1. Exportar do Google Search Console os períodos de 28 e 90 dias.
2. Guardar cliques, impressões, CTR e posição por URL e consulta.
3. Separar marca e não marca; registrar dispositivo e país.
4. Criar o manifesto automatizado das 13 URLs protegidas.
5. Para cada URL, capturar:
   - status HTTP e cadeia de redirects;
   - canonical;
   - `title`, description e robots;
   - H1 e marcador de conteúdo principal;
   - dados estruturados;
   - links internos relevantes;
   - tamanho do HTML e métricas de resposta.
6. Registrar screenshots desktop e mobile das jornadas críticas.
7. Documentar feature flags e rollback antes do primeiro deploy.

Gate de saída:

- baseline arquivada;
- contrato executável no CI;
- nenhuma URL protegida depende de memória manual para validação.

### Fase 1 — Fundação do Next.js e deploy escuro (semana 2)

Entregas:

1. Criar a aplicação Next.js com App Router, TypeScript, lint e testes.
2. Configurar export estático.
3. Criar somente `/app/`, `/app/entrar/` se necessário e uma página 404 interna.
4. Aplicar `noindex` por metadata e cabeçalho `X-Robots-Tag` nas rotas `/app/**`.
5. Não adicionar `/app/**` ao sitemap nem aos links públicos.
6. Integrar o build multi-stage ao Docker.
7. Copiar o output por allowlist para impedir sobrescrita de páginas públicas.
8. Garantir que uma rota inexistente em `/app/**` retorne 404 e não um HTML genérico com status 200.
9. Fazer deploy com a nova área inacessível pela navegação normal.

Gate de saída:

- as 13 URLs protegidas não mudaram;
- assets `/_next/**` carregam sem erros;
- `/app/**` está fora do índice e do sitemap;
- rollback do artefato foi ensaiado.

### Fase 2 — Sessão e shell autenticado (semanas 3 e 4)

Entregas:

1. Implementar o shell visual da área logada: cabeçalho, menu, responsividade, loading, erro e sessão expirada.
2. Consumir `/auth/me` usando cookie HttpOnly.
3. Remover do código novo a necessidade de ler token de autenticação em `localStorage`.
4. Implementar renovação de sessão e logout.
5. Criar uma camada única de cliente HTTP com tratamento de `401`, `403`, `409`, `429` e erros de rede.
6. Reproduzir gradualmente visão da conta, plano, cota, histórico, faturamento e perfil.
7. Manter `client-area.html` como fallback controlado por feature flag.

Gate de saída:

- login, refresh e logout testados em desktop e mobile;
- sessão expirada não vira sessão anônima silenciosamente;
- o painel antigo ainda pode ser reativado sem deploy de banco.

### Fase 3 — Contrato de identidade da conversão (semanas 4 e 5)

Essa fase pode começar em paralelo com as telas finais da fase 2, mas deve terminar antes de mudar qualquer link de conversão.

Entregas:

1. Cobrir com testes de integração todos os endpoints de upload, processamento, consulta e download.
2. Testar usuário com cookie autenticado e cookie anônimo simultaneamente.
3. Confirmar que a identidade autenticada recebe o consumo de cota e o histórico.
4. Confirmar que sessão inválida retorna erro autenticado ou exige refresh, sem consumir cota anônima.
5. Confirmar isolamento: um usuário não acessa resultado de outro usuário ou anônimo.
6. Adicionar telemetria com `source_page`, `identity_type`, `quota_scope` e `organization_id` quando aplicável, sem registrar tokens ou dados sensíveis.

Gate de saída:

- o backend apresenta o mesmo comportamento correto independentemente de a requisição vir do HTML antigo ou do Next.js;
- não existe caminho conhecido em que cliente logado seja contabilizado como anônimo.

### Fase 4 — Conversor autenticado em `/app/converter/` (semanas 5 a 7)

Entregas:

1. Recriar upload, progresso, preview, erro, retry e download no Next.js.
2. Preservar os formatos suportados e a semântica dos endpoints atuais.
3. Aceitar `?formato=ofx` e `?formato=excel` para preservar intenção.
4. Exibir plano, páginas disponíveis e limites antes do envio.
5. Vincular a conversão ao histórico autenticado.
6. Preparar o frontend para o processamento assíncrono: estado persistente do job, polling ou SSE e retomada após reload.
7. Alterar “Nova conversão” da área Next para `/app/converter/`.
8. Manter o conversor legado disponível como rollback.

Gate de saída:

- paridade funcional documentada;
- happy path e erros críticos validados em navegador real;
- nenhuma alteração nas páginas indexadas;
- métricas distinguem conversões públicas, legadas e internas.

### Fase 5 — Direcionar clientes autenticados (semanas 8 e 9)

Entregas:

1. Mudar o pós-login para `/app/` por feature flag.
2. Mudar links internos autenticados para `/app/converter/`.
3. Nas páginas públicas de conversão, consultar a sessão sem bloquear a renderização do conteúdo público.
4. Para sessão válida, mostrar CTA para o conversor interno; não redirecionar automaticamente no primeiro rollout.
5. Alterar o `next` de login/cadastro para `/app/converter/?formato=...`.
6. Medir por pelo menos duas semanas:
   - início e conclusão da conversão;
   - falha por etapa;
   - login solicitado durante a jornada;
   - usuário autenticado ainda convertendo na página pública;
   - divergência de cota ou histórico;
   - tráfego orgânico nas páginas públicas.

Gate de saída:

- ausência de regressão relevante de conversão e autenticação;
- nenhuma divergência de titularidade ou cota;
- Search Console e analytics sem anomalia sustentada nas páginas públicas.

Somente depois desse gate decidir se haverá redirecionamento automático de clientes autenticados. Manter o CTA também é uma solução válida e de menor risco.

### Fase 6 — Novas páginas SEO em Next.js (semanas 10 a 17)

Antes de reescrever páginas já ranqueadas, publicar conteúdo novo em URLs novas, por exemplo `/guias/**`.

Requisitos:

1. Conteúdo original, sem duplicar páginas existentes.
2. HTML principal presente no arquivo exportado, sem depender de JavaScript para título e conteúdo.
3. Canonical absoluto e autorreferente.
4. Metadata, Open Graph, dados estruturados e breadcrumbs válidos.
5. Sitemap e links internos atualizados de forma intencional.
6. 404 real para URLs inexistentes.
7. Core Web Vitals e acessibilidade dentro do orçamento definido.
8. Monitoramento por quatro a oito semanas antes de migrar uma página indexada existente.

Gate de saída:

- Google rastreou e indexou as novas páginas;
- conteúdo renderizado e canonical estão corretos;
- não há aumento de soft 404, páginas duplicadas ou erros de assets.

### Fase 7 — Migração opcional das páginas indexadas existentes

Essa fase é opcional. Se HTML/JavaScript continuar funcionando bem nas páginas públicas, não existe obrigação técnica de migrá-las.

Para cada página escolhida:

1. Selecionar primeiro a URL de menor tráfego e menor receita com base no Search Console e analytics.
2. Congelar uma cópia do HTML e uma captura visual anterior.
3. Reproduzir no Next.js a mesma URL exata, incluindo `.html` quando existir.
4. Manter intenção, conteúdo principal, title, description, canonical, structured data e links.
5. Não usar redirect quando a URL não mudou.
6. Não combinar troca de framework, redesign e reescrita de conteúdo no mesmo PR.
7. Liberar para uma URL por vez.
8. Monitorar por 14 a 28 dias antes da próxima URL.
9. Migrar home e conversores de maior tráfego por último.

Rollback imediato se ocorrer:

- `noindex` ou canonical incorreto;
- resposta diferente de 200 na URL válida;
- conteúdo principal ausente no HTML inicial;
- soft 404 ou redirect inesperado;
- quebra persistente de assets;
- queda orgânica sustentada fora da variação histórica e sem outra explicação conhecida.

### Fase 8 — Área de empresas

A área de empresas deve usar o shell e o conversor autenticado já estabilizados. Ela não deve ser implementada apenas como telas; exige primeiro um modelo de autorização e cobrança multiempresa.

Entidades mínimas:

- `organizations`;
- `organization_memberships` com papéis `master`, `admin` e `member`;
- `organization_invitations`;
- assinatura e plano vinculados à organização;
- limites opcionais por membro;
- jobs de conversão com usuário executor e organização pagadora;
- registro de auditoria para convites, limites, conversões e alterações de papel.

Regras mínimas:

1. O usuário master cria convites, remove membros e configura limites dentro do plano contratado.
2. Cada conversão registra `actor_user_id` e `organization_id` quando executada no contexto empresarial.
3. O limite do membro e o limite total da organização são verificados e reservados de forma atômica antes de enviar o job à fila.
4. O worker recebe apenas um identificador opaco do job; identidade, organização, limites e arquivo ficam em armazenamento controlado pelo backend.
5. Retry do worker é idempotente e não consome a cota duas vezes.
6. O usuário escolhe claramente entre espaço pessoal e empresa quando possuir ambos.
7. Nenhuma URL da empresa é indexável ou incluída no sitemap.

Sequência sugerida:

1. PRD de papéis, limites e cobrança.
2. Migrações aditivas e compatíveis com a produção.
3. API de organizações, membros, convites e seleção de contexto.
4. Reserva de cota e criação idempotente de job.
5. Telas de empresa no Next.js.
6. Auditoria, observabilidade e rollout para uma empresa piloto.

## 8. Estratégia específica para `ofx-convert.html`

Essa URL precisa de uma decisão separada porque combina sinais conflitantes: a página declara `noindex`, o `robots.txt` impede seu rastreamento e, ainda assim, ela foi informada como indexada. Bloquear o rastreamento pode impedir o Google de enxergar uma diretiva `noindex` atualizada.

Durante as fases 0 a 5:

- não mudar URL, canonical, robots e conteúdo dessa página no mesmo rollout da área Next;
- medir acessos orgânicos, backlinks, conversões e links internos;
- retirar gradualmente links autenticados que apontam para ela;
- manter rollback funcional.

Depois, abrir um PR de SEO específico para escolher entre:

- torná-la uma página pública canônica com propósito próprio;
- redirecioná-la com 301 para a página pública equivalente;
- permitir rastreamento temporário para que o `noindex` seja processado e então removê-la do índice.

A escolha depende dos dados de Search Console e backlinks. Não deve ser inferida apenas pelo nome do arquivo.

## 9. Testes e observabilidade

### Contratos automatizados

- snapshot semântico das 13 URLs protegidas;
- status e redirects;
- canonical e robots;
- conteúdo principal no HTML;
- 404 real;
- ausência de `/app/**` no sitemap;
- assets Next com cache e hash;
- nenhum arquivo antigo sobrescrito pelo build Next.

### Identidade e autorização

- anônimo converte e consome cota anônima;
- autenticado converte no Next e consome cota autenticada;
- autenticado converte na página pública e continua autenticado;
- cookie autenticado + cookie anônimo resolve para autenticado;
- sessão expirada não faz downgrade para anônimo;
- usuário A não acessa conversão de B;
- membro empresarial consome seu limite e o limite da organização;
- retry de job não duplica consumo.

### Métricas operacionais e de produto

- conversões iniciadas, concluídas e falhas por `source_page`;
- identidade anônima, pessoal ou empresarial;
- divergências entre titular do job, histórico e cota;
- tempo de fila e de processamento;
- erros de sessão e refresh;
- erros `404` e `5xx` de `/_next/**` e `/app/**`;
- cliques, impressões, CTR e posição das URLs públicas;
- taxa de login e conclusão de conversão por página de entrada.

Alertas nunca devem incluir arquivo do cliente, token, cookie ou dados bancários.

## 10. Sequência de PRs recomendada

1. ADR e contrato de URLs/SEO.
2. Scaffold do Next.js e build estático, sem navegação pública.
3. Shell, sessão por cookie e cliente HTTP.
4. Painel e histórico em modo de leitura.
5. Testes e telemetria da precedência de identidade.
6. Conversor interno em Next.js.
7. Feature flag de pós-login e navegação interna.
8. CTA autenticado nas páginas públicas.
9. Preparação do modelo multiempresa.
10. Área de empresas e limites.
11. Novas páginas SEO em Next.js.
12. Migrações individuais de páginas existentes, somente se justificadas.

Cada PR deve ter um único objetivo, evidências de teste e rollback descrito. Alterações de banco devem ser aditivas e compatíveis com a versão anterior durante toda a janela de deploy.

## 11. Decisões que ainda precisam de dados

- Manter apenas o CTA ou redirecionar automaticamente clientes autenticados que chegam às páginas públicas.
- Destino definitivo de `ofx-convert.html`.
- Manter conversões anônimas indefinidamente ou introduzir cadastro como experimento posterior.
- Regras comerciais exatas de limite empresarial: por páginas, arquivos, valor, período e excedente.
- Se um membro pode pertencer a várias empresas e como seleciona o contexto padrão.
- Momento em que SSR traria benefício suficiente para justificar um servidor Next.js.

Nenhuma dessas decisões bloqueia o início pelas fases 0 a 4.

## 12. Definição de sucesso

A primeira etapa estará concluída quando:

- a área autenticada principal estiver em Next.js sob `/app/**`;
- toda nova conversão iniciada dentro da área autenticada usar `/app/converter/`;
- um cliente autenticado nunca for contabilizado como anônimo, mesmo se usar uma página pública durante a transição;
- as 13 URLs protegidas mantiverem seus contratos técnicos;
- não houver queda orgânica sustentada atribuível ao rollout;
- o frontend antigo puder ser removido da área logada depois da janela de observação;
- a fundação suportar contexto empresarial sem reescrever novamente o frontend.

## 13. Referências técnicas

- [Next.js — Static Exports](https://nextjs.org/docs/app/guides/static-exports)
- [Next.js — Single-Page Applications](https://nextjs.org/docs/app/guides/single-page-applications)
- [Google Search — mudança de infraestrutura sem alteração de URL](https://developers.google.com/search/docs/crawling-indexing/site-move-no-url-changes)
- [Google Search — JavaScript SEO](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)
- [Render — Static Sites](https://render.com/docs/static-sites)
- [Render — Compute Plans](https://render.com/docs/compute-plans)
- [Render — Workspace Plans](https://render.com/docs/new-workspace-plans)
