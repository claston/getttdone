from __future__ import annotations

from typing import Any

import pytest

from app.application import pdf_parser as pdf_parser_module
from app.application.default_conversion_pipeline import _resolve_ofx_account_type
from app.application.ofx_writer import build_ofx_statement

BANRISUL_EXAMPLE_CASES: dict[str, dict[str, Any]] = {
    "conta_corrente_monospace": {
        "profile": "banrisul_extrato_texto_movimentos_conta_corrente_v1",
        "amounts": [700.14, 25.92, 14.12, 6.0, 0.0, 9.0, -47.0, -2.38],
        "text": """
        B A N R I S U L AGENCIA: CONTA..: NOME...: IDENTIFICACAO:
        DIA HISTORICO DOCUMENTO V A L O R MOVIMENTOS DA CONTA CORRENTE
        SALDO ANT EM 29/10/2021 .991,65 MOVIMENTOS NOV/2021
        01 TED - SPB 024059 700,14
        VERO BANRICARD ALIMENTACAO 314485 25,92
        VERO BANRICOMPRAS A PRAZO 231105 14,12
        VERO CARTAO CREDITO 780615 6,00
        PIX 746325 0,00
        PIX 769405 9,00
        PAGAMENTO TITULO 116635 47,00-
        PAGAMENTO TITULO 116636 .02,38-
        """,
    },
    "consulta_operacoes": {
        "profile": "banrisul_consulta_operacoes_recibos_v1",
        "amounts": [11000.0, 68006.40, 73573.60],
        "text": """
        Impressão - Banrisul BANCO DO ESTADO DO RIO GRANDE DO SUL S.A.
        Consulta Operações / Emite Recibos
        Data NSU Situação Valor Operação Agência/Conta Complemento
        02/03/2022 01278927371 EFETUADA R$ 11.000,00 Transferência
        0041 - 06223069 - Crédito - POSTO DE COMBUSTIVEIS
        02/03/2022 01278930140 EFETUADA R$ 68.006,40 Transferência
        1143 - 06010154 - CRÉDITO - DISTRIBUIDORA DE COMBUSTÍVEL
        02/03/2022 01279185275 EFETUADA R$ 73.573,60 Transferência
        1143 - 06010154 - CRÉDITO - DISTRIBUIDORA DE COMBUSTÍVEL
        """,
    },
    "operacoes_pix": {
        "profile": "banrisul_operacoes_pix_v1",
        "amounts": [541.82, -100.0, -89.02],
        "text": """
        Impressão - Banrisul Banco do Estado do Rio Grande do Sul Operações Pix
        Nome/Razão Social CPF/CNPJ Operação Situação Pagador/Recebedor Data Valor
        Pix Recebido Efetivado de SOLANGE 31/05/2022 R$ 541,82
        Pix Enviado Efetivado para TATIANE 31/05/2022 R$ 100,00
        Pix Enviado Efetivado para AMAZON.COM.BR 27/05/2022 R$ 89,02
        """,
    },
    "recibo_pagamento": {
        "profile": "banrisul_recibo_pagamento_v1",
        "amounts": [-63477.38],
        "text": """
        Banrisul Recibo de Pagamento Número: Data: 01/04/2022 Hora: 14:01:32
        Canal: Office Banking Tipo Pagamento: Títulos Banrisul / Outros Bancos
        Emissor: BCO SANTANDER Ag./Conta Débito:
        Valor: R$ 63.350,94 Valor Juros: R$ 126,44
        Data Débito: 01/04/2022 Data Vencimento: 31/03/2022
        Pagador Final: CPF/CNPJ Pagador Final Beneficiário Original
        """,
    },
    "demonstrativo_cdb": {
        "profile": "banrisul_demonstrativo_cdb_automatico_v1",
        "amounts": [-247.71, -359.94, 222.60, 200.0, -1334.21],
        "text": """
        banrisul DEMONSTRATIVO DE MOVIMENTAÇÃO CDB AUTOMATICO - MENSAL
        Período de Referência 01/04/2025 - 30/04/2025
        IDENTIFICAÇÃO DAS OPERAÇÕES MOVIMENTAÇÕES
        Data da Aplicação Valor Modalidade Prazo Taxa Data Vencimento Data Histórico
        Valor Rendimento Bruto IOF IR Valor Líquido Posição Final do Período
        01/04/2025 APLICACAO 247,71
        02/04/2025 APLICACAO 359,94
        04/04/2025 RESGATE 220,03 3,31 0,74 222,60
        25/04/2025 RESGATE 200,00 200,00
        28/04/2025 APLICACAO 1.334,21
        SOMATÓRIO DAS OPERAÇÕES RESGATADAS NO MÊS
        """,
    },
    "fatura_historico": {
        "profile": "banrisul_fatura_cartao_historico_transacoes_v1",
        "amounts": [-377.98, -58.45, 6896.92, 119.01, -32.90, 18.0, -18.0],
        "text": """
        Banrisul FATURA SETEMBRO/2025 HISTÓRICO DE TRANSAÇÕES
        LUCIA - NR. 0114 US$ R$ BanriClube PÁGINA 2/4
        11/08 ZAF 377,98
        13/08 CASA DO PAPEL 01/05 58,45
        20/08 PAGAMENTO -6.896,92
        20/08 MERCADOPAGO CARLOS SAO PAULO -119,01
        22/08 APPLE.COM/BILL 32,90
        10/09 DESC. ANUID.011406/12 -18,00
        10/09 ANUIDADEINT DIFER 06/12 0114 18,00
        TOTAL DE GASTOS 4.660,34
        """,
    },
    "cartao_credito_simples": {
        "profile": "banrisul_extrato_cartao_credito_simples_v1",
        "amounts": [-300.75, -94.92, -58.45, -222.42, 5941.67, -196.22, -32.90, -10.95],
        "text": """
        Banrisul Extrato de Cartão de Crédito janeiro/2026
        14/04/2025 CLARO R$ 300,75
        16/07/2025 MERCADOPAGO R$ 94,92
        12/08/2025 CASA DO PAPEL 05/05 R$ 58,45
        24/09/2025 PORTO SEGURO CIA SE 04/10 R$ 222,42
        17/12/2025 PGTO HOME/OFFICE BANKING R$ -5.941,67
        19/12/2025 CASA DO PAPEL PORTO ALEGRE BRA R$ 196,22
        21/12/2025 APPLE.COM/BILL SAO PAULO BRA R$ 32,90
        22/12/2025 MERCEARIA *FRUTEIRA PORTO R$ 10,95
        """,
    },
}


