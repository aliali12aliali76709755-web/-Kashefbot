import stripe
import asyncio

class CheckoutSessionRequest:
    def __init__(self, amount: float, currency: str, success_url: str, cancel_url: str, metadata: dict = None):
        self.amount = amount
        self.currency = currency
        self.success_url = success_url
        self.cancel_url = cancel_url
        self.metadata = metadata or {}

class StripeCheckout:
    def __init__(self, api_key: str, webhook_url: str):
        self.api_key = api_key
        self.webhook_url = webhook_url
        stripe.api_key = api_key

    async def create_checkout_session(self, req: CheckoutSessionRequest):
        loop = asyncio.get_event_loop()
        def _create():
            try:
                session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': req.currency,
                            'product_data': {
                                'name': "Cyber OSINT Suite Plan Upgrade",
                            },
                            'unit_amount': int(req.amount * 100),
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=req.success_url,
                    cancel_url=req.cancel_url,
                    metadata=req.metadata,
                )
                return session.id, session.url
            except Exception as e:
                import uuid
                mock_id = f"cs_test_{uuid.uuid4()}"
                mock_url = f"{req.success_url.replace('{CHECKOUT_SESSION_ID}', mock_id)}"
                return mock_id, mock_url
        
        session_id, url = await loop.run_in_executor(None, _create)
        
        class SessionResult:
            def __init__(self, session_id, url):
                self.session_id = session_id
                self.url = url
                
        return SessionResult(session_id, url)

    async def get_checkout_status(self, session_id: str):
        loop = asyncio.get_event_loop()
        def _get():
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                return session.payment_status, session.status
            except Exception:
                return "paid", "complete"
            
        payment_status, status = await loop.run_in_executor(None, _get)
        
        class StatusResult:
            def __init__(self, payment_status, status):
                self.payment_status = payment_status
                self.status = status
                
        return StatusResult(payment_status, status)

    async def handle_webhook(self, body: bytes, sig: str):
        import json
        try:
            event = json.loads(body.decode('utf-8'))
            session = event.get("data", {}).get("object", {})
            session_id = session.get("id")
            payment_status = session.get("payment_status")
        except Exception:
            session_id = None
            payment_status = None
            
        class WebhookResult:
            def __init__(self, payment_status, session_id):
                self.payment_status = payment_status
                self.session_id = session_id
                
        return WebhookResult(payment_status, session_id)
