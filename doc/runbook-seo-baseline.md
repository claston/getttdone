# Runbook do baseline e contrato de SEO

- Status: ativo
- Criado em: 28/08/2026
- Manifesto: `seo/protected-routes.json`
- Primeiro baseline: `seo/baseline/2026-08-28/`

## 1. Objetivo

Este runbook protege as páginas públicas que sustentam a aquisição orgânica do OFX Simples durante a modernização do frontend.

O contrato não impede mudanças intencionais. Ele exige que qualquer alteração numa URL protegida seja identificada, revisada como mudança de SEO e acompanhada por uma atualização explícita do manifesto.

## 2. O que está protegido

O manifesto contém as 13 URLs informadas como indexadas em 27/08/2026. Para cada rota são registrados:

- arquivo fonte atual;
- última data de indexação informada;
- status HTTP esperado;
- ausência esperada de redirects;
- title e description;
- canonical e robots;
- H1;
- tipos encontrados nos dados estruturados;
- marcadores do conteúdo principal;
- presença esperada no sitemap;
- necessidade de screenshot visual.

Os testes estão em `backend/tests/test_protected_seo_contract.py`.

## 3. Baseline técnico de produção

Para capturar novamente o estado da produção:

```powershell
backend\venv\Scripts\python.exe scripts\capture_seo_baseline.py `
  --base-url https://www.ofxsimples.com.br `
  --output seo\baseline\AAAA-MM-DD\technical-production.json `
  --fail-on-drift
```

O arquivo resultante registra:

- status e URL final;
- cadeia de redirects;
- tempo observado da resposta;
- Content-Type, Cache-Control e X-Robots-Tag;
- tamanho e SHA-256 do HTML;
- title, description, canonical e robots;
- H1 e tipos JSON-LD;
- links internos resolvidos;
- diferenças em relação ao manifesto.

O tempo de resposta é uma amostra pontual. Ele deve ser comparado com monitoramento contínuo antes de fundamentar uma decisão de performance.

### Interpretação do resultado

- `[OK]`: a resposta observada corresponde ao contrato semântico.
- `[DRIFT]`: pelo menos um campo divergiu ou a captura falhou.
- Exit code `1` com `--fail-on-drift`: não prosseguir com o rollout até explicar a diferença.

O script faz somente requisições GET e não envia cookies, arquivos ou dados de clientes.

## 4. Baseline visual

As rotas críticas são marcadas com `capture_screenshot: true` no manifesto.

Para capturar desktop e mobile:

```powershell
backend\venv\Scripts\python.exe scripts\capture_seo_screenshots.py `
  --base-url https://www.ofxsimples.com.br `
  --output-dir seo\baseline\AAAA-MM-DD\screenshots
