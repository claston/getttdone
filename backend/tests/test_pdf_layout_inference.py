from app.application.pdf_layout_inference import infer_pdf_layout


def test_infer_pdf_layout_prefers_nubank_profile_when_tokens_match() -> None:
    text = """
    06 NOV 2023 Total de entradas + 1.069,04
    Transferencia recebida pelo Pix BANCO TESTE
    Saldo do dia 4.583,57
    Total de saidas - 4.000,00
    Transferencia enviada pelo Pix FULANO
    """

    result = infer_pdf_layout(text)

    assert result.layout_name == "nubank_statement_ptbr"
    assert result.confidence >= 0.6


def test_infer_pdf_layout_prefers_itau_profile_when_tokens_match() -> None:
    text = """
    saldo em conta Limite da Conta utilizado Limite da Conta disponível
    extrato conta / lançamentos
    data lançamentos valor (R$) saldo (R$)
    13/04/2026 PIX TRANSF ERICA -2.835,00
    13/04/2026 SALDO DO DIA -4.142,48
    """

    result = infer_pdf_layout(text)

    assert result.layout_name == "itau_statement_ptbr"
    assert result.confidence >= 0.6


def test_infer_pdf_layout_falls_back_to_generic_profile() -> None:
    text = """
    01 JAN 2026
    PAGAMENTO FORNECEDOR ALFA
    980,00
    02 JAN 2026
    RECEBIMENTO CLIENTE BRAVO
    1500,00
    """

    result = infer_pdf_layout(text)

    assert result.layout_name == "generic_statement_ptbr"
    assert result.confidence >= 0.2


def test_infer_pdf_layout_prefers_santander_profile_when_tokens_match() -> None:
    text = """
    BANCO SANTANDER BRASIL S.A.
    EXTRATO DE CONTA CORRENTE
    agencia: 1234 conta: 00012345-6
    data historico documento valor (R$) saldo (R$)
    13/04/2026 PIX RECEBIDO CLIENTE 1.250,00 4.142,48
    """

    result = infer_pdf_layout(text)

    assert result.layout_name == "santander_statement_ptbr"
    assert result.confidence >= 0.55


def test_infer_pdf_layout_prefers_bradesco_profile_when_tokens_match() -> None:
    text = """
    BANCO BRADESCO S.A.
    EXTRATO MENSAL
    agencia 1234 conta 12345-6
    data historico valor saldo
    12/04/2026 TRANSFERENCIA PIX -250,00 2.845,10
    """

    result = infer_pdf_layout(text)

    assert result.layout_name == "bradesco_statement_ptbr"
    assert result.confidence >= 0.5
