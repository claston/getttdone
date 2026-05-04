from fastapi import APIRouter, Depends, HTTPException

from app.application import (
    AccessControlService,
    ContactDeliveryError,
    ContactProviderNotConfiguredError,
    ContactService,
)
from app.dependencies import get_access_control_service, get_contact_service
from app.schemas import CheckoutIntentRequest, CheckoutIntentResponse

router = APIRouter()


def _format_price_brl(price_cents: int) -> str:
    value = int(price_cents)
    reais = value // 100
    cents = value % 100
    return f"R$ {reais},{cents:02d}"


@router.post("/checkout/intents", response_model=CheckoutIntentResponse, status_code=202)
async def create_checkout_intent(
    payload: CheckoutIntentRequest,
    access_control_service: AccessControlService = Depends(get_access_control_service),
    contact_service: ContactService = Depends(get_contact_service),
) -> CheckoutIntentResponse:
    clean_name = payload.name.strip()
    clean_email = payload.email.strip().lower()
    clean_whatsapp = payload.whatsapp.strip()
    clean_plan_code = payload.plan_code.strip().lower()
    clean_document = (payload.document or "").strip()
    clean_notes = (payload.notes or "").strip()

    if not payload.accepted_terms:
        raise HTTPException(status_code=400, detail="Terms must be accepted before checkout.")
    if not clean_name or not clean_email or not clean_whatsapp or not clean_plan_code:
        raise HTTPException(status_code=400, detail="name, email, whatsapp, and plan_code are required.")
    if "@" not in clean_email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    try:
        intent = access_control_service.create_checkout_intent(
            plan_code=clean_plan_code,
            customer_name=clean_name,
            customer_email=clean_email,
            customer_whatsapp=clean_whatsapp,
            customer_document=clean_document or None,
            customer_notes=clean_notes or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    plan_price = _format_price_brl(int(intent["price_cents"]))
    admin_subject = f"[Checkout] Novo pedido {intent['id']} - {intent['plan_name']}"
    admin_text_lines = [
        "Novo pedido de plano recebido (fluxo manual sem gateway).",
        "",
        f"Pedido: {intent['id']}",
        f"Plano: {intent['plan_name']} ({intent['plan_code']})",
        f"Preco: {plan_price}/{intent['billing_period']}",
        f"Nome: {clean_name}",
        f"Email: {clean_email}",
        f"WhatsApp: {clean_whatsapp}",
        f"Documento: {clean_document or '-'}",
        "",
        "Observacoes:",
        clean_notes or "-",
        "",
        "Proximo passo: responder este cliente com dados Pix e ativar plano manualmente.",
    ]
    customer_subject = f"Recebemos seu pedido de plano ({intent['plan_name']})"
    customer_text_lines = [
        "Recebemos seu pedido de contratacao no OFX Simples.",
        "",
        f"Pedido: {intent['id']}",
        f"Plano: {intent['plan_name']}",
        f"Preco: {plan_price}/{intent['billing_period']}",
        "",
        "Nosso time vai enviar os dados de pagamento via Pix por e-mail.",
        "A ativacao do plano e manual apos confirmacao de pagamento.",
    ]

    try:
        admin_delivery = await contact_service.send_text_email(
            to_email=contact_service.support_email,
            subject=admin_subject,
            text="\n".join(admin_text_lines),
            reply_to=clean_email,
        )
        customer_delivery = await contact_service.send_text_email(
            to_email=clean_email,
            subject=customer_subject,
            text="\n".join(customer_text_lines),
        )
    except ContactProviderNotConfiguredError:
        raise HTTPException(status_code=503, detail="Checkout contact channel is not configured.")
    except ContactDeliveryError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to deliver checkout emails: {exc}")

    return CheckoutIntentResponse(
        intent_id=str(intent["id"]),
        status=str(intent["status"]),
        created_at=str(intent["created_at"]),
        plan_code=str(intent["plan_code"]),
        plan_name=str(intent["plan_name"]),
        price_cents=int(intent["price_cents"]),
        currency=str(intent["currency"]),
        billing_period=str(intent["billing_period"]),
        admin_delivery_mode=admin_delivery.delivery_mode,
        customer_delivery_mode=customer_delivery.delivery_mode,
        message="Pedido recebido. Vamos enviar os dados Pix por email e ativar o plano manualmente.",
    )