```

O comando usa Chromium headless e gera:

- JPEG full-page desktop em `1440x1000`;
- JPEG full-page mobile em `390x844`;
- `screenshots.json` com rota, viewport, status, URL final, title e arquivo.

Os screenshots representam uma primeira visita sem sessão, inclusive com o banner de consentimento quando exibido. Não aceitar cookies automaticamente evita esconder uma regressão no consentimento.

## 5. Google Search Console

O Search Console contém dados privados e não está conectado ao ambiente de desenvolvimento. Os exports brutos não devem ser adicionados ao repositório sem uma decisão explícita sobre confidencialidade.

### Export obrigatório para fechar a Fase 0

No relatório “Resultados da pesquisa”, exportar:

1. Últimos 28 dias completos disponíveis.
2. Janela customizada de 90 dias terminando na mesma data completa.

Para cada período, guardar as dimensões:

- páginas;
- consultas;
- dispositivos;
- países;
- datas;
- filtros utilizados.

Registrar cliques, impressões, CTR e posição. Separar consultas de marca e não marca, documentando a regra usada para classificar a marca.

### Armazenamento seguro sugerido

Os arquivos brutos podem ser colocados localmente em:

```text
local/seo-baseline/2026-08-28/search-console/
├── 28-days/
└── 90-days/
```

O diretório `local/` já é ignorado pelo Git. Se for necessário compartilhar os exports entre agentes ou pessoas, usar armazenamento privado aprovado pelo projeto e registrar neste runbook apenas a localização e a data de corte, nunca credenciais.

Depois da análise, pode ser versionado um resumo sem consultas sensíveis contendo:

- total de cliques e impressões;
- CTR e posição agregados;
- desempenho das 13 URLs protegidas;
- divisão marca/não marca;
- divisão por dispositivo e país;
- data final dos dados.

## 6. Checklist antes de alterar uma página protegida

1. Confirmar que a URL consta em `seo/protected-routes.json`.
2. Capturar baseline técnico de produção antes da mudança.
3. Consultar os dados de 28 e 90 dias no Search Console.
4. Registrar screenshot desktop e mobile anterior.
5. Abrir PR com um único objetivo de SEO.
6. Explicar cada alteração de title, description, canonical, robots, H1, JSON-LD, conteúdo ou links.
7. Não combinar troca de framework, redesign e reescrita do conteúdo.
8. Executar os testes do contrato.
9. Descrever feature flag e rollback.
10. Depois do deploy, repetir captura técnica e screenshots.

## 7. Flags previstas para a Fase 1

As flags abaixo ainda não existem no código. A Fase 1 deve criá-las com default desligado antes de expor qualquer rota Next.js:

| Flag | Default | Efeito quando ativada | Rollback |
| --- | --- | --- | --- |
| `NEXT_APP_ROLLOUT_ENABLED` | `false` | Permite servir `/app/**` | Desligar e manter a área antiga |
| `NEXT_POST_LOGIN_ENABLED` | `false` | Envia o pós-login para `/app/` | Voltar para `client-area.html` |
| `NEXT_PUBLIC_AUTH_CTA_ENABLED` | `false` | Mostra CTA autenticado nas páginas públicas | Ocultar CTA sem mudar a página pública |
| `NEXT_AUTH_REDIRECT_ENABLED` | `false` | Redireciona sessão autenticada da página pública para `/app/converter/` | Desligar e voltar ao CTA |

Regras:

- nenhum deploy deve ativar todas as flags simultaneamente;
- a existência dos arquivos Next não implica habilitar a rota;
- o frontend HTML/JavaScript antigo permanece no artefato durante a janela de rollback;
- nenhuma flag pode alterar conteúdo para robôs com base em user-agent.

## 8. Rollback por tipo de problema

| Sinal | Ação imediata | Verificação posterior |
| --- | --- | --- |
| Status diferente de 200 ou redirect inesperado | Desativar a flag e restaurar artefato anterior | Reexecutar baseline técnico |
| Canonical, robots ou conteúdo principal incorreto | Reverter imediatamente a mudança da rota | Solicitar nova inspeção no Search Console |
| Assets `/_next/**` quebrados | Desativar `NEXT_APP_ROLLOUT_ENABLED` | Validar build e allowlist de cópia |
| Falha de login/pós-login | Desativar `NEXT_POST_LOGIN_ENABLED` | Validar cookie, refresh e `next` |
| Divergência de cota/histórico | Desativar conversor novo | Auditar identidade e titularidade do job |
| Anomalia orgânica sustentada | Pausar novos rollouts | Comparar 7, 28 e 90 dias e fatores externos |

Problemas técnicos objetivos, como `noindex`, canonical incorreto, soft 404 ou conteúdo ausente, não devem aguardar uma tendência estatística para rollback.

## 9. Estado conhecido em 28/08/2026

- As 13 URLs responderam `200` na captura de produção.
- Nenhuma das 13 apresentou redirect.
- O contrato técnico de produção ficou sem drift.
- Seis jornadas críticas possuem screenshots desktop e mobile.
- `/ofx-convert.html` continua com `noindex,follow`, sem canonical, fora do sitemap e bloqueada no `robots.txt`.
- O conflito de indexação de `/ofx-convert.html` continua deliberadamente fora desta fase.
- Os exports privados de 28 dias e 90 dias foram verificados com data final comum em 26/08/2026.
- O gate operacional da Fase 0 foi encerrado em 28/08/2026.