@pytest.mark.parametrize("case_name", BANRISUL_EXAMPLE_CASES)
def test_parse_pdf_transactions_supports_banrisul_visual_examples(case_name: str, monkeypatch) -> None:
    case = BANRISUL_EXAMPLE_CASES[case_name]
    monkeypatch.setattr(pdf_parser_module, "_read_native_pdf_page_texts", lambda raw_bytes: [case["text"]])
    monkeypatch.setattr(pdf_parser_module, "_read_layout_native_pdf_page_texts", lambda raw_bytes: [case["text"]])

    result = pdf_parser_module.parse_pdf_transactions(b"%PDF synthetic")

    assert result.layout.layout_name == case["profile"]
    assert [transaction.amount for transaction in result.transactions] == case["amounts"]
    ofx = build_ofx_statement(
        result.transactions,
        account_type="credit_card" if case_name in {"fatura_historico", "cartao_credito_simples"} else None,
    )
    assert ofx.count("<STMTTRN>") == len(case["amounts"])


@pytest.mark.parametrize("case_name", ["fatura_historico", "cartao_credito_simples"])
def test_banrisul_card_layouts_resolve_credit_card_ofx_account_type(case_name: str) -> None:
    case = BANRISUL_EXAMPLE_CASES[case_name]

    account_type = _resolve_ofx_account_type(
        extension="pdf",
        filename="banrisul.pdf",
        raw_bytes=b"",
        extracted_text=case["text"],
        layout_inference_name=case["profile"],
    )

    assert account_type == "credit_card"
